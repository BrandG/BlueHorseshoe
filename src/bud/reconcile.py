"""Append-only outcome reconciler for OANDA-tagged BH FTMO trades."""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

from bh_ftmo.trading.oanda_trader import OandaTrader, OandaTraderConfig, OandaTraderError
from bud.auto_v2 import _ENTRY_MODE_BY_STRATEGY

REPO_ROOT = Path(__file__).resolve().parents[2]
JOURNAL_PATH = REPO_ROOT / "src" / "logs" / "bh_ftmo_trader_journal.csv"
OUTCOMES_PATH = REPO_ROOT / "src" / "logs" / "bh_ftmo_outcomes.csv"

OUTCOME_FIELDS = [
    "reconciled_ts_utc", "trade_id", "tag", "source", "strategy", "pair",
    "direction", "entry_mode", "open_time", "close_time", "open_price",
    "close_price", "units", "realized_pl", "financing", "risk_dollars",
    "realized_r", "r_multiple_price", "close_reason",
]

LOG = logging.getLogger("bud.reconcile")


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _fmt(value: Decimal | None, places: int = 10) -> str:
    if value is None:
        return ""
    quant = Decimal(1).scaleb(-places)
    text = str(value.quantize(quant).normalize())
    return "0" if text == "-0" else text


def _tag_from_row(row: dict[str, str]) -> str:
    source = row.get("source", "")
    if source == "v2":
        strategy = row.get("strategy", "")
        direction = row.get("direction", "")
        ts = _compact_ts(row.get("trigger_bar_close_ts", "") or row.get("trigger_bar_ts", ""))
        return f"v2:{strategy}:{direction}:{ts}" if strategy and direction and ts else ""
    if source == "rising_3bar":
        ts = _compact_ts(row.get("trigger_bar_ts", "") or row.get("trigger_bar_close_ts", ""))
        return f"rising3bar:{ts}" if ts else ""
    return ""


def _compact_ts(value: str) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if len(text) == 12 and text.isdigit():
        return text
    try:
        ts = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        digits = "".join(ch for ch in text if ch.isdigit())
        return digits[:12] if len(digits) >= 12 else ""
    return ts.strftime("%Y%m%d%H%M")


def _parse_tag(tag: str) -> Optional[tuple[str, str, str, str]]:
    if tag.startswith("v2:"):
        parts = tag.split(":")
        if len(parts) != 4 or not parts[1] or not parts[2]:
            return None
        strategy = parts[1]
        return "v2", strategy, parts[2], _ENTRY_MODE_BY_STRATEGY.get(strategy, "")
    if tag.startswith("rising3bar:"):
        return "rising_3bar", "", "long", "market"
    return None


def _load_existing_trade_ids() -> set[str]:
    if not OUTCOMES_PATH.exists():
        return set()
    with open(OUTCOMES_PATH, "r", newline="", encoding="utf-8") as f:
        return {row.get("trade_id", "") for row in csv.DictReader(f) if row.get("trade_id")}


