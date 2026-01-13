"""
symbols.py (v1.0)
"""

from __future__ import annotations

import os
import time
import logging
from datetime import datetime
from typing import List, Dict, Any

from pymongo.collection import Collection
from requests.exceptions import RequestException

from .symbols import (
    refresh_historical_for_symbol,
    fetch_daily_ohlc_from_net,
)
from .database import db


# -------------------------------
# Config
# -------------------------------

BATCH_LIMIT = int(os.environ.get("BH_BATCH_LIMIT", "50"))   # how many symbols per run
SLEEP_BETWEEN = float(os.environ.get("BH_SLEEP_SECONDS", "0.9"))  # small cushion for AV limits
RECENT_ONLY = os.environ.get("BH_RECENT_ONLY", "false").lower() == "true"

CHECKPOINT_COLLECTION = os.environ.get("BH_CHECKPOINT_COLLECTION", "loader_checkpoints")
CHECKPOINT_ID = os.environ.get("BH_CHECKPOINT_ID", "historical_batch_v1")

LOG_LEVEL = os.environ.get("BH_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))


def _checkpoint_col() -> Collection:
    """Return the checkpoint collection."""
    return db.get_db()[CHECKPOINT_COLLECTION]


def get_checkpoint() -> Dict[str, Any]:
    """
    Returns checkpoint doc:
      {
        "_id": CHECKPOINT_ID,
        "last_symbol": "AAPL",
        "updated_at": "...",
        "run_count": 12,
        "processed_total": 600
      }
    """
    doc = _checkpoint_col().find_one({"_id": CHECKPOINT_ID}) or {}
    return doc


def set_checkpoint(last_symbol: str, processed_total: int, run_count: int) -> None:
    """Update the batch loader checkpoint in the database."""
    _checkpoint_col().update_one(
        {"_id": CHECKPOINT_ID},
        {"$set": {
            "last_symbol": last_symbol,
            "processed_total": processed_total,
            "run_count": run_count,
            "updated_at": datetime.utcnow().isoformat(),
        }},
        upsert=True
    )


def clear_checkpoint() -> None:
    """Remove the current checkpoint."""
    _checkpoint_col().delete_one({"_id": CHECKPOINT_ID})

def _active_symbols_after(last_symbol, limit) -> List[str]:
    """
    Get next symbols alphabetically after last_symbol.
    Uses Mongo sort order so it's stable.
    """
    query = {"active": True}
    if last_symbol:
        query["symbol"] = {"$gt": last_symbol}

    cursor = (
        db.get_db()["symbols"]
        .find(query, {"_id":0, "symbol":1})
        .sort("symbol", 1)
        .limit(limit)
    )
    return [d["symbol"] for d in cursor]

def _symbols_after(last_symbol, limit, active_only: bool) -> List[str]:
    """Retrieve a list of symbols alphabetically following the last symbol."""
    query = {}
    if active_only:
        query["active"] = True
    if last_symbol:
        query["symbol"] = {"$gt": last_symbol}

    cursor = (
        db.get_db()["symbols"]
        .find(query, {"_id": 0, "symbol": 1})
        .sort("symbol", 1)
        .limit(limit)
    )
    return [d["symbol"] for d in cursor]

def run_historical_batch(
    limit: int = BATCH_LIMIT,
    recent_only: bool = RECENT_ONLY,
    sleep_seconds: float = SLEEP_BETWEEN,
    classify: bool = False,
) -> Dict[str, Any]:
    """
    Run a single batch of historical loads.
    Safe to call from cron repeatedly.

    Returns a summary payload suitable for logs / API.
    """
    ck = get_checkpoint()
    last_symbol = ck.get("last_symbol")
    run_count = int(ck.get("run_count", 0)) + 1
    processed_total = int(ck.get("processed_total", 0))

    symbols = _symbols_after(last_symbol, limit, active_only=not classify)

    if not symbols:
        logging.info("No more symbols after %s. Batch complete.", last_symbol)
        return {
            "status": "done",
            "last_symbol": last_symbol,
            "processed_total": processed_total,
            "run_count": run_count,
        }

    successes = 0
    failures = 0
    failed_symbols: List[str] = []
    current_last = last_symbol

    logging.info("Starting batch run #%d. last_symbol=%s limit=%d recent_only=%s",
                 run_count, last_symbol, limit, recent_only)

    for sym in symbols:
        current_last = sym
        try:
            refresh_historical_for_symbol(sym, recent=recent_only)
            successes += 1
            processed_total += 1
            logging.info("Loaded %s (%d/%d this batch)", sym, successes + failures, len(symbols))
        except (RuntimeError, ValueError, RequestException) as e:
            failures += 1
            processed_total += 1
            failed_symbols.append(sym)
            logging.exception("Failed loading %s: %s", sym, e)

        # cushion for AV + keep CPU polite
        time.sleep(sleep_seconds)

        # checkpoint after each symbol so restarts are painless
        set_checkpoint(current_last, processed_total, run_count)

#    if classify:
#        classify_symbol_activity(symbol, days)

    summary = {
        "status": "ok",
        "batch_size": len(symbols),
        "successes": successes,
        "failures": failures,
        "failed_symbols": failed_symbols[:20],  # cap log size
        "last_symbol": current_last,
        "processed_total": processed_total,
        "run_count": run_count,
        "recent_only": recent_only,
    }

    logging.info("Batch summary: %s", summary)
    return summary

def classify_symbols_batch(limit=50, sleep_seconds=1.2):
    """Classify a batch of symbols by updating their data."""
    ck = get_checkpoint()
    last_symbol = ck.get("last_symbol")
    symbols = _symbols_after(last_symbol, limit, active_only=False)

    if not symbols:
        return {"status": "done"}

    processed_total = int(ck.get("processed_total", 0))
    run_count = int(ck.get("run_count", 0)) + 1
    for sym in symbols:
        fetch_daily_ohlc_from_net(sym, recent=True)  # compact

        refresh_historical_for_symbol(sym, True)

        processed_total += 1
        set_checkpoint(sym, processed_total, run_count)
        time.sleep(sleep_seconds)

    return {"status": "ok", "last_symbol": symbols[-1]}

if __name__ == "__main__":
    run_historical_batch()
