"""Append-only CSV journal for bh_swing.

Single source of truth for decision/event history. Each row is a state-change
event or a no-op decision (e.g., skip_paused). The reconciler reads the most
recent fill timestamp from this file to compute the high-water mark for
deduplication — there is no other state store.
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import Iterable

from bluehorseshoe.core.config import REPO_ROOT

JOURNAL_PATH = os.path.join(REPO_ROOT, "src", "logs", "bh_swing_journal.csv")

# Event vocabulary. Reconciler-emitted events on top, action events on bottom.
EVENT_FILL_DETECTED = "fill_detected"
EVENT_POSITION_OPENED = "position_opened"
EVENT_POSITION_CLOSED = "position_closed"
EVENT_PARTIAL_FILL = "partial_fill"
EVENT_ORDER_CANCELLED = "order_cancelled"
EVENT_ORDER_REJECTED = "order_rejected"
EVENT_RUN_START = "run_start"
EVENT_RUN_END = "run_end"
EVENT_RUN_ERROR = "run_error"
# Reserved for later phases:
EVENT_ORDER_PLACED = "order_placed"
EVENT_STOP_ADVANCED = "stop_advanced"
EVENT_EARLY_EXIT = "early_exit"
EVENT_SKIP_PAUSED = "skip_paused"
EVENT_SKIP_CASH = "skip_cash"
EVENT_SKIP_DUPLICATE = "skip_duplicate"
EVENT_SKIP_POSITION_CAP = "skip_position_cap"


@dataclass
class JournalRow:
    """One line in src/logs/bh_swing_journal.csv."""
    ts_utc: str = ""
    run_mode: str = ""           # "live" | "dry-run"
    event: str = ""
    symbol: str = ""
    side: str = ""               # "buy" | "sell" | ""
    quantity: int = 0
    price: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    order_id: str = ""
    exec_id: str = ""
    pnl: float = 0.0
    nav: float = 0.0
    settled_cash: float = 0.0
    note: str = ""


def _ensure_dir() -> None:
    os.makedirs(os.path.dirname(JOURNAL_PATH), exist_ok=True)


def _header() -> list[str]:
    return [f.name for f in fields(JournalRow)]


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def append(row: JournalRow) -> None:
    """Append a single row. Creates header if file is new."""
    _ensure_dir()
    if not row.ts_utc:
        row.ts_utc = now_utc_iso()
    new_file = not os.path.exists(JOURNAL_PATH)
    with open(JOURNAL_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(_header())
        w.writerow([getattr(row, name) for name in _header()])


def append_many(rows: Iterable[JournalRow]) -> None:
    rows = list(rows)
    if not rows:
        return
    _ensure_dir()
    new_file = not os.path.exists(JOURNAL_PATH)
    with open(JOURNAL_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(_header())
        ts = now_utc_iso()
        for row in rows:
            if not row.ts_utc:
                row.ts_utc = ts
            w.writerow([getattr(row, name) for name in _header()])


def read_recent(limit: int = 200) -> list[dict]:
    """Return up to `limit` most recent rows as dicts, newest first."""
    if not os.path.exists(JOURNAL_PATH):
        return []
    with open(JOURNAL_PATH, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)
    return list(reversed(all_rows[-limit:]))


def last_seen_exec_ids(window: int = 5000) -> set[str]:
    """Exec IDs already journaled in the trailing `window` rows.

    Used by the reconciler as a stateless dedup key — IBKR exec_ids are stable
    and unique per fill, so any exec_id we've already written is one we should
    not write again. Window keeps the read bounded.
    """
    rows = read_recent(limit=window)
    return {r["exec_id"] for r in rows if r.get("exec_id")}
