"""
Core service module for handling business logic and trade operations.
"""
import time
from datetime import date, datetime
from typing import Dict, Any, List, Optional
import os

import pandas as pd  # Added pandas import
from pymongo.errors import PyMongoError
from requests.exceptions import RequestException

from .models import DailyReport, Candidate
from .database import db
from bluehorseshoe.analysis import legacy_strategy as strategy
from .symbols import (
    get_symbols_from_mongo,
    fetch_overview_from_net,
    upsert_overview_to_mongo,
    get_overview_from_mongo
)

def run_backtest(symbol: str, start: date, end: date, strategy_name: str = "baseline") -> Dict[str, Any]:
    """
    Placeholder backtest implementation.
    """
    return {
        "status": "not_implemented",
        "symbol": symbol,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "strategy": strategy_name,
        "summary": {
            "trades": 0,
            "total_return": 0.0,
            "cagr": 0.0,
            "max_drawdown": 0.0,
        },
    }

def handle_trigger_action(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flexible action handler for development triggers.
    """
    _db = db.get_db()

    if action == "hello":
        name = payload.get("name", "World")
        return {"message": f"Hello, {name}!"}

    elif action == "test_db":
        try:
            collections = _db.list_collection_names()
            stats = {}
            for col_name in collections:
                stats[col_name] = _db[col_name].count_documents({})
            return {
                "collections": collections,
                "document_counts": stats
            }
        except PyMongoError as e:
            return {"error": f"Database test failed: {e}"}

    elif action == "backfill_overviews":
        limit = payload.get("limit", 10)
        symbols = get_symbols_from_mongo(limit=limit)
        count = 0
        for s in symbols:
            sym = s["symbol"]
            # Check if already exists
            if not get_overview_from_mongo(sym):
                try:
                    ov = fetch_overview_from_net(sym)
                    if ov:
                        upsert_overview_to_mongo(sym, ov)
                        count += 1
                        time.sleep(0.2) # Small delay
                except (RequestException, PyMongoError, RuntimeError) as e:
                    print(f"Failed to fetch overview for {sym}: {e}")
        return {"status": "ok", "backfilled_count": count}

    else:
        return {
            "error": f"Unknown action: {action}",
            "available_actions": ["hello", "test_db", "backfill_overviews"],
        }

def run_daily() -> Dict[str, Any]:
    """
    Main Daily Scan Routine.
    """
    # 1. Determine date
    report_date = date.today().isoformat()

    # 2. Load universe data EFFICIENTLY
    universe_data = load_universe_data()

    if not universe_data:
        return {"error": "No data found for scanning"}

    # Extract the actual data date from the first record found
    data_date = universe_data[0].get("date", report_date)

    # 3. Vectorized Scoring with Pandas
    # Convert the list of dicts to a DataFrame
    df = pd.DataFrame(universe_data)

    # Vectorized Calculations (Column-wise math)
    # This replaces the row-by-row loop and is significantly faster
    df['range'] = df['high'] - df['low']
    df['body'] = (df['close'] - df['open']).abs()

    # Handle division by zero for stability
    # If range is 0, set stability to 0, otherwise body/range
    df['stability'] = 0.0
    mask = df['range'] > 0
    df.loc[mask, 'stability'] = df.loc[mask, 'body'] / df.loc[mask, 'range']

    # Simple score: Volatility (range) is good, Body is bad (uncertainty)
    df['score'] = df['range'] - df['body']

    # 4. Sort and pick top 10
    # sort_values is highly optimized
    top_df = df.sort_values(by='score', ascending=False).head(10)

    # Convert back to Candidate objects for the report
    candidates: List[Candidate] = []
    for _, row in top_df.iterrows():
        cand = Candidate(
            symbol=row['symbol'],
            score=row['score'],
            open=row['open'],
            high=row['high'],
            low=row['low'],
            close=row['close'],
            volume=row['volume'],
            range=row['range'],
            body=row['body'],
            stability=row['stability'],
        )
        candidates.append(cand)

    selected = {}
    if candidates:
        selected = {
            "symbol": candidates[0].symbol,
            "score": candidates[0].score,
        }

    report = DailyReport(
        report_date=report_date,
        data_date=data_date,
        strategy="baseline",
        version="1.1",
        universe_size=len(universe_data),
        top_candidates=[c.to_dict() for c in candidates],
        selected=selected,
    )

    return report.to_dict()


def _parse_date_str(d: str) -> str:
    if not d: return ""
    return str(d).strip()[:10]


def load_universe_data(
    data_date: Optional[str] = None,
    min_price: float = 1.0,
) -> List[Dict[str, Any]]:
    """
    Load OHLCV bars for the universe using an Efficient Aggregation Pipeline.

    This replaces the 'Look-Ahead' / 'N+1 Query' loop.
    """
    _db = db.get_db()

    # 1. If no date provided, find the most recent date in the prices collection
    if data_date is None:
        sample = _db["historical_prices_recent"].find_one({}, {"days": {"$slice": -1}})
        if not sample or not sample.get("days"):
            return []
        data_date = _parse_date_str(sample["days"][0].get("date"))
    else:
        data_date = _parse_date_str(data_date)

    print(f"Loading universe for date: {data_date}")

    # 2. Aggregation Pipeline
    pipeline = [
        # Match only documents that HAVE this date in their days array
        { "$match": { "days.date": data_date } },

        # Project only the specific day we want using $filter
        { "$project": {
            "symbol": 1,
            "day": {
                "$filter": {
                    "input": "$days",
                    "as": "d",
                    "cond": { "$eq": ["$$d.date", data_date] }
                }
            }
        }},

        # The filter returns an array (of 1 element). Unwind it.
        { "$unwind": "$day" },

        # Filter by minimum price
        { "$match": { "day.close": { "$gte": min_price } } },

        # Format the output to be flat
        { "$project": {
            "_id": 0,
            "symbol": 1,
            "date": "$day.date",
            "open": "$day.open",
            "high": "$day.high",
            "low": "$day.low",
            "close": "$day.close",
            "volume": "$day.volume"
        }}
    ]

    # Run the aggregation
    results = list(_db["historical_prices_recent"].aggregate(pipeline))

    return results