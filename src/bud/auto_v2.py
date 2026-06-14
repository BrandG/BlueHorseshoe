"""DEPRECATED: use src/bud/auto_trader.py for live cron deployment.

BH FTMO V2 autonomous trader — limit + mid-entry production cells.

Counterpart to bh_ftmo_paper.py (rising_3bar). Reuses the v2 cell list and
evaluators from src/bh_briefing.py and replaces the email-out path with
OANDA order submission. Limit cells use LIMIT orders with GTD set to the
next H4 close. Mid cells use MARKET orders that fill immediately at the
just-closed signal bar's mid (no GTD).

Currently deploys:
  - macd     5 limit cells (AUD_JPY L, NZD_JPY L, CAD_CHF/EUR_CHF/NZD_USD S)
  - atr      3 limit cells (EUR_NOK L, NZD_CHF S, USD_JPY L)
  - ichimoku 1 limit cell  (USD_SGD S, tk_cross)
  - stoch    4 mid cells   (CAD_CHF S, CHF_JPY L, EUR_GBP L, USD_JPY L)
  - bb       5 mid cells   (AUD_CAD S, CAD_CHF S, CHF_JPY L, EUR_CAD L, USD_JPY L)
  - cci      5 mid cells   (CAD_CHF S, CHF_JPY L, EUR_USD S, USD_CAD L, USD_JPY L)
  - ema      4 mid cells   (CHF_JPY L, EUR_CAD L, EUR_GBP S, GBP_CAD L)
  - sma      3 mid cells   (CAD_JPY L, EUR_CAD L, EUR_GBP L)
  - rsi      3 mid cells   (CHF_JPY L, EUR_GBP L, USD_JPY L)

Only candlestick (1 cell, gate-skating per research memory) is held back.
The order-submission path is mode-agnostic — all entry modes go through
the same loop with a per-cell branch at submission.

Risk profile:
  - 0.5% of account NAV per trade (chosen 2026-05-06 after the gated-ledger
    sizing sweep; see research/v2_deploy_backtest/)
  - 1.0% stop / 1.0% target (v2 cell convention)
  - Limit order valid for one H4 bar (~4h) via GTD, mirroring the simulator's
    LIMIT_FILL_WINDOW=1.
  - Position-age cap (Phase II mixed cap): per entry-mode in
    bh_ftmo_config.json::v2_paper.max_position_age_days_by_entry_mode.
    Default {limit: 5, mid: null} closes limit-cell trades after 5 days,
    leaves mid-cell trades to TP/SL. Set both to null to disable.

Run modes:
  --dry-run   detect signals, compute orders, but DO NOT submit
  (default)   submit limit orders to OANDA practice account
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

# Reuse cell defs + evaluators from the briefing tool
from bud.briefing import (
    CELLS,
    H4_BAR_HOURS,
    STOP_PCT,
    TP_PCT,
    Cell,
    LOOKBACK_BARS,
    _price_precision,
    compute_entry_stop_target,
    evaluate_cell,
    ranked_cells,
)
from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import ohlc_mid
from bh_ftmo.trading.oanda_trader import (
    OandaTrader,
    OandaTraderConfig,
    OandaTraderError,
)
from bh_ftmo.trading.safety import (
    count_open_directions,
    direction_gate_allows,
    margin_gate_allows,
)

# Mirror auto_rising3bar helpers we want directly
from bud.auto_rising3bar import _split, latest_mid_close, quote_to_account_rate

REPO_ROOT = Path(__file__).resolve().parents[2]  # src/bud/<this> -> repo root
CONFIG_PATH = REPO_ROOT / "src" / "bh_ftmo_config.json"
JOURNAL_PATH = REPO_ROOT / "src" / "logs" / "bh_ftmo_v2_paper_journal.csv"

RISK_PER_TRADE_PCT = 0.005   # 0.5% — chosen 2026-05-06 after the gated-ledger
                              # sizing sweep. With direction + already-open gates
                              # applied (the live system's actual behavior), pass
                              # rate is 96% realistic / 80% conservative at 0.5%
                              # vs 99% / 99% at 0.25% — the safety gain is small
                              # but median time-to-pass drops 322d -> 145d.
                              # See research/v2_deploy_backtest/sweep_gated_results.json
MAX_NEW_ORDERS_PER_RUN = 5

# Which cells are in the V2 autonomous deployment universe.
# Keep this conservative — only cells with FTMO-sim conservative-model
# survival evidence go here.
DEPLOYED_STRATEGIES = frozenset({"macd", "atr", "ichimoku", "stoch", "bb", "cci",
                                  "ema", "sma", "rsi"})


def DEPLOY_PREDICATE(cell: Cell) -> bool:  # noqa: N802 (intentionally caps as a constant-fn)
    return cell.strategy in DEPLOYED_STRATEGIES


# Research-backed exit override for the validated long mean-reversion cells.
# research/exit_geometry_v1 (EXIT_SWEEP_v1.md): on the long-MR book, TP 1.5% / SL 1.0% /
# 10-day hold beats the global 1%/1%/14d v2 default on total money — the steadier total-money
# winner, profitable across all three eras (A/B + recent holdout). Scoped to ONLY the cells the
# sweep validated — long, mean-reversion (bb/rsi/ema/stoch), mid entry. Every other cell (shorts,
# trend strategies macd/atr/ichimoku/sma, limit entries) stays on the global 1%/1% convention;
# the sweep says nothing about those. Stop is unchanged (1.0%) — only the target widens to 1.5%.
LONG_MR_EXIT_STRATEGIES = frozenset({"bb", "rsi", "ema", "stoch"})
LONG_MR_TP_PCT = 0.015
LONG_MR_SL_PCT = 0.010
LONG_MR_MAX_HOLD_DAYS = 10


def _uses_long_mr_exit(strategy: str, direction: str, entry_mode: str) -> bool:
    """True for the long mean-reversion mid cells whose exits the sweep validated."""
    return (
        strategy in LONG_MR_EXIT_STRATEGIES
        and direction == "long"
        and entry_mode == "mid"
    )


LOG = logging.getLogger("bh_ftmo.v2_paper")


JOURNAL_FIELDS = [
    "ts_utc", "run_mode", "event", "strategy", "pair", "direction",
    "entry_mode", "trigger_bar_close_ts", "entry_price", "stop_price",
    "target_price", "gtd_time_utc", "units", "equity", "risk_dollars",
    "quote_to_account", "order_id", "status", "note",
]


def _archive_obsolete_journal_if_needed() -> None:
    if not JOURNAL_PATH.exists():
        return
    with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
        first_line = f.readline().strip()
    existing = first_line.split(",") if first_line else []
    if existing == JOURNAL_FIELDS:
        return
    backup = JOURNAL_PATH.with_suffix(JOURNAL_PATH.suffix + ".bak")
    counter = 1
    while backup.exists():
        backup = JOURNAL_PATH.with_suffix(f"{JOURNAL_PATH.suffix}.bak{counter}")
        counter += 1
    JOURNAL_PATH.rename(backup)
    LOG.info("archived old-schema journal to %s", backup.name)


def _append_journal_row(row: dict) -> None:
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_file = not JOURNAL_PATH.exists()
    with open(JOURNAL_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=JOURNAL_FIELDS)
        if new_file:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in JOURNAL_FIELDS})


def _pair_to_oanda(symbol: str) -> str:
    """bh_briefing uses OANDA-style USD_JPY directly; nothing to do."""
    return symbol


def _compute_units(
    risk_in_account_ccy: float,
    entry_price: float,
    quote_to_account: float,
    *,
    direction: str,
) -> int:
    """Position size in BASE currency units. Signed by direction (long > 0,
    short < 0). Stop distance is STOP_PCT of the entry price (v2 convention).
    """
    risk_in_quote = risk_in_account_ccy / quote_to_account
    stop_distance_quote = entry_price * STOP_PCT
    raw = risk_in_quote / stop_distance_quote
    units = int(round(raw))
    return units if direction == "long" else -units


_ENTRY_MODE_BY_STRATEGY = {c.strategy: c.entry_mode for c in CELLS}


def _parse_oanda_iso(iso: str) -> datetime:
    """OANDA returns RFC3339 with nanosecond precision (Python only handles us)."""
    if "." in iso:
        head, frac = iso.split(".")
        frac = frac.rstrip("Z")[:6]
        iso = f"{head}.{frac}+00:00"
    else:
        iso = iso.replace("Z", "+00:00")
    return datetime.fromisoformat(iso)


def _close_aged_positions(
    trader: OandaTrader,
    max_age_by_em: dict,
    *,
    dry_run: bool,
) -> int:
    """Close v2-tagged positions older than the per-entry-mode cap.

    Identifies our trades by the `clientExtensions.tag` we set on order creation
    (format: ``v2:<strategy>:<direction>:<bar_ts>``). Strategy → entry_mode is
    looked up from `bh_briefing.CELLS`. Caps are per entry_mode; ``None`` skips.

    Returns the number of positions closed (0 in dry-run).
    """
    # The validated long-MR cells carry an always-on LONG_MR_MAX_HOLD_DAYS cap (independent of
    # the per-entry-mode config), so we cannot short-circuit on config caps alone — always check.
    try:
        trades = trader.get_open_trades()
    except OandaTraderError as exc:
        LOG.warning("age-close: failed to fetch open trades: %s", exc)
        return 0

    now = datetime.now(UTC)
    closed = 0
    for tr in trades:
        tag = (tr.get("clientExtensions") or {}).get("tag", "")
        if not tag.startswith("v2:"):
            continue
        parts = tag.split(":")
        if len(parts) < 3:
            continue
        strategy = parts[1]
        direction = parts[2]
        entry_mode = _ENTRY_MODE_BY_STRATEGY.get(strategy)
        if entry_mode is None:
            continue
        cap_days = max_age_by_em.get(entry_mode)
        if _uses_long_mr_exit(strategy, direction, entry_mode):
            cap_days = LONG_MR_MAX_HOLD_DAYS
        if cap_days is None:
            continue
        try:
            opened = _parse_oanda_iso(tr["openTime"])
        except (KeyError, ValueError):
            continue
        age_days = (now - opened).total_seconds() / 86400
        if age_days < cap_days:
            continue

        instrument = tr.get("instrument", "?")
        units = int(tr.get("currentUnits", 0))
        side = "long" if units > 0 else "short"
        if dry_run:
            LOG.info("[DRY] age-close would fire: %s/%s age=%.1fd cap=%dd",
                     strategy, instrument, age_days, cap_days)
            _append_journal_row({
                "ts_utc": datetime.now(UTC).isoformat(),
                "run_mode": "dry-run",
                "event": "would_close_aged",
                "strategy": strategy,
                "pair": instrument,
                "direction": side,
                "entry_mode": entry_mode,
                "note": f"age={age_days:.1f}d cap={cap_days}d",
            })
            continue

        LOG.info("age-close: %s/%s age=%.1fd cap=%dd → CLOSE",
                 strategy, instrument, age_days, cap_days)
        try:
            trader.close_position(instrument, side=side)
            closed += 1
            _append_journal_row({
                "ts_utc": datetime.now(UTC).isoformat(),
                "run_mode": "live",
                "event": "closed_aged",
                "strategy": strategy,
                "pair": instrument,
                "direction": side,
                "entry_mode": entry_mode,
                "note": f"age={age_days:.1f}d cap={cap_days}d",
            })
        except OandaTraderError as exc:
            LOG.error("age-close failed for %s: %s", instrument, exc)
            _append_journal_row({
                "ts_utc": datetime.now(UTC).isoformat(),
                "run_mode": "live",
                "event": "close_aged_failed",
                "strategy": strategy,
                "pair": instrument,
                "note": str(exc)[:200],
            })
    return closed


def _next_bar_close(latest_open_ts: pd.Timestamp) -> datetime:
    """Compute the close time of the bar that's currently forming.

    FxStore stores bar OPEN time; the most-recent bar's open + 4h is the close
    of the just-closed (signal) bar. The bar currently forming opens at that
    close and itself closes 4h after, i.e. open_ts + 8h. Limit orders for v2
    cells are valid until that point (mirrors the simulator's 1-bar fill
    window).
    """
    ts = latest_open_ts.to_pydatetime() if isinstance(latest_open_ts, pd.Timestamp) else latest_open_ts
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts + timedelta(hours=2 * H4_BAR_HOURS)


def run(*, dry_run: bool) -> int:
    _archive_obsolete_journal_if_needed()

    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    account_ccy = cfg["ftmo"]["account_currency"].upper()

    deploy_cells = [c for c in ranked_cells() if DEPLOY_PREDICATE(c)]
    deploy_pairs = {c.pair for c in deploy_cells}
    LOG.info("V2 autonomous: %d deployable cells across %d pairs (deployed: %s)",
             len(deploy_cells), len(deploy_pairs), sorted(DEPLOYED_STRATEGIES))
    if not deploy_cells:
        LOG.warning("no cells match DEPLOY_PREDICATE — nothing to do")
        _append_journal_row({"ts_utc": datetime.now(UTC).isoformat(),
                             "run_mode": "dry-run" if dry_run else "live",
                             "event": "no_deployable_cells"})
        return 0

    LOG.info("loading H4 bars from FxStore for %d pairs", len(deploy_pairs))
    store = FxStore(read_only=True)
    bars_by_pair: dict[str, pd.DataFrame] = {}
    mid_by_pair: dict[str, float] = {}
    try:
        # Load the deployable pairs PLUS every pair we might need for
        # quote→account currency conversion (cheap; just reads from FxStore).
        # bh_ftmo_paper does the same trick — to convert e.g. AUD_JPY to USD,
        # we need pairs like USD_JPY in the graph.
        all_pairs_for_conversion = set(deploy_pairs)
        # Load all pairs from config to ensure conversion graph completeness.
        for inst in cfg.get("instruments", []):
            ftmo = str(inst.get("ftmo", "")).replace(".sim", "").upper()
            if len(ftmo) == 6 and ftmo.isalpha():
                all_pairs_for_conversion.add(f"{ftmo[:3]}_{ftmo[3:]}")

        for pair in all_pairs_for_conversion:
            df = store.load(pair, granularity="H4", include_incomplete=False)
            if df is None or df.empty or len(df) < 60:
                if pair in deploy_pairs:
                    LOG.warning("skipping %s: insufficient bars", pair)
                continue
            df = df.tail(LOOKBACK_BARS).reset_index(drop=True)
            bars_by_pair[pair] = df
            mid_by_pair[pair] = latest_mid_close(df)
    finally:
        store.close()

    # Connect to OANDA practice account
    try:
        trader_config = OandaTraderConfig.from_env()
    except OandaTraderError as exc:
        LOG.error("OandaTrader config error: %s", exc)
        return 2

    with OandaTrader(trader_config) as trader:
        try:
            account = trader.get_account_summary()
        except OandaTraderError as exc:
            LOG.error("Failed to fetch account summary: %s", exc)
            return 1

        equity = float(account.get("NAV", account.get("balance", 0.0)))
        currency = account.get("currency", account_ccy)
        if currency.upper() != account_ccy:
            LOG.warning("account currency %r differs from config %r — using account's",
                        currency, account_ccy)
            account_ccy = currency.upper()
        LOG.info("account %s NAV=%s %s", account.get("id"), equity, account_ccy)
        if equity <= 0:
            LOG.error("account equity <= 0; aborting")
            return 1

        risk_dollars = equity * RISK_PER_TRADE_PCT
        LOG.info("risk per trade: %.2f %s (%.2f%% of NAV)",
                 risk_dollars, account_ccy, RISK_PER_TRADE_PCT * 100)

        margin_ok, margin_reason = margin_gate_allows(account)
        LOG.info("margin gate: %s", margin_reason)
        if not margin_ok:
            _append_journal_row({
                "ts_utc": datetime.now(UTC).isoformat(),
                "run_mode": "dry-run" if dry_run else "live",
                "event": "skip_margin_util",
                "equity": f"{equity:.2f}",
                "note": margin_reason,
            })
            return 0

        max_age_by_em = (cfg.get("v2_paper", {})
                         .get("max_position_age_days_by_entry_mode", {}))
        # Always run: the validated long-MR cells carry an always-on 10-day cap regardless of
        # the per-entry-mode config, so the age-close pass cannot be gated on config caps alone.
        n_aged = _close_aged_positions(trader, max_age_by_em, dry_run=dry_run)
        if n_aged:
            LOG.info("age-close: closed %d aged position(s)", n_aged)

        try:
            open_positions = trader.get_open_positions()
        except OandaTraderError as exc:
            LOG.error("Failed to fetch open positions: %s", exc)
            return 1
        open_pair_set = {p.get("instrument") for p in open_positions if p.get("instrument")}
        n_long, n_short = count_open_directions(open_positions)
        LOG.info("currently open positions: %d (n_long=%d n_short=%d) %s",
                 len(open_pair_set), n_long, n_short, sorted(open_pair_set))

        # Evaluate each deployable cell on the most-recently-closed H4 bar
        fires: list[dict] = []
        for cell in deploy_cells:
            df = bars_by_pair.get(cell.pair)
            if df is None:
                LOG.info("%s/%s: no bars — skip", cell.strategy, cell.pair)
                continue
            mid = ohlc_mid(df)
            if not evaluate_cell(cell, mid):
                continue
            if _uses_long_mr_exit(cell.strategy, cell.direction, cell.entry_mode):
                entry, stop, target = compute_entry_stop_target(
                    cell, mid, tp_pct=LONG_MR_TP_PCT, sl_pct=LONG_MR_SL_PCT,
                )
            else:
                entry, stop, target = compute_entry_stop_target(cell, mid)
            signal_open_ts = pd.Timestamp(df["timestamp"].iloc[-1])
            signal_close_ts = signal_open_ts + pd.Timedelta(hours=H4_BAR_HOURS)
            gtd = _next_bar_close(signal_open_ts)
            fires.append({
                "cell": cell, "df": df,
                "signal_close_ts": signal_close_ts,
                "entry": entry, "stop": stop, "target": target,
                "gtd": gtd,
            })

        LOG.info("fires on most-recent bar: %d", len(fires))
        if not fires:
            _append_journal_row({"ts_utc": datetime.now(UTC).isoformat(),
                                 "run_mode": "dry-run" if dry_run else "live",
                                 "event": "no_fires",
                                 "equity": f"{equity:.2f}",
                                 "risk_dollars": f"{risk_dollars:.2f}"})
            return 0

        n_placed = 0
        for f in fires:
            cell: Cell = f["cell"]
            pair = cell.pair
            entry = f["entry"]
            stop = f["stop"]
            target = f["target"]
            gtd = f["gtd"]
            signal_close_ts = f["signal_close_ts"]
            precision = _price_precision(pair)

            base_fields = {
                "ts_utc": datetime.now(UTC).isoformat(),
                "run_mode": "dry-run" if dry_run else "live",
                "strategy": cell.strategy,
                "pair": pair,
                "direction": cell.direction,
                "entry_mode": cell.entry_mode,
                "trigger_bar_close_ts": signal_close_ts.isoformat(),
                "entry_price": f"{entry:.{precision}f}",
                "stop_price": f"{stop:.{precision}f}",
                "target_price": f"{target:.{precision}f}",
                "gtd_time_utc": gtd.isoformat() if cell.entry_mode == "limit" else "",
                "equity": f"{equity:.2f}",
            }

            if pair in open_pair_set:
                LOG.info("%s/%s: position already open — skip", cell.strategy, pair)
                _append_journal_row({**base_fields, "event": "skip_already_open"})
                continue

            dir_ok, dir_reason = direction_gate_allows(cell.direction, n_long, n_short)
            if not dir_ok:
                LOG.info("%s/%s: direction gate skip — %s",
                         cell.strategy, pair, dir_reason)
                _append_journal_row({
                    **base_fields,
                    "event": "skip_direction_imbalance",
                    "note": dir_reason,
                })
                continue

            qta = quote_to_account_rate(pair, account_ccy, mid_by_pair)
            if qta is None or qta <= 0:
                LOG.warning("%s/%s: no quote→account conversion path — skip",
                            cell.strategy, pair)
                _append_journal_row({
                    **base_fields,
                    "event": "skip_no_conversion",
                    "note": f"no path {pair.split('_')[1]} -> {account_ccy}",
                })
                continue

            units = _compute_units(risk_dollars, entry, qta, direction=cell.direction)
            if units == 0:
                LOG.warning("%s/%s: computed 0 units — skip", cell.strategy, pair)
                _append_journal_row({**base_fields, "event": "skip_zero_units"})
                continue

            order_fields = {
                **base_fields,
                "units": str(units),
                "risk_dollars": f"{risk_dollars:.2f}",
                "quote_to_account": f"{qta:.6f}",
            }

            if dry_run:
                if cell.entry_mode == "limit":
                    LOG.info(
                        "[DRY] %s/%s %s LIMIT: entry=%.5f stop=%.5f target=%.5f units=%d gtd=%s",
                        cell.strategy, pair, cell.direction.upper(),
                        entry, stop, target, units, gtd.isoformat(),
                    )
                else:
                    LOG.info(
                        "[DRY] %s/%s %s MARKET: entry=%.5f stop=%.5f target=%.5f units=%d",
                        cell.strategy, pair, cell.direction.upper(),
                        entry, stop, target, units,
                    )
                _append_journal_row({**order_fields,
                                     "event": "would_open",
                                     "status": "dry_run"})
                continue

            if n_placed >= MAX_NEW_ORDERS_PER_RUN:
                LOG.warning("%s/%s: MAX_NEW_ORDERS_PER_RUN cap — skip", cell.strategy, pair)
                _append_journal_row({**base_fields, "event": "skip_cap"})
                continue

            client_tag = (f"v2:{cell.strategy}:{cell.direction}:"
                          f"{signal_close_ts.strftime('%Y%m%d%H%M')}")
            LOG.info("submitting %s %s/%s %s units=%d entry=%.5f stop=%.5f target=%.5f",
                     cell.entry_mode.upper(),
                     cell.strategy, pair, cell.direction.upper(),
                     units, entry, stop, target)
            try:
                if cell.entry_mode == "limit":
                    resp = trader.create_limit_order_with_bracket(
                        instrument=pair,
                        units=units,
                        limit_price=entry,
                        stop_loss_price=stop,
                        take_profit_price=target,
                        gtd_time=gtd,
                        price_precision=precision,
                        client_tag=client_tag,
                    )
                else:
                    resp = trader.create_market_order_with_bracket(
                        instrument=pair,
                        units=units,
                        stop_loss_price=stop,
                        take_profit_price=target,
                        price_precision=precision,
                        client_tag=client_tag,
                    )
            except OandaTraderError as exc:
                exc_msg = str(exc)
                if "MARKET_HALTED" in exc_msg:
                    LOG.info("%s/%s: market halted; skipping order: %s", cell.strategy, pair, exc)
                    event = "skip_market_halted"
                else:
                    LOG.error("%s/%s: order submission failed: %s", cell.strategy, pair, exc)
                    event = "order_failed"
                _append_journal_row({
                    **order_fields,
                    "event": event,
                    "status": "failed",
                    "note": exc_msg[:200],
                })
                continue

            order_id = (
                resp.get("orderCreateTransaction", {}).get("id")
                or resp.get("orderFillTransaction", {}).get("orderID", "")
            )
            n_placed += 1
            if cell.direction == "long":
                n_long += 1
            else:
                n_short += 1
            _append_journal_row({
                **order_fields,
                "event": "order_placed",
                "order_id": str(order_id),
                "status": "submitted",
            })

        LOG.info("done: placed %d new order(s) (mode=%s)",
                 n_placed, "dry" if dry_run else "live")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="BH FTMO V2 autonomous trader")
    parser.add_argument("--dry-run", action="store_true",
                        help="Detect + log signals but do not submit orders")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
