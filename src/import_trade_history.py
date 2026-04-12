"""Import raw broker trade history CSV into journal-shaped documents."""
from __future__ import annotations

import argparse
import csv
import logging
import os
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Deque, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - depends on runtime environment
    load_dotenv = None

from pymongo import MongoClient

QUANTITY_TOLERANCE = 0.001
DEFAULT_CSV_PATH = "data/trade_history.csv"

logger = logging.getLogger(__name__)


@dataclass
class ParsedFill:
    """One raw broker fill parsed from CSV."""

    date: object
    side: str
    quantity: float
    symbol: str
    price: float
    row_number: int = 0
    fill_id: str = ""


@dataclass
class BuyLot:
    """Remaining shares from a buy fill available for FIFO matching."""

    date: object
    quantity_remaining: float
    price: float
    fill_id: str


def noon_utc(fill_date) -> datetime:
    """Return noon UTC for a date."""
    return datetime.combine(fill_date, time(12, 0), tzinfo=timezone.utc)


def parse_csv(csv_path: str) -> List[ParsedFill]:
    """Parse trade history CSV rows into normalized fills."""
    fills: List[ParsedFill] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row_number, row in enumerate(reader, start=2):
            date_value = datetime.strptime(row["Date Received"].strip(), "%m/%d/%Y").date()
            type_value = row["Type"].strip().upper()
            if type_value not in {"BOUGHT", "SOLD"}:
                raise ValueError(f"Unsupported Type at row {row_number}: {type_value}")
            fills.append(
                ParsedFill(
                    date=date_value,
                    side="buy" if type_value == "BOUGHT" else "sell",
                    quantity=float(row["Quantity"]),
                    symbol=row["Asset"].strip().upper(),
                    price=float(row["Price"]),
                    row_number=row_number,
                )
            )
    return fills


def assign_fill_ids(fills: Iterable[ParsedFill]) -> List[ParsedFill]:
    """Assign stable CSV fill IDs with per-date-symbol-side counters."""
    counters: Dict[Tuple[object, str, str], int] = defaultdict(int)
    assigned: List[ParsedFill] = []
    for fill in fills:
        key = (fill.date, fill.symbol, fill.side)
        counters[key] += 1
        fill.fill_id = f"csv_{fill.date.isoformat()}_{fill.symbol}_{fill.side}_{counters[key]}"
        assigned.append(fill)
    return assigned


def fill_to_doc(fill: ParsedFill, created_at: Optional[datetime] = None) -> dict:
    """Convert a parsed fill to a trade_fills-compatible document."""
    created_at = created_at or datetime.now(timezone.utc)
    return {
        "fill_id": fill.fill_id,
        "symbol": fill.symbol,
        "side": fill.side,
        "quantity": fill.quantity,
        "price": fill.price,
        "commission": 0.0,
        "exec_time": noon_utc(fill.date),
        "exec_id": fill.fill_id,
        "order_ref": None,
        "idea_id": None,
        "source": "csv",
        "created_at": created_at,
    }


def generate_fill_documents(fills: Iterable[ParsedFill], created_at: Optional[datetime] = None) -> List[dict]:
    """Generate trade_fills-compatible documents."""
    return [fill_to_doc(fill, created_at=created_at) for fill in fills]


def _weighted_avg(records: Sequence[Tuple[object, float, float, str]]) -> float:
    total_qty = sum(qty for _, qty, _, _ in records)
    if total_qty <= 0:
        return 0.0
    return sum(qty * price for _, qty, price, _ in records) / total_qty


def _outcome(pnl: float) -> str:
    if pnl > 0.005:
        return "win"
    if pnl < -0.005:
        return "loss"
    return "breakeven"


def _era_tag(opened_at: datetime) -> str:
    """Return era tag based on position open date."""
    if opened_at.date().year < 2026:
        return "pre_bh"
    return "bh_v2"


