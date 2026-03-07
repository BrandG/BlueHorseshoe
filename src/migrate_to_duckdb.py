#!/usr/bin/env python3
"""
One-time migration: Copy OHLCV data from MongoDB → DuckDB.

Usage:
    docker exec bluehorseshoe python src/migrate_to_duckdb.py [--verify-only]

Reads every document from ``historical_prices``, converts the nested
``days`` array to a flat DataFrame, and writes it to DuckDB via
``DuckDBStore.save_symbol()``.

With ``--verify-only``, skips the copy and just compares row counts
between MongoDB and DuckDB.
"""
import logging
import random
import sys
import time

import pandas as pd
from pymongo import MongoClient

from bluehorseshoe.core.config import get_settings
from bluehorseshoe.data.duckdb_store import DuckDBStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def migrate(settings=None):
    """Copy all historical_prices documents from MongoDB to DuckDB."""
    if settings is None:
        settings = get_settings()

    client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    db = client[settings.mongo_db]
    collection = db["historical_prices"]

    store = DuckDBStore(settings.duckdb_path)

    total = collection.count_documents({})
    logger.info("Starting migration: %d documents in historical_prices", total)

    t0 = time.time()
    migrated = 0
    skipped = 0

    cursor = collection.find({}, batch_size=50)
    for doc in cursor:
        symbol = doc.get("symbol")
        days = doc.get("days")
        if not symbol or not days:
            skipped += 1
            continue

        df = pd.DataFrame(days)
        full_name = doc.get("full_name", symbol)
        store.save_symbol(symbol, df, full_name=full_name)
        migrated += 1

        if migrated % 100 == 0:
            elapsed = time.time() - t0
            rate = migrated / elapsed if elapsed > 0 else 0
            logger.info(
                "Progress: %d/%d migrated (%.0f sym/s)", migrated, total, rate
            )

    elapsed = time.time() - t0
    logger.info(
        "Migration complete: %d migrated, %d skipped in %.1fs",
        migrated, skipped, elapsed,
    )

    store.close()
    client.close()
    return migrated


def verify(settings=None):
    """Compare MongoDB and DuckDB row counts for random symbols."""
    if settings is None:
        settings = get_settings()

    client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    db = client[settings.mongo_db]
    collection = db["historical_prices"]

    store = DuckDBStore(settings.duckdb_path)

    mongo_count = collection.count_documents({})
    duck_count = store.symbol_count()
    logger.info("Symbol counts — MongoDB: %d, DuckDB: %d", mongo_count, duck_count)

    # Spot-check 20 random symbols
    all_symbols = [doc["symbol"] for doc in collection.find({}, {"symbol": 1, "_id": 0})]
    sample = random.sample(all_symbols, min(20, len(all_symbols)))

    mismatches = 0
    for sym in sample:
        mongo_doc = collection.find_one({"symbol": sym})
        mongo_rows = len(mongo_doc.get("days", [])) if mongo_doc else 0
        duck_rows = store.row_count(sym)

        if mongo_rows != duck_rows:
            logger.warning("MISMATCH %s: MongoDB=%d, DuckDB=%d", sym, mongo_rows, duck_rows)
            mismatches += 1
        else:
            # Check last date matches
            if mongo_rows > 0:
                mongo_last = mongo_doc["days"][-1]["date"]
                duck_dates = store.get_symbol_dates(sym)
                duck_last = duck_dates[-1] if duck_dates else None
                if mongo_last != duck_last:
                    logger.warning(
                        "DATE MISMATCH %s: MongoDB=%s, DuckDB=%s",
                        sym, mongo_last, duck_last,
                    )
                    mismatches += 1
                else:
                    logger.info("OK %s: %d rows, last=%s", sym, mongo_rows, mongo_last)

    if mismatches == 0:
        logger.info("Verification passed: all %d spot-checked symbols match", len(sample))
    else:
        logger.warning("Verification found %d mismatches out of %d checked", mismatches, len(sample))

    store.close()
    client.close()
    return mismatches


if __name__ == "__main__":
    if "--verify-only" in sys.argv:
        verify()
    else:
        migrate()
        verify()
