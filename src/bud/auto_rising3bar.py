"""DEPRECATED: use src/bud/auto_trader.py for live cron deployment.

BH FTMO paper trader — rising_3bar @ 1.5%/1.5% on the OANDA practice account.

Runs as a cron-driven script every 4 hours, just after the H4 data update:
  1. Pull account equity from OANDA (demo account).
  2. For each of 40 configured pairs, load latest H4 bars from FxStore.
  3. Compute rising_3bar trigger; check if it fired on the *just-closed* bar.
  4. Skip pairs that already have a position open (one-trade-per-pair policy).
  5. For each fresh signal, size the position at 1% of equity / 1.5% stop and
     submit a market order with attached stop-loss + take-profit via OANDA.
  6. Log every signal, every order, every error to a CSV journal.

This is the deployment shape we validated:
  - Trigger: rising_3bar_from_oversold (K rising 3 bars from below 20)
  - RR: 1.5% stop, 1.5% target
  - Universe: all 40 OANDA H4 pairs
  - Risk: 1% of demo account equity per trade

Run modes:
  --dry-run   detect signals, compute orders, but DO NOT submit
  (default)   submit orders to OANDA practice account
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import ohlc_mid, rsi, stochastic
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

REPO_ROOT = Path(__file__).resolve().parents[2]  # src/bud/<this> -> repo root
CONFIG_PATH = REPO_ROOT / "src" / "bh_ftmo_config.json"
JOURNAL_PATH = REPO_ROOT / "src" / "logs" / "bh_ftmo_paper_journal.csv"

# Strategy parameters — match the validated research configuration
STOP_PCT = 0.015
TARGET_PCT = 0.015
RISK_PER_TRADE_PCT = 0.01
LOOKBACK_BARS = 200  # plenty for stoch warmup + 3-bar history
MAX_NEW_ORDERS_PER_RUN = 5  # safety cap; real-life rarely hits this

# Amplifier: when RSI(14) at trigger bar is below this threshold, the trade is
# tagged as a high-conviction confirmation and sized up by the multiplier.
# Per held-out validation, RSI<30 trades show ~+0.029 R lift over RSI>=30
# trades on rising_3bar fires. Borderline statistical confidence (P=81%) so
# the multiplier is modest — captures lift if real, costs little if illusory.
RSI_OVERSOLD_THRESHOLD = 30.0
RSI_AMPLIFIER_RISK_MULTIPLIER = 1.5

LOG = logging.getLogger("bh_ftmo.paper")


@dataclass(frozen=True)
class PairSpec:
    symbol: str          # canonical "EUR_USD"
    pip_size: float      # e.g., 0.0001 for majors, 0.01 for JPY/HUF/...
    price_precision: int # decimals for stop/target price formatting


def load_pair_specs() -> list[PairSpec]:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    specs: list[PairSpec] = []
    for inst in cfg.get("instruments", []):
        # The bar store is keyed by the OANDA instrument name. When the config
        # carries an explicit `oanda` field (metals/energy/softs), use it
        # verbatim: the FX-style split below mangles names like NATGAS -> NAT_GAS
        # and silently drops non-6-char tickers (USOIL, CORN.c, XPT/USD).
        oanda = inst.get("oanda")
        if oanda:
            symbol = str(oanda)
        else:
            ftmo = str(inst.get("ftmo", "")).replace(".sim", "").upper()
            if len(ftmo) == 6 and ftmo.isalpha():
                symbol = f"{ftmo[:3]}_{ftmo[3:]}"
            else:
                continue
        pip_size = float(inst["pip_size"])
        # 0.0001 → 5 decimals (4-decimal pip + 1); 0.01 → 3 decimals
        if pip_size <= 0.0001:
            precision = 5
        elif pip_size <= 0.001:
            precision = 4
        elif pip_size <= 0.01:
            precision = 3
        else:
            precision = 2
        specs.append(PairSpec(symbol=symbol, pip_size=pip_size, price_precision=precision))
    return specs


def evaluate_trigger_on_last_bar(bars: pd.DataFrame) -> tuple[bool, float]:
    """Return (rising_3bar_fired, rsi_at_last_bar) for the most-recently-closed bar.

    rsi_at_last_bar is returned regardless of whether the trigger fires — it's
    used for journal logging and for the tiered-sizing decision.
    """
    k = stochastic(bars, k_period=14)["k"]
    rsi_series = rsi(bars, period=14)
    if k.iloc[-3:].isna().any() or pd.isna(rsi_series.iloc[-1]):
        return False, float("nan")
    rising = (k.iloc[-1] > k.iloc[-2]) and (k.iloc[-2] > k.iloc[-3])
    started_oversold = k.iloc[-3] < 20.0
    fired = bool(rising and started_oversold)
    return fired, float(rsi_series.iloc[-1])


def latest_mid_close(bars: pd.DataFrame) -> float:
    return float((bars["close_bid"].iloc[-1] + bars["close_ask"].iloc[-1]) / 2.0)


def _split(symbol: str) -> tuple[str, str]:
    base, quote = symbol.split("_", 1)
    return base, quote


def quote_to_account_rate(
    pair: str,
    account_ccy: str,
    mid_by_pair: dict[str, float],
) -> Optional[float]:
    """Walk a small currency graph to convert one unit of the pair's QUOTE
    currency into account_ccy. Returns None if no path is found.
    """
    _, quote = _split(pair)
    if quote == account_ccy:
        return 1.0

    # Build neighbour graph from mid prices: BASE→QUOTE = rate; QUOTE→BASE = 1/rate
    graph: dict[str, list[tuple[str, float]]] = {}
    for sym, rate in mid_by_pair.items():
        if rate <= 0:
            continue
        b, q = _split(sym)
        graph.setdefault(b, []).append((q, rate))
        graph.setdefault(q, []).append((b, 1.0 / rate))

    # BFS from quote to account
    from collections import deque
    queue: deque[tuple[str, float]] = deque([(quote, 1.0)])
    visited = {quote}
    while queue:
        cur, path_rate = queue.popleft()
        if cur == account_ccy:
            return path_rate
        for nbr, edge in graph.get(cur, []):
            if nbr in visited:
                continue
            visited.add(nbr)
            queue.append((nbr, path_rate * edge))
    return None


def compute_units(
    risk_in_account_ccy: float,
    entry_mid: float,
    quote_to_account: float,
) -> int:
    """Position size in BASE currency units (what OANDA's `units` field expects)."""
    risk_in_quote = risk_in_account_ccy / quote_to_account
    stop_distance_quote = entry_mid * STOP_PCT
    units = risk_in_quote / stop_distance_quote
    return int(round(units))


def compute_stop_target(entry: float, direction: int = +1) -> tuple[float, float]:
    if direction > 0:
        return entry * (1 - STOP_PCT), entry * (1 + TARGET_PCT)
    return entry * (1 + STOP_PCT), entry * (1 - TARGET_PCT)


JOURNAL_FIELDS = [
    "ts_utc", "run_mode", "event", "pair", "trigger_bar_ts",
    "entry_mid", "stop_price", "target_price", "units",
    "equity", "risk_dollars", "quote_to_account",
    "rsi_at_entry", "rsi_oversold", "risk_multiplier",
    "order_id", "status", "note",
]


def _archive_obsolete_journal_if_needed() -> None:
    """If the journal exists with an older header, rename to .bak so the new
    schema can write a fresh file. Run once per process, before any append.
    """
    if not JOURNAL_PATH.exists():
        return
    with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
        first_line = f.readline().strip()
    existing_fields = first_line.split(",") if first_line else []
    if existing_fields == JOURNAL_FIELDS:
        return
    backup = JOURNAL_PATH.with_suffix(JOURNAL_PATH.suffix + ".bak")
    counter = 1
    while backup.exists():
        backup = JOURNAL_PATH.with_suffix(f"{JOURNAL_PATH.suffix}.bak{counter}")
        counter += 1
    JOURNAL_PATH.rename(backup)
    LOG.info("archived old-schema journal to %s; starting fresh", backup.name)


def append_journal_row(row: dict) -> None:
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_file = not JOURNAL_PATH.exists()
    with open(JOURNAL_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=JOURNAL_FIELDS)
        if new_file:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in JOURNAL_FIELDS})


