"""
score_backfill_pick_date.py — pick the next date to score for the background backfill.

Walks backwards from the earliest date already present in `trade_scores`,
choosing the most recent SPY trading day strictly earlier than that cursor
which is not in the skip-list. Prints the chosen date (YYYY-MM-DD) on stdout
and exits 0. Exits 1 with a message on stderr when there is nothing to do.

Wrapper consumes stdout; do not print anything else there.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

from pymongo import MongoClient

from bluehorseshoe.core.config import get_settings
from bluehorseshoe.data.duckdb_store import DuckDBStore

DEFAULT_FLOOR = "2015-01-01"
TRADING_DAY_SOURCE_SYMBOL = "SPY"


def _read_skip_list(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out: set[str] = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.add(line.split()[0])
    return out


def main() -> int:
    floor = os.environ.get("BACKFILL_FLOOR_DATE", DEFAULT_FLOOR)
    skip_path = Path(os.environ.get(
        "BACKFILL_SKIP_FILE",
        Path(__file__).resolve().parent / "logs" / "score_backfill_skip.txt",
    ))

    settings = get_settings()
    client = MongoClient(settings.mongo_uri)
    try:
        db = client[settings.mongo_db]
        scored = set(db["trade_scores"].distinct("date"))
    finally:
        client.close()

    if not scored:
        print("trade_scores is empty; nothing to walk back from.", file=sys.stderr)
        return 1
    earliest_scored = min(scored)

    store = DuckDBStore(settings.duckdb_path, read_only=True)
    try:
        spy_dates = store.get_symbol_dates(TRADING_DAY_SOURCE_SYMBOL)
    finally:
        store.close()
    if not spy_dates:
        print("No SPY dates in DuckDB; cannot determine trading days.", file=sys.stderr)
        return 1

    skips = _read_skip_list(skip_path)

    today = date.today().isoformat()
    candidates = (
        d for d in reversed(spy_dates)
        if floor <= d < earliest_scored
        and d < today
        and d not in scored
        and d not in skips
    )
    pick = next(candidates, None)
    if pick is None:
        print(
            f"No unscored trading days between {floor} and {earliest_scored} "
            f"(skip-list has {len(skips)} entries).",
            file=sys.stderr,
        )
        return 1

    print(pick)
    return 0


if __name__ == "__main__":
    sys.exit(main())
