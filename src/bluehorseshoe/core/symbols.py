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
from requests.exceptions import RequestException
from ratelimit import limits, sleep_and_retry
from pymongo import UpdateOne
from pymongo.results import BulkWriteResult

# Database instances are now passed as parameters instead of using global singletons

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------

ALPHAVANTAGE_KEY = os.environ.get("ALPHAVANTAGE_KEY", "")

# Rate Limit Configuration
# Default to 5 calls/sec (Premium Tier standard) if not set.
CPS = int(os.environ.get("ALPHAVANTAGE_CPS", "2"))

LISTING_STATUS_URL = "https://www.alphavantage.co/query?function=LISTING_STATUS&apikey={key}"
DAILY_SERIES_URL = (
    "https://www.alphavantage.co/query"
    "?function=TIME_SERIES_DAILY_ADJUSTED"
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

NEWS_SENTIMENT_URL = (
    "https://www.alphavantage.co/query"
    "?function=NEWS_SENTIMENT"
    "&tickers={tickers}"
    "&apikey={key}"
)

RECENT_TRADING_DAYS = int(os.environ.get("RECENT_TRADING_DAYS", "240"))

INVALID_SYMBOLS_FILE = "/workspaces/BlueHorseshoe/src/historical_data/invalid_symbols.txt"

def get_invalid_symbols() -> set[str]:
    """Load the list of invalid symbols from the blacklist file."""
    if not os.path.exists(INVALID_SYMBOLS_FILE):
        return set()
    try:
        with open(INVALID_SYMBOLS_FILE, "r", encoding="utf-8") as f:
            return {line.strip().upper() for line in f if line.strip()}
    except OSError as e:
        logging.error("Error reading invalid symbols file: %s", e)
        return set()

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

    invalid_symbols = get_invalid_symbols()
    symbols: List[Dict[str, str]] = []
    for row in rows:
        sym = (row.get("symbol") or "").replace("/", "")

        # Group conditions for readability and to satisfy linting
        is_active = row.get("status") == "Active"
        is_correct_exchange = row.get("exchange") in {"NYSE", "NASDAQ", "NYSE ARCA", "NYSE MKT", "AMEX"}
        is_correct_asset = row.get("assetType") in {"Stock", "ETF"}
        is_valid_sym = sym and "-" not in sym and sym.upper() not in invalid_symbols

        if is_active and is_correct_exchange and is_correct_asset and is_valid_sym:
            symbols.append({
                "symbol": sym, 
                "name": row.get("name", ""),
                "exchange": row.get("exchange", "Unknown")
            })

    return symbols


def upsert_symbols_to_mongo(symbols: Iterable[Dict[str, Any]], database=None) -> int:
    """
    Upsert symbol documents into MongoDB.

    Args:
        symbols: Iterable of symbol dictionaries to upsert.
        database: MongoDB database instance. Required.
    """
    if database is None:
        raise ValueError("database parameter is required for upsert_symbols_to_mongo")

    _symbols_col = database["symbols"]

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


def refresh_symbols(database=None) -> Dict[str, Any]:
    """
    Fetch symbols from net and store in MongoDB.

    Args:
        database: MongoDB database instance. Required.
    """
    if database is None:
        raise ValueError("database parameter is required for refresh_symbols")

    symbols = fetch_symbol_list_from_net()
    if not symbols:
        return {"status": "empty", "count": 0, "symbol_count": 0, "sample": []}

    count = upsert_symbols_to_mongo(symbols, database=database)

    return {
        "status": "ok",
        "count": count,
        "symbol_count": len(symbols),
        "sample": symbols[:5],
    }


# ---------------------------------------------------------------------
# Goal 2: Load symbol list from Mongo
# ---------------------------------------------------------------------

def get_symbols_from_mongo(database=None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Return stored symbols sorted alphabetically.

    Args:
        database: MongoDB database instance. Required.
        limit: Optional limit on number of symbols to return.

    Returns:
        List of symbol dictionaries.
    """
    if database is None:
        raise ValueError("database parameter is required for get_symbols_from_mongo")

    cursor = database["symbols"].find({}, {"_id": 0}).sort("symbol", 1)
    if limit:
        cursor = cursor.limit(limit)
    return list(cursor)


def get_symbol_list(database=None, prefer_net: bool = False) -> List[Dict[str, Any]]:
    """
    Convenience getter:
      - prefer_net=True: try net, fall back to mongo on error/empty.
      - prefer_net=False: mongo only.

    Args:
        database: Optional MongoDB database instance. If None, uses legacy global singleton.
        prefer_net: If True, tries to fetch from network first.

    Returns:
        List of symbol dictionaries.
    """
    invalid_symbols = get_invalid_symbols()
    symbols = []
    if prefer_net:
        try:
            symbols = fetch_symbol_list_from_net()
        except (RequestException, RuntimeError) as e:
            logging.warning("Net symbol fetch failed; falling back to Mongo: %s", e)

    if not symbols:
        symbols = get_symbols_from_mongo(database=database)

    return [s for s in symbols if s["symbol"].upper() not in invalid_symbols]


def get_symbol_name_list(database=None) -> List[str]:
    """
    Retrieves a list of symbol names.

    Args:
        database: Optional MongoDB database instance. If None, uses legacy global singleton.

    Returns:
        List of symbol strings.
    """
    return [s['symbol'] for s in get_symbol_list(database=database)]


# ---------------------------------------------------------------------
# Goal 3: Fetch historical OHLC for one symbol -> upsert to Mongo
# ---------------------------------------------------------------------

def _parse_adjusted_day(date_str: str, record: Dict[str, Any]) -> Dict[str, Any]:
    """Helper to parse a single day record with split adjustments."""
    raw_close = float(record.get("4. close", 0))
    adj_close = float(record.get("5. adjusted close", 0))

    factor = adj_close / raw_close if raw_close != 0 else 1.0

    open_ = round(float(record.get("1. open", 0)) * factor, 4)
    close_ = round(adj_close, 4)

    return {
        "date": date_str,
        "open": open_,
        "high": round(float(record.get("2. high", 0)) * factor, 4),
        "low": round(float(record.get("3. low", 0)) * factor, 4),
        "close": close_,
        "volume": int(record.get("6. volume", 0)),
        "midpoint": round((open_ + close_) / 2, 4),
    }

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

    print(f"DEBUG: Fetched {len(series)} days for {sym} (outputsize={outputsize})")
    days: List[Dict[str, Any]] = []
    for d, rec in series.items():
        days.append(_parse_adjusted_day(d, rec))

    # Sort oldest-first
    days.sort(key=lambda x: x["date"])

    return {"symbol": sym, "days": days}


def upsert_historical_to_mongo(symbol: str, days: List[Dict[str, Any]], database=None) -> None:
    """
    Store full historical days in historical_prices,
    plus a recent slice in historical_prices_recent.
    Merges with existing data to prevent truncation.

    Args:
        symbol: Stock symbol.
        days: List of OHLCV day dictionaries.
        database: MongoDB database instance. Required.
    """
    sym = symbol.upper().strip()
    if not sym:
        raise ValueError("symbol is required")

    if database is None:
        raise ValueError("database parameter is required for upsert_historical_to_mongo")

    _prices = database["historical_prices"]
    _prices_recent = database["historical_prices_recent"]

    now = datetime.utcnow().isoformat()

    # Load existing days to merge
    existing_doc = _prices.find_one({"symbol": sym}, {"days": 1})
    if existing_doc and "days" in existing_doc:
        import pandas as pd
        df_existing = pd.DataFrame(existing_doc["days"])
        df_new = pd.DataFrame(days)
        # Combine and drop duplicates based on date
        df_merged = pd.concat([df_existing, df_new]).drop_duplicates(subset=['date'])
        df_merged = df_merged.sort_values(by='date').reset_index(drop=True)
        merged_days = df_merged.to_dict(orient='records')
    else:
        merged_days = days

    # Update Full History
    full_doc = {"symbol": sym, "days": merged_days, "last_updated": now}
    _prices.update_one({"symbol": sym}, {"$set": full_doc}, upsert=True)

    # Update Recent History (Used for scanning)
    recent_days = merged_days[-RECENT_TRADING_DAYS:] if merged_days else []
    recent_doc = {"symbol": sym, "days": recent_days, "last_updated": now}
    _prices_recent.update_one({"symbol": sym}, {"$set": recent_doc}, upsert=True)


def refresh_historical_for_symbol(symbol: str, recent: bool = False, database=None) -> Dict[str, Any]:
    """
    Fetch OHLC from net and upsert to Mongo.

    Args:
        symbol: Stock symbol.
        recent: If True, fetch compact data; if False, fetch full history.
        database: MongoDB database instance. Required.
    """
    if database is None:
        raise ValueError("database parameter is required for refresh_historical_for_symbol")

    data = fetch_daily_ohlc_from_net(symbol, recent=recent)
    days = data.get("days", [])
    if not days:
        raise RuntimeError(f"No historical days returned for {symbol}")

    upsert_historical_to_mongo(data["symbol"], days, database=database)

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


def upsert_overview_to_mongo(symbol: str, overview: Dict[str, Any], database=None) -> None:
    """
    Store company overview metadata in the symbol_overviews collection.

    Args:
        symbol: Stock symbol.
        overview: Overview data dictionary from Alpha Vantage.
        database: MongoDB database instance. Required.
    """
    sym = symbol.upper().strip()
    if not sym:
        raise ValueError("symbol is required")

    if database is None:
        raise ValueError("database parameter is required for upsert_overview_to_mongo")

    _overviews = database["symbol_overviews"]

    overview["symbol"] = sym
    overview["last_updated"] = datetime.utcnow().isoformat()

    _overviews.update_one({"symbol": sym}, {"$set": overview}, upsert=True)


def get_overview_from_mongo(symbol: str, database=None) -> Dict[str, Any]:
    """
    Load company overview for a symbol from MongoDB.

    Args:
        symbol: Stock symbol.
        database: MongoDB database instance. Required.
    """
    if database is None:
        raise ValueError("database parameter is required for get_overview_from_mongo")

    sym = symbol.upper().strip()
    doc = database["symbol_overviews"].find_one({"symbol": sym}, {"_id": 0})
    return doc or {}


@sleep_and_retry
@limits(calls=1, period=1.0/CPS)
def fetch_news_sentiment_from_net(tickers: str) -> Dict[str, Any]:
    """
    Fetch news sentiment for one or more tickers.
    """
    if not ALPHAVANTAGE_KEY:
        raise RuntimeError("ALPHAVANTAGE_KEY not set in environment")

    url = NEWS_SENTIMENT_URL.format(tickers=tickers, key=ALPHAVANTAGE_KEY)
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    return response.json()


def upsert_news_sentiment_to_mongo(symbol: str, news_data: Dict[str, Any], database=None) -> None:
    """
    Store news sentiment feed in the symbol_news collection.

    Args:
        symbol: Stock symbol.
        news_data: News sentiment data from Alpha Vantage.
        database: MongoDB database instance. Required.
    """
    if database is None:
        raise ValueError("database parameter is required for upsert_news_sentiment_to_mongo")

    sym = symbol.upper().strip()
    _news = database["symbol_news"]

    # We store the feed as a single document for the ticker
    doc = {
        "symbol": sym,
        "feed": news_data.get("feed", []),
        "last_updated": datetime.utcnow().isoformat()
    }
    _news.update_one({"symbol": sym}, {"$set": doc}, upsert=True)


def get_news_sentiment_from_mongo(symbol: str, database=None) -> List[Dict[str, Any]]:
    """
    Load news sentiment feed for a symbol from MongoDB.

    Args:
        symbol: Stock symbol.
        database: MongoDB database instance. Required.
    """
    if database is None:
        raise ValueError("database parameter is required for get_news_sentiment_from_mongo")

    sym = symbol.upper().strip()
    doc = database["symbol_news"].find_one({"symbol": sym}, {"_id": 0})
    return (doc or {}).get("feed", [])


def _normalize_target_date(target_date: str | date) -> datetime | None:
    """Helper to convert various date inputs to datetime."""
    if isinstance(target_date, str):
        try:
            return datetime.strptime(target_date, "%Y-%m-%d")
        except ValueError:
            return None
    if isinstance(target_date, datetime):
        return target_date
    if isinstance(target_date, date):
        return datetime.combine(target_date, datetime.min.time())
    return None


def get_sentiment_score(symbol: str, target_date: str | date, database=None) -> float:
    """
    Calculates an average sentiment score for a symbol up to a target date.
    Lookback is 7 days.

    Args:
        symbol: Stock symbol.
        target_date: Target date for sentiment analysis.
        database: MongoDB database instance. Required.
    """
    if database is None:
        raise ValueError("database parameter is required for get_sentiment_score")

    feed = get_news_sentiment_from_mongo(symbol, database=database)
    target_dt = _normalize_target_date(target_date)

    if not feed or not target_dt:
        return 0.0

    scores = []
    symbol_upper = symbol.upper()

    for item in feed:
        try:
            pub_dt = datetime.strptime(item["time_published"], "%Y%m%dT%H%M%S")
        except (ValueError, KeyError):
            continue

        delta = target_dt - pub_dt
        if 0 <= delta.days <= 7:
            for ts in item.get("ticker_sentiment", []):
                if ts.get("ticker") == symbol_upper:
                    try:
                        scores.append(float(ts.get("ticker_sentiment_score", 0.0)))
                    except (ValueError, TypeError):
                        pass

    return sum(scores) / len(scores) if scores else 0.0


def get_historical_from_mongo(symbol: str, recent: bool = False, database=None) -> List[Dict[str, Any]]:
    """
    Load historical data for a symbol from MongoDB.

    Args:
        symbol: Stock symbol.
        recent: If True, load from recent prices collection; if False, load from full history.
        database: MongoDB database instance. Required.
    """
    if database is None:
        raise ValueError("database parameter is required for get_historical_from_mongo")

    sym = symbol.upper().strip()
    if not sym:
        raise ValueError("symbol is required")

    col = database["historical_prices_recent"] if recent else database["historical_prices"]

    doc = col.find_one({"symbol": sym}, {"_id": 0, "days": 1})
    return (doc or {}).get("days", [])
