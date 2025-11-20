# src/bluehorseshoe/service.py

from datetime import date
from typing import Dict, Any, Optional
import os
from pymongo import MongoClient, UpdateOne

def run_backtest(symbol: str, start: date, end: date, strategy: str = "baseline") -> Dict[str, Any]:
    """
    Placeholder backtest implementation.

    In the future, this will:
      - load historical data
      - run the selected strategy
      - compute metrics (CAGR, max drawdown, etc.)
    """
    return {
        "status": "not_implemented",
        "symbol": symbol,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "strategy": strategy,
        "summary": {
            "trades": 0,
            "total_return": 0.0,
            "cagr": 0.0,
            "max_drawdown": 0.0,
        },
    }


def run_daily() -> Dict[str, Any]:
    """
    Placeholder daily run.

    In the future, this will:
      - generate today's universe
      - rank candidates
      - store results in Mongo
    """
    return {
        "status": "not_implemented",
        "date": date.today().isoformat(),
        "top_candidates": [],
        "notes": "Daily pipeline stub; implement logic in bluehorseshoe.service.run_daily().",
    }

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://mongo:27017")
_client = MongoClient(MONGO_URI)
_db = _client["bluehorseshoe"]
_symbols = _db["symbols"]

# Create a unique index on symbol so upserts behave cleanly
_symbols.create_index("symbol", unique=True)

_prices = _db["historical_prices"]
_prices.create_index("symbol", unique=True)

def sync_symbols_to_mongo(symbol_list):
    """
    Upsert a list of {'symbol':..., 'name':...} dicts into the MongoDB collection.
    """
    if not symbol_list:
        return 0

    ops = []
    for item in symbol_list:
        sym = item.get("symbol")
        if not sym:
            continue
        ops.append(
            UpdateOne(
                {"symbol": sym},
                {"$set": item},
                upsert=True
            )
        )

    if not ops:
        return 0

    result = _symbols.bulk_write(ops, ordered=False)
    return (result.upserted_count or 0) + (result.modified_count or 0)

def load_historical_data_from_mongo(symbol: str, client: MongoClient) -> Optional[Dict[str, Any]]:
    """
    Load a symbol's historical data document from MongoDB.
    Returns None if not found.
    """
    db = client["bluehorseshoe"]
    prices = db["historical_prices"]
    doc = prices.find_one({"symbol": symbol})
    return doc

def save_historical_data_to_mongo(symbol_data: Dict[str, Any], client: MongoClient) -> None:
    """
    Upsert a symbol's historical data document into MongoDB.
    Expects a dict with at least 'symbol' and 'days' keys.
    """
    db = client["bluehorseshoe"]
    prices = db["historical_prices"]

    symbol = symbol_data.get("name") or symbol_data.get("symbol")
    if not symbol:
        return

    doc = {
        "symbol": symbol,
        "days": symbol_data.get("days", []),
        "last_updated": datetime.utcnow().isoformat(),
    }

    prices.update_one(
        {"symbol": symbol},
        {"$set": doc},
        upsert=True,
    )

