"""
Repository helpers for symbol and overview persistence.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from pymongo import UpdateOne
from pymongo.results import BulkWriteResult


def upsert_symbols(symbols: Iterable[Dict[str, Any]], *, database) -> int:
    """Upsert symbol documents into MongoDB."""
    symbols_collection = database["symbols"]
    symbols_collection.create_index("symbol", unique=True)

    operations = [
        UpdateOne({"symbol": symbol["symbol"]}, {"$set": symbol}, upsert=True)
        for symbol in symbols
        if symbol.get("symbol")
    ]
    if not operations:
        return 0

    result: BulkWriteResult = symbols_collection.bulk_write(operations, ordered=False)
    return (result.upserted_count or 0) + (result.modified_count or 0)


def get_symbols(*, database, limit: Optional[int] = None, active_only: bool = False) -> list[Dict[str, Any]]:
    """Read symbol documents from MongoDB."""
    query = {"active": True} if active_only else {}
    cursor = database["symbols"].find(query, {"_id": 0}).sort("symbol", 1)
    if limit:
        cursor = cursor.limit(limit)
    return list(cursor)


def upsert_overview(symbol: str, overview: Dict[str, Any], *, database) -> None:
    """Store company overview metadata."""
    normalized = symbol.upper().strip()
    if not normalized:
        raise ValueError("symbol is required")

    document = dict(overview)
    document["symbol"] = normalized
    document["last_updated"] = datetime.utcnow().isoformat()
    database["symbol_overviews"].update_one({"symbol": normalized}, {"$set": document}, upsert=True)


def get_overview(symbol: str, *, database) -> Dict[str, Any]:
    """Load company overview metadata for a symbol."""
    return database["symbol_overviews"].find_one({"symbol": symbol.upper().strip()}, {"_id": 0}) or {}


def backfill_missing_overviews(
    *,
    database,
    limit: Optional[int] = None,
) -> int:
    """Fetch overviews for symbols missing overview documents."""
    from bluehorseshoe.core.symbols import fetch_overview_from_net  # pylint: disable=import-outside-toplevel

    existing = {doc["symbol"] for doc in database["symbol_overviews"].find({}, {"symbol": 1, "_id": 0})}
    candidates = database["symbols"].find(
        {"symbol": {"$nin": list(existing)}, "exchange": {"$nin": ["NYSE ARCA"]}},
        {"symbol": 1, "_id": 0},
    ).sort("symbol", 1)

    symbols = [doc["symbol"] for doc in candidates]
    if limit:
        symbols = symbols[:limit]

    logging.info("Backfilling overviews for %d symbols", len(symbols))
    fetched = 0
    for symbol in symbols:
        try:
            overview = fetch_overview_from_net(symbol)
            if overview and "Symbol" in overview:
                upsert_overview(symbol, overview, database=database)
                fetched += 1
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.error("Overview fetch failed for %s: %s", symbol, exc)

    logging.info("Overview backfill complete: %d/%d fetched", fetched, len(symbols))
    return fetched