def _make_position_doc(
    *,
    position_id: str,
    symbol: str,
    buy_records: Sequence[Tuple[object, float, float, str]],
    sell_records: Sequence[Tuple[object, float, float, str]],
    total_pnl: float,
    status: str,
    created_at: datetime,
) -> dict:
    first_buy_date = min(record[0] for record in buy_records)
    last_sell_date = max((record[0] for record in sell_records), default=None)
    total_quantity = sum(record[1] for record in buy_records)
    actual_entry = _weighted_avg(buy_records)
    actual_exit = _weighted_avg(sell_records)
    hold_days = (last_sell_date - first_buy_date).days if last_sell_date else 0
    entry_ids = ",".join(record[3] for record in buy_records)
    exit_ids = ",".join(record[3] for record in sell_records) or None
    opened_at = noon_utc(first_buy_date)

    return {
        "position_id": position_id,
        "idea_id": None,
        "symbol": symbol,
        "strategy": "unknown",
        "status": status,
        "planned_entry": 0.0,
        "planned_stop": 0.0,
        "planned_target_t1": 0.0,
        "planned_target_t2": 0.0,
        "actual_entry": actual_entry,
        "legs": [
            {
                "leg": "FULL",
                "quantity": total_quantity,
                "entry_fill_id": entry_ids,
                "exit_fill_id": exit_ids,
                "entry_price": actual_entry,
                "exit_price": actual_exit,
                "close_reason": "manual" if status == "closed" else None,
                "pnl": total_pnl,
                "r_multiple": 0.0,
                "hold_days": hold_days,
            }
        ],
        "total_quantity": total_quantity,
        "total_pnl": total_pnl,
        "total_commission": 0.0,
        "entry_slippage": 0.0,
        "tags": ["csv_import", _era_tag(opened_at)],
        "opened_at": opened_at,
        "closed_at": noon_utc(last_sell_date) if last_sell_date else None,
        "created_at": created_at,
        "updated_at": created_at,
    }


def review_from_position(position: dict, created_at: Optional[datetime] = None) -> dict:
    """Create a trade_reviews-compatible document from a position."""
    created_at = created_at or datetime.now(timezone.utc)
    return {
        "review_id": f"review_{position['position_id']}",
        "position_id": position["position_id"],
        "idea_id": None,
        "symbol": position["symbol"],
        "strategy": "unknown",
        "batch_date": position["opened_at"].date().isoformat(),
        "planned_entry": 0.0,
        "planned_stop": 0.0,
        "planned_target_t2": 0.0,
        "actual_entry": position["actual_entry"],
        "actual_exit_avg": position["legs"][0]["exit_price"],
        "gross_pnl": position["total_pnl"],
        "net_pnl": position["total_pnl"],
        "r_multiple": 0.0,
        "entry_slippage_pct": 0.0,
        "hold_days": position["legs"][0]["hold_days"],
        "outcome": _outcome(position["total_pnl"]),
        "t1_hit": False,
        "t2_hit": False,
        "stop_hit": False,
        "followed_plan": True,
        "discipline_score": 1.0,
        "tags": position["tags"],
        "notes": "",
        "lessons_learned": "",
        "created_at": created_at,
        "updated_at": created_at,
    }


