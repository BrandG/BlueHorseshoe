"""
symbols.py (v1.2)

Core utilities for:
1) Fetching active symbols from Alpha Vantage and upserting to MongoDB.
2) Loading symbols from MongoDB.
3) Fetching historical OHLC data for one symbol from Alpha Vantage and upserting to MongoDB.
4) Loading historical OHLC data from MongoDB.
"""

from __future__ import annotations

from datetime import datetime, date
from typing import Any, Dict, List, Optional, Iterable
import os
import csv
import io
import logging

import requests
from ratelimit import limits, sleep_and_retry
from pymongo import UpdateOne
from pymongo.results import BulkWriteResult

# Import the centralized database instance
from .database import db

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------

ALPHAVANTAGE_KEY = os.environ.get("ALPHAVANTAGE_KEY", "")

# Rate Limit Configuration
# Default to 5 calls/sec (Premium Tier standard) if not set.
CPS = int(os.environ.get("ALPHAVANTAGE_CPS", "5"))

LISTING_STATUS_URL = "https://www.alphavantage.co/query?function=LISTING_STATUS&apikey={key}"
DAILY_SERIES_URL = (
    "https://www.alphavantage.co/query"
    "?function=TIME_SERIES_DAILY"
    "&outputsize={outputsize}"
    "&symbol={symbol}"
    "&apikey={key}"
)

OVERVIEW_URL = (
    "https://www.alphavantage.co/query"
    "?function=OVERVIEW"
    "&symbol={symbol}"
    "&apikey={key}"
)

RECENT_TRADING_DAYS = int(os.environ.get("RECENT_TRADING_DAYS", "240"))

# ---------------------------------------------------------------------
# Goal 1: Fetch symbol list from net -> upsert to Mongo
# ---------------------------------------------------------------------

@sleep_and_retry
@limits(calls=1, period=1)
def fetch_symbol_list_from_net() -> List[Dict[str, Any]]:
    """
    Fetch active NYSE/NASDAQ stock symbols from Alpha Vantage LISTING_STATUS.
    """
    if not ALPHAVANTAGE_KEY:
        raise RuntimeError("ALPHAVANTAGE_KEY not set in environment")

    url = LISTING_STATUS_URL.format(key=ALPHAVANTAGE_KEY)
    response = requests.get(url, timeout=15)
    response.raise_for_status()

    csv_file = io.StringIO(response.text)
    reader = csv.DictReader(csv_file)
    rows = list(reader)

    symbols: List[Dict[str, str]] = []
    for row in rows:
        sym = (row.get("symbol") or "").replace("/", "")
        # Basic filtering for valid common stocks
        if (
            row.get("status") == "Active"
            and row.get("exchange") in {"NYSE", "NASDAQ"}
            and row.get("assetType") == "Stock"
            and sym
            and "-" not in sym
        ):
            symbols.append({"symbol": sym, "name": row.get("name", "")})

    return symbols


def upsert_symbols_to_mongo(symbols: Iterable[Dict[str, Any]]) -> int:
    """
    Upsert symbol documents into MongoDB.
    """
    # Use the centralized db
    _db = db.get_db()
    _symbols_col = _db["symbols"]
    
    # Create index if it doesn't exist (idempotent)
    _symbols_col.create_index("symbol", unique=True)

    ops = [
        UpdateOne({"symbol": s["symbol"]}, {"$set": s}, upsert=True)
        for s in symbols
        if s.get("symbol")
    ]
    if not ops:
        return 0

    result: BulkWriteResult = _symbols_col.bulk_write(ops, ordered=False)
    return (result.upserted_count or 0) + (result.modified_count or 0)


def refresh_symbols() -> Dict[str, Any]:
    """
    Fetch symbols from net and store in MongoDB.
    """
    symbols = fetch_symbol_list_from_net()
    if not symbols:
        return {"status": "empty", "count": 0, "symbol_count": 0, "sample": []}

    count = upsert_symbols_to_mongo(symbols)

    return {
        "status": "ok",
        "count": count,
        "symbol_count": len(symbols),
        "sample": symbols[:5],
    }


# ---------------------------------------------------------------------
# Goal 2: Load symbol list from Mongo
# ---------------------------------------------------------------------