def _load_placements() -> dict[tuple[str, str], dict[str, str]]:
    # Keyed by (tag, pair): the tag alone is NOT unique — a v2 strategy can fire
    # several pairs the same direction on one bar (all share v2:<strategy>:<dir>:<ts>),
    # and rising_3bar's tag carries no pair at all. Folding the pair into the key
    # keeps each trade joined to its own placement (risk_dollars, stop, target).
    if not JOURNAL_PATH.exists():
        return {}
    placements: dict[tuple[str, str], dict[str, str]] = {}
    with open(JOURNAL_PATH, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("event") != "order_placed":
                continue
            tag = _tag_from_row(row)
            if tag:
                placements[(tag, row.get("pair", ""))] = row
    return placements


def _infer_close_reason(close_price: Decimal | None, placement: dict[str, str] | None) -> str:
    if close_price is None or placement is None:
        return "unknown"
    target = _decimal(placement.get("target_price"))
    stop = _decimal(placement.get("stop_price"))
    if target is None or stop is None:
        return "unknown"

    tolerance = Decimal("0.0005")
    if "_" in placement.get("pair", "") and placement["pair"].endswith("_JPY"):
        tolerance = Decimal("0.05")

    target_distance = abs(close_price - target)
    stop_distance = abs(close_price - stop)
    if target_distance <= tolerance and target_distance <= stop_distance:
        return "target"
    if stop_distance <= tolerance and stop_distance < target_distance:
        return "stop"
    return "aged_or_manual"


def _price_r_multiple(
    direction: str,
    open_price: Decimal | None,
    close_price: Decimal | None,
    placement: dict[str, str] | None,
) -> Decimal | None:
    if placement is None or open_price is None or close_price is None:
        return None
    stop = _decimal(placement.get("stop_price"))
    if stop is None:
        return None
    if direction == "long":
        denom = open_price - stop
        return None if denom == 0 else (close_price - open_price) / denom
    if direction == "short":
        denom = stop - open_price
        return None if denom == 0 else (open_price - close_price) / denom
    return None


def _outcome_row(
    trade: dict[str, Any],
    tag: str,
    parsed: tuple[str, str, str, str],
    placement: dict[str, str] | None,
    reconciled_ts: str,
) -> dict[str, str]:
    source, strategy, direction, entry_mode = parsed
    open_price = _decimal(trade.get("price"))
    close_price = _decimal(trade.get("averageClosePrice"))
    realized_pl = _decimal(trade.get("realizedPL"))
    risk_dollars = _decimal(placement.get("risk_dollars")) if placement is not None else None
    realized_r = (
        None
        if realized_pl is None or risk_dollars is None or risk_dollars == 0
        else realized_pl / risk_dollars
    )
    r_multiple_price = _price_r_multiple(direction, open_price, close_price, placement)

    return {
        "reconciled_ts_utc": reconciled_ts,
        "trade_id": str(trade.get("id", "")),
        "tag": tag,
        "source": source,
        "strategy": strategy,
        "pair": str(trade.get("instrument") or (placement or {}).get("pair", "")),
        "direction": direction,
        "entry_mode": entry_mode,
        "open_time": str(trade.get("openTime", "")),
        "close_time": str(trade.get("closeTime", "")),
        "open_price": str(trade.get("price", "")),
        "close_price": str(trade.get("averageClosePrice", "")),
        "units": str(trade.get("initialUnits", "")),
        "realized_pl": str(trade.get("realizedPL", "")),
        "financing": str(trade.get("financing", "")),
        "risk_dollars": "" if risk_dollars is None else str(placement.get("risk_dollars", "")),
        "realized_r": _fmt(realized_r),
        "r_multiple_price": _fmt(r_multiple_price),
        "close_reason": _infer_close_reason(close_price, placement),
    }


def _append_outcomes(rows: list[dict[str, str]]) -> None:
    OUTCOMES_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_file = not OUTCOMES_PATH.exists()
    with open(OUTCOMES_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTCOME_FIELDS)
        if new_file:
            writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in OUTCOME_FIELDS})


def reconcile_outcomes(trader, *, dry_run: bool = False) -> int:
    """Append newly-closed tagged trades to the outcome journal."""
    trades = trader.get_closed_trades()
    known_trade_ids = _load_existing_trade_ids()
    placements = _load_placements()
    reconciled_ts = datetime.now(UTC).isoformat()
    rows: list[dict[str, str]] = []

    for trade in trades:
        trade_id = str(trade.get("id", ""))
        if not trade_id or trade_id in known_trade_ids:
            continue
        tag = (trade.get("clientExtensions") or {}).get("tag", "")
        if not tag:
            continue
        parsed = _parse_tag(tag)
        if parsed is None:
            continue
        placement = placements.get((tag, str(trade.get("instrument") or "")))
        rows.append(_outcome_row(trade, tag, parsed, placement, reconciled_ts))

    if dry_run:
        for row in rows:
            LOG.info(
                "[DRY] would write outcome trade_id=%s tag=%s realized_r=%s close_reason=%s",
                row["trade_id"], row["tag"], row["realized_r"], row["close_reason"],
            )
        return 0

    if rows:
        _append_outcomes(rows)
    return len(rows)


def main(argv: Optional[list[str]] = None) -> int:
    """Run the manual outcome reconciliation CLI."""
    parser = argparse.ArgumentParser(description="Reconcile OANDA closed trade outcomes")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and log, but append nothing")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    try:
        config = OandaTraderConfig.from_env()
    except OandaTraderError as exc:
        print(f"ERROR: {exc}")
        return 2
    with OandaTrader(config) as trader:
        count = reconcile_outcomes(trader, dry_run=args.dry_run)
    mode = "dry-run" if args.dry_run else "live"
    print(f"outcome reconcile complete mode={mode} rows_written={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
