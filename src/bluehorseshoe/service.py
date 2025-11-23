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


def handle_trigger_action(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flexible action handler for development triggers.
    
    This function serves as a central dispatch point for temporary/development
    actions that you want to trigger from the API. Modify this function to
    add, remove, or change actions as needed during development.
    
    Args:
        action: String identifier for the action
        payload: Dictionary with action parameters
        
    Returns:
        Dictionary with action results
    """
    
    if action == "hello":
        # Simple test action
        name = payload.get("name", "World")
        return {"message": f"Hello, {name}!"}
    
    elif action == "test_db":
        # Test database connection and show collection stats
        try:
            collections = _db.list_collection_names()
            stats = {}
            for col_name in collections:
                stats[col_name] = _db[col_name].count_documents({})
            return {
                "collections": collections,
                "document_counts": stats
            }
        except Exception as e:
            return {"error": f"Database test failed: {e}"}
        
    # Add more actions here as needed during development
    # Just add new elif statements for different action names
    
    else:
        # Unknown action
        available_actions = ["hello", "test_db", "debug_symbols", "temp_calculation"]
        return {
            "error": f"Unknown action: {action}",
            "available_actions": available_actions,
            "hint": "Modify handle_trigger_action() in service.py to add new actions"
        }
        
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