def synthesize_positions(fills: Iterable[ParsedFill]) -> Tuple[List[dict], List[ParsedFill], List[str]]:
    """Synthesize FIFO positions, returning positions, included fills, and warning messages."""
    created_at = datetime.now(timezone.utc)
    fills_by_symbol: Dict[str, List[ParsedFill]] = defaultdict(list)
    for fill in assign_fill_ids(fills):
        fills_by_symbol[fill.symbol].append(fill)

    positions: List[dict] = []
    included_fills: List[ParsedFill] = []
    warnings: List[str] = []
    position_seq: Dict[Tuple[object, str], int] = defaultdict(int)

    for symbol, symbol_fills in sorted(fills_by_symbol.items()):
        buy_queue: Deque[BuyLot] = deque()
        buy_records: List[Tuple[object, float, float, str]] = []
        sell_records: List[Tuple[object, float, float, str]] = []
        position_pnl = 0.0

        sorted_fills = sorted(
            symbol_fills,
            key=lambda fill: (fill.date, 0 if fill.side == "buy" else 1, fill.row_number),
        )

        for fill in sorted_fills:
            if fill.side == "buy":
                buy_queue.append(BuyLot(fill.date, fill.quantity, fill.price, fill.fill_id))
                buy_records.append((fill.date, fill.quantity, fill.price, fill.fill_id))
                included_fills.append(fill)
                continue

            if not buy_queue:
                warning = f"Skipped: {symbol} (orphan sell, no prior buy)"
                logger.warning(warning)
                warnings.append(warning)
                continue

            qty_to_sell = fill.quantity
            matched_qty = 0.0
            matched_pnl = 0.0
            while qty_to_sell > QUANTITY_TOLERANCE and buy_queue:
                lot = buy_queue[0]
                match_qty = min(qty_to_sell, lot.quantity_remaining)
                matched_qty += match_qty
                matched_pnl += (fill.price - lot.price) * match_qty
                lot.quantity_remaining -= match_qty
                qty_to_sell -= match_qty
                if lot.quantity_remaining < QUANTITY_TOLERANCE:
                    buy_queue.popleft()

            if matched_qty > QUANTITY_TOLERANCE:
                sell_records.append((fill.date, matched_qty, fill.price, fill.fill_id))
                included_fills.append(fill)
                position_pnl += matched_pnl

            if qty_to_sell > QUANTITY_TOLERANCE:
                warning = f"Unmatched sell quantity for {symbol}: {qty_to_sell:.4f}"
                logger.warning(warning)
                warnings.append(warning)

            if not buy_queue and buy_records:
                first_buy_date = min(record[0] for record in buy_records)
                position_seq[(first_buy_date, symbol)] += 1
                position_id = f"pos_csv_{first_buy_date.isoformat()}_{symbol}_{position_seq[(first_buy_date, symbol)]}"
                positions.append(
                    _make_position_doc(
                        position_id=position_id,
                        symbol=symbol,
                        buy_records=buy_records,
                        sell_records=sell_records,
                        total_pnl=position_pnl,
                        status="closed",
                        created_at=created_at,
                    )
                )
                buy_records = []
                sell_records = []
                position_pnl = 0.0

        if buy_records:
            first_buy_date = min(record[0] for record in buy_records)
            position_seq[(first_buy_date, symbol)] += 1
            position_id = f"pos_csv_{first_buy_date.isoformat()}_{symbol}_{position_seq[(first_buy_date, symbol)]}"
            warning = f"Open position for {symbol}: remaining quantity {sum(lot.quantity_remaining for lot in buy_queue):.4f}"
            logger.warning(warning)
            warnings.append(warning)
            positions.append(
                _make_position_doc(
                    position_id=position_id,
                    symbol=symbol,
                    buy_records=buy_records,
                    sell_records=sell_records,
                    total_pnl=position_pnl,
                    status="open",
                    created_at=created_at,
                )
            )

    return positions, included_fills, warnings


def build_import_documents(fills: Iterable[ParsedFill]) -> Tuple[List[dict], List[dict], List[dict], List[str]]:
    """Build fill, position, and review documents for import."""
    positions, included_fills, warnings = synthesize_positions(fills)
    fill_docs = generate_fill_documents(included_fills)
    review_docs = [review_from_position(position) for position in positions if position["status"] == "closed"]
    return fill_docs, positions, review_docs, warnings