def get_symbols_from_mongo(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return stored symbols sorted alphabetically."""
    _db = db.get_db()
    cursor = _db["symbols"].find({}, {"_id": 0}).sort("symbol", 1)
    if limit:
        cursor = cursor.limit(limit)
    return list(cursor)


def get_symbol_list(prefer_net: bool = False) -> List[Dict[str, Any]]:
    """
    Convenience getter:
      - prefer_net=True: try net, fall back to mongo on error/empty.
      - prefer_net=False: mongo only.
    """
    if prefer_net:
        try:
            symbols = fetch_symbol_list_from_net()
            if symbols:
                return symbols
        except Exception as e:
            logging.warning("Net symbol fetch failed; falling back to Mongo: %s", e)

    return get_symbols_from_mongo()


def get_symbol_name_list() -> List[str]:
    """Retrieves a list of symbol names."""
    return [s['symbol'] for s in get_symbol_list()]


# ---------------------------------------------------------------------
# Goal 3: Fetch historical OHLC for one symbol -> upsert to Mongo
# ---------------------------------------------------------------------

@sleep_and_retry
@limits(calls=1, period=1.0/CPS)
def fetch_daily_ohlc_from_net(symbol: str, recent: bool = False) -> Dict[str, Any]:
    """
    Fetch daily OHLC data from Alpha Vantage TIME_SERIES_DAILY.
    Rate limit is controlled by ALPHAVANTAGE_RPM env var.
    """
    if not ALPHAVANTAGE_KEY:
        raise RuntimeError("ALPHAVANTAGE_KEY not set in environment")

    sym = symbol.upper().strip()
    if not sym:
        raise ValueError("symbol is required")

    outputsize = "compact" if recent else "full"
    url = DAILY_SERIES_URL.format(outputsize=outputsize, symbol=sym, key=ALPHAVANTAGE_KEY)

    response = requests.get(url, timeout=15)
    response.raise_for_status()
    json_data = response.json()

    series = json_data.get("Time Series (Daily)")
    if not series:
        logging.error("No Time Series (Daily) for %s. Response keys: %s", sym, list(json_data.keys()))
        raise RuntimeError(f"'Time Series (Daily)' missing for {sym}")

    days: List[Dict[str, Any]] = []
    for d, rec in series.items():
        open_ = round(float(rec["1. open"]), 4)
        close_ = round(float(rec["4. close"]), 4)
        day = {
            "date": d,
            "open": open_,
            "high": round(float(rec["2. high"]), 4),
            "low": round(float(rec["3. low"]), 4),
            "close": close_,
            "volume": int(rec["5. volume"]),
            "midpoint": round((open_ + close_) / 2, 4),
        }
        days.append(day)

    # Sort oldest-first
    days.sort(key=lambda x: x["date"])

    return {"symbol": sym, "days": days}


def upsert_historical_to_mongo(symbol: str, days: List[Dict[str, Any]]) -> None:
    """
    Store full historical days in historical_prices,
    plus a recent slice in historical_prices_recent.
    """
    sym = symbol.upper().strip()
    if not sym:
        raise ValueError("symbol is required")
    
    _db = db.get_db()
    _prices = _db["historical_prices"]
    _prices_recent = _db["historical_prices_recent"]

    now = datetime.utcnow().isoformat()
    
    # Update Full History
    full_doc = {"symbol": sym, "days": days, "last_updated": now}
    _prices.update_one({"symbol": sym}, {"$set": full_doc}, upsert=True)

    # Update Recent History (Used for scanning)
    recent_days = days[-RECENT_TRADING_DAYS:] if days else []
    recent_doc = {"symbol": sym, "days": recent_days, "last_updated": now}
    _prices_recent.update_one({"symbol": sym}, {"$set": recent_doc}, upsert=True)


def refresh_historical_for_symbol(symbol: str, recent: bool = False) -> Dict[str, Any]:
    """
    Fetch OHLC from net and upsert to Mongo.
    """
    data = fetch_daily_ohlc_from_net(symbol, recent=recent)
    days = data.get("days", [])
    if not days:
        raise RuntimeError(f"No historical days returned for {symbol}")

    upsert_historical_to_mongo(data["symbol"], days)

    return {
        "symbol": data["symbol"],
        "num_days": len(days),
        "first_date": days[0]["date"],
        "last_date": days[-1]["date"],
        "last_updated": datetime.utcnow().isoformat(),
    }


@sleep_and_retry
@limits(calls=1, period=1.0/CPS)
def fetch_overview_from_net(symbol: str) -> Dict[str, Any]:
    """
    Fetch company overview data (Sector, Industry, MarketCap, etc.) from Alpha Vantage.
    """
    if not ALPHAVANTAGE_KEY:
        raise RuntimeError("ALPHAVANTAGE_KEY not set in environment")

    sym = symbol.upper().strip()
    url = OVERVIEW_URL.format(symbol=sym, key=ALPHAVANTAGE_KEY)

    response = requests.get(url, timeout=15)
    response.raise_for_status()
    json_data = response.json()
    
    if not json_data or "Symbol" not in json_data:
        logging.error("No overview data for %s. Response: %s", sym, json_data)
        return {}

    return json_data


def upsert_overview_to_mongo(symbol: str, overview: Dict[str, Any]) -> None:
    """
    Store company overview metadata in the symbol_overviews collection.
    """
    sym = symbol.upper().strip()
    if not sym:
        raise ValueError("symbol is required")
    
    _db = db.get_db()
    _overviews = _db["symbol_overviews"]

    overview["symbol"] = sym
    overview["last_updated"] = datetime.utcnow().isoformat()
    
    _overviews.update_one({"symbol": sym}, {"$set": overview}, upsert=True)


def get_overview_from_mongo(symbol: str) -> Dict[str, Any]:
    """
    Load company overview for a symbol from MongoDB.
    """
    sym = symbol.upper().strip()
    _db = db.get_db()
    doc = _db["symbol_overviews"].find_one({"symbol": sym}, {"_id": 0})
    return doc or {}


def get_historical_from_mongo(symbol: str, recent: bool = False) -> List[Dict[str, Any]]:
    """
    Load historical data for a symbol from MongoDB.
    """
    sym = symbol.upper().strip()
    if not sym:
        raise ValueError("symbol is required")

    _db = db.get_db()
    col = _db["historical_prices_recent"] if recent else _db["historical_prices"]
    
    doc = col.find_one({"symbol": sym}, {"_id": 0, "days": 1})
    return (doc or {}).get("days", [])