"""
symbols.py (v1.3)

Core utilities for:
1) Fetching active symbols from Alpha Vantage and upserting to MongoDB.
2) Loading symbols from MongoDB.
3) Fetching historical OHLC data for one symbol from Alpha Vantage and saving to DuckDB.
4) Loading historical OHLC data from DuckDB.
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

from bluehorseshoe.core.invalid_symbols import load_invalid_symbol_set
from bluehorseshoe.core.symbol_repository import (
    backfill_missing_overviews,
    get_overview,
    get_symbols,
    upsert_overview,
    upsert_symbols,
)

def get_invalid_symbols() -> set[str]:
    """Load the list of invalid symbols from the blacklist file."""
    return load_invalid_symbol_set()

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
    return upsert_symbols(symbols, database=database)


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

def get_symbols_from_mongo(database=None, limit: Optional[int] = None, active_only: bool = False) -> List[Dict[str, Any]]:
    """
    Return stored symbols sorted alphabetically.

    Args:
        database: MongoDB database instance. Required.
        limit: Optional limit on number of symbols to return.
        active_only: If True, only return symbols with active=True.

    Returns:
        List of symbol dictionaries.
    """
    if database is None:
        raise ValueError("database parameter is required for get_symbols_from_mongo")
    return get_symbols(database=database, limit=limit, active_only=active_only)


def get_symbol_list(database=None, prefer_net: bool = False, active_only: bool = False) -> List[Dict[str, Any]]:
    """
    Convenience getter:
      - prefer_net=True: try net, fall back to mongo on error/empty.
      - prefer_net=False: mongo only.

    Args:
        database: Optional MongoDB database instance. If None, uses legacy global singleton.
        prefer_net: If True, tries to fetch from network first.
        active_only: If True, only return symbols with active=True.

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
        symbols = get_symbols_from_mongo(database=database, active_only=active_only)

    return [s for s in symbols if s["symbol"].upper() not in invalid_symbols]


def get_symbol_name_list(database=None, active_only: bool = False) -> List[str]:
    """
    Retrieves a list of symbol names.

    Args:
        database: Optional MongoDB database instance. If None, uses legacy global singleton.
        active_only: If True, only return symbols with active=True.

    Returns:
        List of symbol strings.
    """
    return [s['symbol'] for s in get_symbol_list(database=database, active_only=active_only)]


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


def upsert_historical(symbol: str, days: List[Dict[str, Any]], store=None, **_kwargs) -> None:
    """
    Save historical OHLCV days to DuckDB, merging with existing data.

    Args:
        symbol: Stock symbol.
        days: List of OHLCV day dictionaries.
        store: DuckDBStore instance. Required.
    """
    sym = symbol.upper().strip()
    if not sym:
        raise ValueError("symbol is required")

    if store is None:
        raise ValueError("store parameter is required for upsert_historical")

    import pandas as pd  # pylint: disable=import-outside-toplevel
    _df = pd.DataFrame(days)
    store.save_symbol(sym, _df, full_name=sym)


def refresh_historical_for_symbol(symbol: str, recent: bool = False, database=None, store=None) -> Dict[str, Any]:
    """
    Fetch OHLC from net and save to DuckDB.

    Args:
        symbol: Stock symbol.
        recent: If True, fetch compact data; if False, fetch full history.
        database: MongoDB database instance (unused, kept for caller compatibility).
        store: DuckDBStore instance. Required.
    """
    if store is None:
        raise ValueError("store parameter is required for refresh_historical_for_symbol")

    data = fetch_daily_ohlc_from_net(symbol, recent=recent)
    days = data.get("days", [])
    if not days:
        raise RuntimeError(f"No historical days returned for {symbol}")

    upsert_historical(data["symbol"], days, store=store)

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
    if database is None:
        raise ValueError("database parameter is required for upsert_overview_to_mongo")
    upsert_overview(symbol, overview, database=database)


def get_overview_from_mongo(symbol: str, database=None) -> Dict[str, Any]:
    """
    Load company overview for a symbol from MongoDB.

    Args:
        symbol: Stock symbol.
        database: MongoDB database instance. Required.
    """
    if database is None:
        raise ValueError("database parameter is required for get_overview_from_mongo")
    return get_overview(symbol, database=database)


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