def format_dry_run_summary(csv_path: str, parsed_count: int, fill_docs: List[dict], positions: List[dict], reviews: List[dict], warnings: Sequence[str]) -> str:
    """Format dry-run import summary."""
    lines = [
        f"Parsed {parsed_count} fills from {csv_path}",
        *warnings,
        f"Generated: {len(fill_docs)} fill documents, {len(positions)} positions, {len(reviews)} reviews",
        "",
        "Position Summary:",
        "  Symbol    Entry Date  Exit Date   Qty     Entry     Exit      P&L     Hold  Outcome",
    ]
    for position in positions:
        leg = position["legs"][0]
        exit_date = position["closed_at"].date().isoformat() if position["closed_at"] else "OPEN"
        outcome = _outcome(position["total_pnl"]) if position["status"] == "closed" else "open"
        lines.append(
            f"  {position['symbol']:<8}  {position['opened_at'].date().isoformat()}  {exit_date:<10} "
            f"{position['total_quantity']:>7.2f}  ${position['actual_entry']:>7.2f}  "
            f"${leg['exit_price']:>7.2f}  ${position['total_pnl']:>7.2f}  {leg['hold_days']:>3}d  {outcome}"
        )

    closed_positions = [position for position in positions if position["status"] == "closed"]
    wins = sum(1 for position in closed_positions if _outcome(position["total_pnl"]) == "win")
    losses = sum(1 for position in closed_positions if _outcome(position["total_pnl"]) == "loss")
    breakeven = sum(1 for position in closed_positions if _outcome(position["total_pnl"]) == "breakeven")
    win_rate = wins / len(closed_positions) * 100 if closed_positions else 0.0
    total_pnl = sum(position["total_pnl"] for position in positions)
    lines.extend(
        [
            "",
            f"Totals: {wins} wins, {losses} losses, {breakeven} breakeven",
            f"Win rate: {win_rate:.1f}%",
            f"Total P&L: ${total_pnl:.2f}",
        ]
    )
    return "\n".join(lines)


def connect_database():
    """Connect to MongoDB from environment variables."""
    if load_dotenv:
        load_dotenv()
    mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    mongo_db = os.environ.get("MONGO_DB", "bluehorseshoe")
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    client.server_info()
    return client, client[mongo_db]


def write_documents(db, fill_docs: List[dict], positions: List[dict], reviews: List[dict], force: bool = False) -> None:
    """Write import documents to MongoDB idempotently."""
    if force:
        db["trade_fills"].delete_many({"source": "csv"})
        db["trade_positions"].delete_many({"position_id": {"$regex": "^pos_csv_"}})
        db["trade_reviews"].delete_many({"tags": "csv_import"})

    for doc in fill_docs:
        db["trade_fills"].update_one({"fill_id": doc["fill_id"]}, {"$set": doc}, upsert=True)
    for doc in positions:
        db["trade_positions"].update_one({"position_id": doc["position_id"]}, {"$set": doc}, upsert=True)
    for doc in reviews:
        db["trade_reviews"].update_one({"review_id": doc["review_id"]}, {"$set": doc}, upsert=True)


def run_import(csv_path: str, dry_run: bool = False, force: bool = False) -> str:
    """Run the import pipeline and return a summary string."""
    parsed_fills = parse_csv(csv_path)
    fill_docs, positions, reviews, warnings = build_import_documents(parsed_fills)
    summary = format_dry_run_summary(csv_path, len(parsed_fills), fill_docs, positions, reviews, warnings)

    if dry_run:
        return summary

    client, db = connect_database()
    try:
        write_documents(db, fill_docs, positions, reviews, force=force)
    finally:
        client.close()
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Import raw trade history CSV into the trade journal.")
    parser.add_argument("--csv", default=DEFAULT_CSV_PATH, help="Path to trade history CSV.")
    parser.add_argument("--dry-run", action="store_true", help="Print summary without writing to MongoDB.")
    parser.add_argument("--force", action="store_true", help="Delete prior CSV-imported docs before writing.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    csv_path = str(Path(args.csv))
    summary = run_import(csv_path, dry_run=args.dry_run, force=args.force)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