def run(*, dry_run: bool) -> int:
    _archive_obsolete_journal_if_needed()
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    account_ccy = cfg["ftmo"]["account_currency"].upper()
    pair_specs = load_pair_specs()

    LOG.info("loading H4 bars from FxStore for %d pairs", len(pair_specs))
    store = FxStore(read_only=True)
    bars_by_pair: dict[str, pd.DataFrame] = {}
    mid_by_pair: dict[str, float] = {}
    try:
        for spec in pair_specs:
            df = store.load(spec.symbol, granularity="H4", include_incomplete=False)
            if df is None or df.empty or len(df) < 50:
                LOG.warning("skipping %s: insufficient bars (%d)", spec.symbol, 0 if df is None else len(df))
                continue
            df = df.tail(LOOKBACK_BARS).reset_index(drop=True)
            bars_by_pair[spec.symbol] = df
            mid_by_pair[spec.symbol] = latest_mid_close(df)
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
            LOG.warning("account currency %r differs from config %r — using account's", currency, account_ccy)
            account_ccy = currency.upper()
        LOG.info("account %s NAV=%s %s", account.get("id"), equity, account_ccy)
        if equity <= 0:
            LOG.error("account equity <= 0; aborting")
            return 1

        risk_dollars = equity * RISK_PER_TRADE_PCT
        LOG.info("risk per trade: %.2f %s (%.2f%% of NAV)", risk_dollars, account_ccy, RISK_PER_TRADE_PCT * 100)

        margin_ok, margin_reason = margin_gate_allows(account)
        LOG.info("margin gate: %s", margin_reason)
        if not margin_ok:
            append_journal_row({
                "ts_utc": datetime.now(UTC).isoformat(),
                "run_mode": "dry-run" if dry_run else "live",
                "event": "skip_margin_util",
                "equity": f"{equity:.2f}",
                "risk_dollars": f"{risk_dollars:.2f}",
                "risk_multiplier": "1.00",
                "note": margin_reason,
            })
            return 0

        # Fetch already-open positions to avoid duplicates
        try:
            open_positions = trader.get_open_positions()
        except OandaTraderError as exc:
            LOG.error("Failed to fetch open positions: %s", exc)
            return 1
        open_pair_set = {p.get("instrument") for p in open_positions if p.get("instrument")}
        n_long, n_short = count_open_directions(open_positions)
        LOG.info("currently open positions: %d (n_long=%d n_short=%d) %s",
                 len(open_pair_set), n_long, n_short, sorted(open_pair_set))

        # Detect signals (rising_3bar) and capture RSI at trigger time
        signals: list[tuple[PairSpec, pd.DataFrame, float]] = []
        for spec in pair_specs:
            df = bars_by_pair.get(spec.symbol)
            if df is None:
                continue
            mid = ohlc_mid(df).copy()
            mid["timestamp"] = df["timestamp"].values
            fired, rsi_at_trigger = evaluate_trigger_on_last_bar(mid)
            if fired:
                signals.append((spec, df, rsi_at_trigger))

        LOG.info("signals fired on most-recent bar: %d", len(signals))
        if not signals:
            append_journal_row({
                "ts_utc": datetime.now(UTC).isoformat(),
                "run_mode": "dry-run" if dry_run else "live",
                "event": "no_signals",
                "equity": f"{equity:.2f}",
                "risk_dollars": f"{risk_dollars:.2f}",
                "risk_multiplier": "1.00",
            })
            return 0

        # For each signal, decide whether to place an order
        n_placed = 0
        for spec, df, rsi_at_trigger in signals:
            pair = spec.symbol
            entry = mid_by_pair[pair]
            trigger_bar_ts = pd.Timestamp(df["timestamp"].iloc[-1])

            # Tiered sizing: RSI<30 confirmation gets 1.5× risk
            rsi_oversold = (
                not pd.isna(rsi_at_trigger) and rsi_at_trigger < RSI_OVERSOLD_THRESHOLD
            )
            risk_multiplier = RSI_AMPLIFIER_RISK_MULTIPLIER if rsi_oversold else 1.0
            trade_risk_dollars = risk_dollars * risk_multiplier

            # Common journal fields per signal
            base_fields = {
                "ts_utc": datetime.now(UTC).isoformat(),
                "run_mode": "dry-run" if dry_run else "live",
                "pair": pair,
                "trigger_bar_ts": trigger_bar_ts.isoformat(),
                "entry_mid": f"{entry:.{spec.price_precision}f}",
                "equity": f"{equity:.2f}",
                "rsi_at_entry": f"{rsi_at_trigger:.2f}" if not pd.isna(rsi_at_trigger) else "",
                "rsi_oversold": "1" if rsi_oversold else "0",
                "risk_multiplier": f"{risk_multiplier:.2f}",
            }

            if pair in open_pair_set:
                LOG.info("%s: signal fired but position already open — skipping", pair)
                append_journal_row({**base_fields, "event": "skip_already_open"})
                continue

            dir_ok, dir_reason = direction_gate_allows("long", n_long, n_short)
            if not dir_ok:
                LOG.info("%s: direction gate skip — %s", pair, dir_reason)
                append_journal_row({
                    **base_fields,
                    "event": "skip_direction_imbalance",
                    "note": dir_reason,
                })
                continue

            qta = quote_to_account_rate(pair, account_ccy, mid_by_pair)
            if qta is None or qta <= 0:
                LOG.warning("%s: no quote→account conversion path; skipping", pair)
                append_journal_row({
                    **base_fields,
                    "event": "skip_no_conversion",
                    "note": f"no path {pair.split('_')[1]} -> {account_ccy}",
                })
                continue

            units = compute_units(trade_risk_dollars, entry, qta)
            if units == 0:
                LOG.warning("%s: computed 0 units; skipping", pair)
                continue
            stop_price, target_price = compute_stop_target(entry, +1)

            order_fields = {
                **base_fields,
                "stop_price": f"{stop_price:.{spec.price_precision}f}",
                "target_price": f"{target_price:.{spec.price_precision}f}",
                "units": str(units),
                "risk_dollars": f"{trade_risk_dollars:.2f}",
                "quote_to_account": f"{qta:.6f}",
            }

            conviction = "HIGH(RSI<30)" if rsi_oversold else "STD"
            if dry_run:
                LOG.info(
                    "[DRY] %s [%s]: entry=%.5f stop=%.5f target=%.5f units=%d "
                    "rsi=%.1f risk=$%.2f (×%.2f)",
                    pair, conviction, entry, stop_price, target_price, units,
                    rsi_at_trigger, trade_risk_dollars, risk_multiplier,
                )
                append_journal_row({**order_fields, "event": "would_open", "status": "dry_run"})
                continue

            if n_placed >= MAX_NEW_ORDERS_PER_RUN:
                LOG.warning("%s: hit MAX_NEW_ORDERS_PER_RUN cap; skipping", pair)
                append_journal_row({**base_fields, "event": "skip_cap"})
                continue

            LOG.info(
                "submitting market order: %s [%s] units=%d entry≈%.5f stop=%.5f target=%.5f rsi=%.1f",
                pair, conviction, units, entry, stop_price, target_price, rsi_at_trigger,
            )
            try:
                resp = trader.create_market_order_with_bracket(
                    instrument=pair,
                    units=units,
                    stop_loss_price=stop_price,
                    take_profit_price=target_price,
                    price_precision=spec.price_precision,
                    client_tag=f"rising3bar:{trigger_bar_ts.strftime('%Y%m%d%H%M')}",
                )
            except OandaTraderError as exc:
                exc_msg = str(exc)
                if "MARKET_HALTED" in exc_msg:
                    LOG.info("%s: market halted; skipping order: %s", pair, exc)
                    event = "skip_market_halted"
                else:
                    LOG.error("%s: order submission failed: %s", pair, exc)
                    event = "order_failed"
                append_journal_row({
                    **order_fields,
                    "event": event,
                    "status": "failed",
                    "note": exc_msg[:200],
                })
                continue

            order_id = (
                resp.get("orderFillTransaction", {}).get("orderID")
                or resp.get("orderCreateTransaction", {}).get("id", "")
            )
            n_placed += 1
            n_long += 1
            append_journal_row({
                **order_fields,
                "event": "order_placed",
                "order_id": str(order_id),
                "status": "submitted",
            })

        LOG.info("done: placed %d new order(s) (mode=%s)", n_placed, "dry" if dry_run else "live")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="BH FTMO rising_3bar paper trader")
    parser.add_argument("--dry-run", action="store_true", help="Detect + log signals but do not submit orders")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
