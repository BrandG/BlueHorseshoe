"""Strategy-only P&L history for BH Swing.

This is deliberately forward-only. Realized P&L comes from newly observed
closing executions in the journal; unrealized P&L comes from mark minus cost.
"""
from __future__ import annotations

import csv
import os
from typing import Any

from bluehorseshoe.core.config import REPO_ROOT

from bh_swing import journal

PNL_HISTORY_PATH = os.path.join(REPO_ROOT, "src", "logs", "pnl_history.csv")

FIELDNAMES = ["ts_utc", "net_liq", "unrealized", "realized_cum", "n_positions"]


def _ensure_dir() -> None:
    os.makedirs(os.path.dirname(PNL_HISTORY_PATH), exist_ok=True)


def _as_csv_value(value: Any) -> Any:
    if value is None:
        return ""
    return value


def append_snapshot(
    ts: str,
    net_liq: float,
    unrealized: float | None,
    realized_cum: float,
    n_positions: int,
) -> None:
    """Append one strategy P&L snapshot, creating the CSV header if needed."""
    _ensure_dir()
    new_file = not os.path.exists(PNL_HISTORY_PATH)
    with open(PNL_HISTORY_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if new_file:
            writer.writeheader()
        writer.writerow({
            "ts_utc": ts,
            "net_liq": net_liq,
            "unrealized": _as_csv_value(unrealized),
            "realized_cum": realized_cum,
            "n_positions": n_positions,
        })


def read_history() -> list[dict]:
    """Read all strategy P&L snapshots for the tracker."""
    if not os.path.exists(PNL_HISTORY_PATH):
        return []
    with open(PNL_HISTORY_PATH, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def cumulative_realized() -> float:
    """Sum realized P&L from close fills captured in the BH Swing journal."""
    if not os.path.exists(journal.JOURNAL_PATH):
        return 0.0

    total = 0.0
    with open(journal.JOURNAL_PATH, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("event") != journal.EVENT_FILL_DETECTED:
                continue
            if (row.get("side") or "").lower() != "sell":
                continue
            try:
                total += float(row.get("pnl") or 0.0)
            except (TypeError, ValueError):
                continue
    return total