def get_sentiment_score_with_count(
    symbol: str, target_date: str | date, database=None
) -> tuple[float, int]:
    """
    Calculates an average sentiment score for a symbol up to a target date.
    Lookback is 7 days.

    Args:
        symbol: Stock symbol.
        target_date: Target date for sentiment analysis.
        database: MongoDB database instance. Required.

    Returns:
        Tuple of (average_score, article_count).
    """
    if database is None:
        raise ValueError("database parameter is required for get_sentiment_score_with_count")

    feed = get_news_sentiment_from_mongo(symbol, database=database)
    target_dt = _normalize_target_date(target_date)

    if not feed or not target_dt:
        return 0.0, 0

    scores: List[float] = []
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

    avg = sum(scores) / len(scores) if scores else 0.0
    return avg, len(scores)


def get_sentiment_score(symbol: str, target_date: str | date, database=None) -> float:
    """
    Calculates an average sentiment score for a symbol up to a target date.
    Lookback is 7 days.

    Args:
        symbol: Stock symbol.
        target_date: Target date for sentiment analysis.
        database: MongoDB database instance. Required.
    """
    score, _ = get_sentiment_score_with_count(symbol, target_date, database=database)
    return score


def save_sentiment_snapshots(
    snapshots: List[Dict[str, Any]], database=None
) -> int:
    """
    Bulk upsert daily sentiment snapshots to MongoDB.

    Each snapshot: {"symbol": str, "date": str, "score": float,
                    "article_count": int, "source": str (optional, default "alphavantage")}
    Unique index on (symbol, date, source). Returns number of upserted/modified docs.

    Args:
        snapshots: List of snapshot dicts.
        database: MongoDB database instance. Required.
    """
    if not snapshots:
        return 0

    if database is None:
        raise ValueError("database parameter is required for save_sentiment_snapshots")

    col = database["sentiment_snapshots"]

    # Migrate index from (symbol, date) to (symbol, date, source)
    try:
        col.drop_index("symbol_1_date_1")
    except Exception:  # pylint: disable=broad-except
        pass  # Index may not exist yet
    col.create_index([("symbol", 1), ("date", 1), ("source", 1)], unique=True)

    ops = [
        UpdateOne(
            {
                "symbol": s["symbol"],
                "date": s["date"],
                "source": s.get("source", "alphavantage"),
            },
            {"$set": {
                "score": s["score"],
                "article_count": s["article_count"],
                "source": s.get("source", "alphavantage"),
                "updated_at": datetime.utcnow(),
            }},
            upsert=True,
        )
        for s in snapshots
    ]

    result: BulkWriteResult = col.bulk_write(ops, ordered=False)
    return (result.upserted_count or 0) + (result.modified_count or 0)


def get_sentiment_history(
    symbol: str, limit: int = 30, database=None, source: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Query last N sentiment snapshots for a symbol, newest first.

    Args:
        symbol: Stock symbol.
        limit: Maximum number of snapshots to return.
        database: MongoDB database instance. Required.
        source: Optional provider filter (e.g. "alphavantage", "tiingo").
    """
    if database is None:
        raise ValueError("database parameter is required for get_sentiment_history")

    col = database["sentiment_snapshots"]
    query: Dict[str, Any] = {"symbol": symbol.upper().strip()}
    if source:
        query["source"] = source
    cursor = (
        col.find(query, {"_id": 0})
        .sort("date", -1)
        .limit(limit)
    )
    return list(cursor)


def backfill_overviews(database, limit=None):
    """
    Fetch AV OVERVIEW for symbols missing from symbol_overviews.
    Skips NYSE ARCA (mostly ETFs — AV has no overview for them).
    """
    return backfill_missing_overviews(
        database=database,
        fetch_overview=fetch_overview_from_net,
        upsert_overview_fn=lambda symbol, overview: upsert_overview_to_mongo(symbol, overview, database=database),
        limit=limit,
    )


def get_historical(symbol: str, store=None, **_kwargs) -> List[Dict[str, Any]]:
    """
    Load historical OHLCV data for a symbol from DuckDB.

    Args:
        symbol: Stock symbol.
        store: DuckDBStore instance. Required.
    """
    if store is None:
        raise ValueError("store parameter is required for get_historical")

    sym = symbol.upper().strip()
    if not sym:
        raise ValueError("symbol is required")

    data = store.load_symbol_dict(sym)
    return data.get("days", []) if data else []
