"""Unified BH FTMO autonomous trader for rising_3bar and v2 cells.

Replaces the separately-cronned ``bh_ftmo_paper.py`` and
``bh_ftmo_v2_paper.py`` while preserving each family's signal, risk, and RR.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional, Protocol

import pandas as pd

from bud.briefing import (
    CELLS,
    H4_BAR_HOURS,
    LOOKBACK_BARS as V2_LOOKBACK_BARS,
    Cell,
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
    MAX_MARGIN_UTILIZATION,
    count_open_directions,
    direction_gate_allows,
    estimate_order_margin,
    margin_headroom,
)
from bud.auto_rising3bar import (
    LOOKBACK_BARS as R3B_LOOKBACK_BARS,
    RISK_PER_TRADE_PCT as R3B_RISK_PER_TRADE_PCT,
    RSI_AMPLIFIER_RISK_MULTIPLIER,
    RSI_OVERSOLD_THRESHOLD,
    STOP_PCT as R3B_STOP_PCT,
    TARGET_PCT as R3B_TARGET_PCT,
    PairSpec,
    evaluate_trigger_on_last_bar,
    latest_mid_close,
    load_pair_specs,
    quote_to_account_rate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]  # src/bud/<this> -> repo root
CONFIG_PATH = REPO_ROOT / "src" / "bh_ftmo_config.json"
JOURNAL_PATH = REPO_ROOT / "src" / "logs" / "bh_ftmo_trader_journal.csv"

R3B_SOURCE = "rising_3bar"
V2_SOURCE = "v2"
V2_RISK_PER_TRADE_PCT = 0.005
MAX_NEW_ORDERS_PER_RUN = 5

DEPLOYED_STRATEGIES = frozenset({
    "macd", "atr", "ichimoku", "stoch", "bb", "cci", "ema", "sma", "rsi",
})

LOG = logging.getLogger("bh_ftmo.trader")


@dataclass(frozen=True)
class OrderCandidate:
    source: str
    pair: str
    direction: str
    entry_mode: str
    entry: float
    stop: float
    target: float
    risk_pct: float
    client_tag: str
    price_precision: int
    gtd: datetime | None
    meta: dict


class SignalSource(Protocol):
    name: str

    def candidates(
        self,
        *,
        bars_by_pair: dict[str, pd.DataFrame],
        mid_by_pair: dict[str, float],
        account_ccy: str,
        equity: float,
    ) -> list[OrderCandidate]:
        ...


def deploy_predicate(cell: Cell) -> bool:
    return cell.strategy in DEPLOYED_STRATEGIES


def compute_units(
    *,
    risk_in_account_ccy: float,
    entry_price: float,
    stop_price: float,
    quote_to_account: float,
    direction: str,
) -> int:
    risk_in_quote = risk_in_account_ccy / quote_to_account
    stop_distance_quote = abs(entry_price - stop_price)
    if stop_distance_quote <= 0:
        return 0
    raw = risk_in_quote / stop_distance_quote
    units = int(round(raw))
    return units if direction == "long" else -units


def _next_bar_close(latest_open_ts: pd.Timestamp | datetime) -> datetime:
    ts = latest_open_ts.to_pydatetime() if isinstance(latest_open_ts, pd.Timestamp) else latest_open_ts
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts + timedelta(hours=2 * H4_BAR_HOURS)


class Rising3BarSource:
    name = R3B_SOURCE

    def __init__(self, pair_specs: list[PairSpec]) -> None:
        self._pair_specs = pair_specs

    def candidates(
        self,
        *,
        bars_by_pair: dict[str, pd.DataFrame],
        mid_by_pair: dict[str, float],
        account_ccy: str,
        equity: float,
    ) -> list[OrderCandidate]:
        del account_ccy, equity
        out: list[OrderCandidate] = []
        for spec in self._pair_specs:
            df = bars_by_pair.get(spec.symbol)
            if df is None:
                continue
            mid = ohlc_mid(df).copy()
            mid["timestamp"] = df["timestamp"].values
            fired, rsi_at_trigger = evaluate_trigger_on_last_bar(mid)
            if not fired:
                continue
            entry = mid_by_pair[spec.symbol]
            rsi_oversold = (
                not pd.isna(rsi_at_trigger)
                and rsi_at_trigger < RSI_OVERSOLD_THRESHOLD
            )
            risk_multiplier = RSI_AMPLIFIER_RISK_MULTIPLIER if rsi_oversold else 1.0
            trigger_bar_ts = pd.Timestamp(df["timestamp"].iloc[-1])
            stop = entry * (1 - R3B_STOP_PCT)
            target = entry * (1 + R3B_TARGET_PCT)
            out.append(OrderCandidate(
                source=self.name,
                pair=spec.symbol,
                direction="long",
                entry_mode="market",
                entry=entry,
                stop=stop,
                target=target,
                risk_pct=R3B_RISK_PER_TRADE_PCT * risk_multiplier,
                client_tag=f"rising3bar:{trigger_bar_ts.strftime('%Y%m%d%H%M')}",
                price_precision=spec.price_precision,
                gtd=None,
                meta={
                    "trigger_bar_ts": trigger_bar_ts.isoformat(),
                    "trigger_bar_close_ts": "",
                    "rsi_at_entry": rsi_at_trigger,
                    "rsi_oversold": rsi_oversold,
                    "risk_multiplier": risk_multiplier,
                },
            ))
        return out


class V2CellSource:
    name = V2_SOURCE

    def __init__(self, cells: list[Cell] | None = None) -> None:
        self._cells = [c for c in ranked_cells(cells) if deploy_predicate(c)]

    @property
    def deploy_pairs(self) -> set[str]:
        return {c.pair for c in self._cells}

    def candidates(
        self,
        *,
        bars_by_pair: dict[str, pd.DataFrame],
        mid_by_pair: dict[str, float],
        account_ccy: str,
        equity: float,
    ) -> list[OrderCandidate]:
        del mid_by_pair, account_ccy, equity
        out: list[OrderCandidate] = []
        for cell in self._cells:
            df = bars_by_pair.get(cell.pair)
            if df is None:
                continue
            mid = ohlc_mid(df)
            if not evaluate_cell(cell, mid):
                continue
            entry, stop, target = compute_entry_stop_target(cell, mid)
            signal_open_ts = pd.Timestamp(df["timestamp"].iloc[-1])
            signal_close_ts = signal_open_ts + pd.Timedelta(hours=H4_BAR_HOURS)
            gtd = _next_bar_close(signal_open_ts)
            out.append(OrderCandidate(
                source=self.name,
                pair=cell.pair,
                direction=cell.direction,
                entry_mode=cell.entry_mode,
                entry=entry,
                stop=stop,
                target=target,
                risk_pct=V2_RISK_PER_TRADE_PCT,
                client_tag=(f"v2:{cell.strategy}:{cell.direction}:"
                            f"{signal_close_ts.strftime('%Y%m%d%H%M')}"),
                price_precision=_price_precision(cell.pair),
                gtd=gtd if cell.entry_mode == "limit" else None,
                meta={
                    "strategy": cell.strategy,
                    "trigger_bar_ts": "",
                    "trigger_bar_close_ts": signal_close_ts.isoformat(),
                },
            ))
        return out


JOURNAL_FIELDS = [
    "ts_utc", "run_mode", "event", "source", "strategy", "pair", "direction",
    "entry_mode", "trigger_bar_ts", "trigger_bar_close_ts", "entry_price",
    "entry_mid", "stop_price", "target_price", "gtd_time_utc", "units",
    "equity", "risk_dollars", "quote_to_account", "est_margin", "headroom",
    "rsi_at_entry", "rsi_oversold", "risk_multiplier", "order_id", "status",
    "note",
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
    LOG.info("archived old-schema journal to %s; starting fresh", backup.name)


def append_journal_row(row: dict) -> None:
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_file = not JOURNAL_PATH.exists()
    with open(JOURNAL_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=JOURNAL_FIELDS)
        if new_file:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in JOURNAL_FIELDS})


def _base_fields(candidate: OrderCandidate, *, dry_run: bool, equity: float) -> dict:
    rsi = candidate.meta.get("rsi_at_entry", "")
    if isinstance(rsi, float) and pd.isna(rsi):
        rsi = ""
    elif rsi != "":
        rsi = f"{float(rsi):.2f}"
    return {
        "ts_utc": datetime.now(UTC).isoformat(),
        "run_mode": "dry-run" if dry_run else "live",
        "source": candidate.source,
        "strategy": candidate.meta.get("strategy", ""),
        "pair": candidate.pair,
        "direction": candidate.direction,
        "entry_mode": candidate.entry_mode,
        "trigger_bar_ts": candidate.meta.get("trigger_bar_ts", ""),
        "trigger_bar_close_ts": candidate.meta.get("trigger_bar_close_ts", ""),
        "entry_price": f"{candidate.entry:.{candidate.price_precision}f}",
        "entry_mid": f"{candidate.entry:.{candidate.price_precision}f}",
        "stop_price": f"{candidate.stop:.{candidate.price_precision}f}",
        "target_price": f"{candidate.target:.{candidate.price_precision}f}",
        "gtd_time_utc": candidate.gtd.isoformat() if candidate.gtd else "",
        "equity": f"{equity:.2f}",
        "rsi_at_entry": rsi,
        "rsi_oversold": "1" if candidate.meta.get("rsi_oversold") else "",
        "risk_multiplier": (
            f"{float(candidate.meta['risk_multiplier']):.2f}"
            if "risk_multiplier" in candidate.meta else ""
        ),
    }


def _order_id(resp: dict) -> str:
    return str(
        resp.get("orderCreateTransaction", {}).get("id")
        or resp.get("orderFillTransaction", {}).get("orderID", "")
    )


def _dedupe_candidates(
    candidates: list[OrderCandidate],
    open_pair_set: set[str],
    *,
    dry_run: bool,
    equity: float,
    journal=append_journal_row,
) -> list[OrderCandidate]:
    by_pair: dict[str, list[OrderCandidate]] = {}
    for candidate in candidates:
        by_pair.setdefault(candidate.pair, []).append(candidate)

    out: list[OrderCandidate] = []
    for pair_candidates in by_pair.values():
        has_v2 = any(c.source == V2_SOURCE for c in pair_candidates)
        if len(pair_candidates) > 1 and has_v2 and pair_candidates[0].pair not in open_pair_set:
            kept = next(c for c in pair_candidates if c.source == V2_SOURCE)
            for dropped in pair_candidates:
                if dropped is kept:
                    continue
                journal({**_base_fields(dropped, dry_run=dry_run, equity=equity),
                         "event": "skip_conflict",
                         "note": "v2 candidate wins same-pair conflict"})
            out.append(kept)
        else:
            out.extend(pair_candidates)
    return out


def place_candidates(
    *,
    trader: OandaTrader,
    candidates: list[OrderCandidate],
    account_summary: dict,
    open_positions: list[dict],
    mid_by_pair: dict[str, float],
    account_ccy: str,
    equity: float,
    dry_run: bool,
    journal=append_journal_row,
) -> int:
    open_pair_set = {p.get("instrument") for p in open_positions if p.get("instrument")}
    n_long, n_short = count_open_directions(open_positions)
    headroom = margin_headroom(account_summary, MAX_MARGIN_UTILIZATION)
    margin_rate = float(account_summary.get("marginRate", 0.02))
    n_placed = 0

    candidates = _dedupe_candidates(
        candidates, open_pair_set, dry_run=dry_run, equity=equity, journal=journal,
    )

    for candidate in candidates:
        base = _base_fields(candidate, dry_run=dry_run, equity=equity)
        if candidate.pair in open_pair_set:
            journal({**base, "event": "skip_already_open"})
            continue

        dir_ok, dir_reason = direction_gate_allows(candidate.direction, n_long, n_short)
        if not dir_ok:
            journal({**base, "event": "skip_direction_imbalance", "note": dir_reason})
            continue

        qta = quote_to_account_rate(candidate.pair, account_ccy, mid_by_pair)
        if qta is None or qta <= 0:
            journal({
                **base,
                "event": "skip_no_conversion",
                "note": f"no path {candidate.pair.split('_')[1]} -> {account_ccy}",
            })
            continue

        risk_dollars = equity * candidate.risk_pct
        units = compute_units(
            risk_in_account_ccy=risk_dollars,
            entry_price=candidate.entry,
            stop_price=candidate.stop,
            quote_to_account=qta,
            direction=candidate.direction,
        )
        if units == 0:
            journal({**base, "event": "skip_zero_units"})
            continue

        est_margin = estimate_order_margin(
            units, candidate.entry, qta, margin_rate,
        )
        order_fields = {
            **base,
            "units": str(units),
            "risk_dollars": f"{risk_dollars:.2f}",
            "quote_to_account": f"{qta:.6f}",
            "est_margin": f"{est_margin:.2f}",
            "headroom": f"{headroom:.2f}",
        }
        if est_margin > headroom:
            journal({**order_fields, "event": "skip_margin_budget"})
            continue

        if dry_run:
            journal({**order_fields, "event": "would_open", "status": "dry_run"})
            headroom -= est_margin
            open_pair_set.add(candidate.pair)
            if candidate.direction == "long":
                n_long += 1
            else:
                n_short += 1
            continue

        if n_placed >= MAX_NEW_ORDERS_PER_RUN:
            journal({**order_fields, "event": "skip_cap"})
            continue

        try:
            if candidate.entry_mode == "limit":
                resp = trader.create_limit_order_with_bracket(
                    instrument=candidate.pair,
                    units=units,
                    limit_price=candidate.entry,
                    stop_loss_price=candidate.stop,
                    take_profit_price=candidate.target,
                    gtd_time=candidate.gtd,
                    price_precision=candidate.price_precision,
                    client_tag=candidate.client_tag,
                )
            else:
                resp = trader.create_market_order_with_bracket(
                    instrument=candidate.pair,
                    units=units,
                    stop_loss_price=candidate.stop,
                    take_profit_price=candidate.target,
                    price_precision=candidate.price_precision,
                    client_tag=candidate.client_tag,
                )
        except OandaTraderError as exc:
            exc_msg = str(exc)
            event = "skip_market_halted" if "MARKET_HALTED" in exc_msg else "order_failed"
            journal({**order_fields, "event": event, "status": "failed", "note": exc_msg[:200]})
            continue

        n_placed += 1
        headroom -= est_margin
        open_pair_set.add(candidate.pair)
        if candidate.direction == "long":
            n_long += 1
        else:
            n_short += 1
        journal({
            **order_fields,
            "event": "order_placed",
            "order_id": _order_id(resp),
            "status": "submitted",
        })
    return n_placed


_ENTRY_MODE_BY_STRATEGY = {c.strategy: c.entry_mode for c in CELLS}


def _parse_oanda_iso(iso: str) -> datetime:
    if "." in iso:
        head, frac = iso.split(".")
        frac = frac.rstrip("Z")[:6]
        iso = f"{head}.{frac}+00:00"
    else:
        iso = iso.replace("Z", "+00:00")
    return datetime.fromisoformat(iso)


def _tag_source_and_mode(tag: str) -> tuple[str, str, str] | None:
    if tag.startswith("rising3bar:"):
        return R3B_SOURCE, "", ""
    if tag.startswith("v2:"):
        parts = tag.split(":")
        if len(parts) < 4:
            return None
        strategy = parts[1]
        entry_mode = _ENTRY_MODE_BY_STRATEGY.get(strategy, "")
        return V2_SOURCE, strategy, entry_mode
    return None


def _cap_for_trade(source: str, entry_mode: str, config: dict) -> Optional[float]:
    caps = config.get("bh_ftmo_trader", {}).get("max_position_age_days_by_source", {})
    if source == R3B_SOURCE:
        return caps.get(R3B_SOURCE)
    if source == V2_SOURCE:
        v2_caps = caps.get(V2_SOURCE, {})
        return v2_caps.get(entry_mode)
    return None


def close_aged_positions(
    trader: OandaTrader,
    config: dict,
    *,
    dry_run: bool,
    now: datetime | None = None,
    journal=append_journal_row,
) -> int:
    now = now or datetime.now(UTC)
    try:
        trades = trader.get_open_trades()
    except OandaTraderError as exc:
        LOG.warning("age-close: failed to fetch open trades: %s", exc)
        return 0

    closed = 0
    for trade in trades:
        tag = (trade.get("clientExtensions") or {}).get("tag", "")
        parsed = _tag_source_and_mode(tag)
        if parsed is None:
            continue
        source, strategy, entry_mode = parsed
        cap_days = _cap_for_trade(source, entry_mode, config)
        if cap_days is None:
            continue
        try:
            opened = _parse_oanda_iso(trade["openTime"])
        except (KeyError, ValueError):
            continue
        age_days = (now - opened).total_seconds() / 86400
        if age_days < float(cap_days):
            continue

        instrument = trade.get("instrument", "?")
        units = int(trade.get("currentUnits", 0))
        side = "long" if units > 0 else "short"
        row = {
            "ts_utc": datetime.now(UTC).isoformat(),
            "run_mode": "dry-run" if dry_run else "live",
            "event": "would_close_aged" if dry_run else "closed_aged",
            "source": source,
            "strategy": strategy,
            "pair": instrument,
            "direction": side,
            "entry_mode": entry_mode,
            "note": f"age={age_days:.1f}d cap={cap_days}d",
        }
        if dry_run:
            journal(row)
            continue
        try:
            trader.close_position(instrument, side=side)
            closed += 1
            journal(row)
        except OandaTraderError as exc:
            journal({
                **row,
                "event": "close_aged_failed",
                "note": str(exc)[:200],
            })
    return closed


def _load_all_bars(pair_specs: list[PairSpec]) -> tuple[dict[str, pd.DataFrame], dict[str, float]]:
    lookback = max(R3B_LOOKBACK_BARS, V2_LOOKBACK_BARS)
    bars_by_pair: dict[str, pd.DataFrame] = {}
    mid_by_pair: dict[str, float] = {}
    store = FxStore(read_only=True)
    try:
        for spec in pair_specs:
            df = store.load(spec.symbol, granularity="H4", include_incomplete=False)
            if df is None or df.empty or len(df) < 60:
                LOG.warning("skipping %s: insufficient bars (%d)", spec.symbol, 0 if df is None else len(df))
                continue
            df = df.tail(lookback).reset_index(drop=True)
            bars_by_pair[spec.symbol] = df
            mid_by_pair[spec.symbol] = latest_mid_close(df)
    finally:
        store.close()
    return bars_by_pair, mid_by_pair


def run(*, dry_run: bool) -> int:
    _archive_obsolete_journal_if_needed()
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    account_ccy = cfg["ftmo"]["account_currency"].upper()
    pair_specs = load_pair_specs()
    bars_by_pair, mid_by_pair = _load_all_bars(pair_specs)

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
            account_ccy = currency.upper()
        if equity <= 0:
            LOG.error("account equity <= 0; aborting")
            return 1

        close_aged_positions(trader, cfg, dry_run=dry_run)

        try:
            open_positions = trader.get_open_positions()
        except OandaTraderError as exc:
            LOG.error("Failed to fetch open positions: %s", exc)
            return 1

        sources: list[SignalSource] = [
            Rising3BarSource(pair_specs),
            V2CellSource(),
        ]
        candidates: list[OrderCandidate] = []
        for source in sources:
            source_candidates = source.candidates(
                bars_by_pair=bars_by_pair,
                mid_by_pair=mid_by_pair,
                account_ccy=account_ccy,
                equity=equity,
            )
            LOG.info("%s emitted %d candidate(s)", source.name, len(source_candidates))
            candidates.extend(source_candidates)

        if not candidates:
            append_journal_row({
                "ts_utc": datetime.now(UTC).isoformat(),
                "run_mode": "dry-run" if dry_run else "live",
                "event": "no_candidates",
                "equity": f"{equity:.2f}",
            })
            return 0

        n_placed = place_candidates(
            trader=trader,
            candidates=candidates,
            account_summary=account,
            open_positions=open_positions,
            mid_by_pair=mid_by_pair,
            account_ccy=account_ccy,
            equity=equity,
            dry_run=dry_run,
        )
        LOG.info("done: placed %d new order(s) (mode=%s)", n_placed, "dry" if dry_run else "live")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="BH FTMO unified autonomous trader")
    parser.add_argument("--dry-run", action="store_true",
                        help="Detect + log signals but do not submit or close")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
