# src/bluehorseshoe/api.py
from fastapi import FastAPI, Query, HTTPException
from datetime import date
from typing import Optional
import os
from pymongo import MongoClient
from . import service
from .globals import get_symbol_list_from_net  # adjust import path
from .service import sync_symbols_to_mongo

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/info")
def info():
    import sys, os
    return {
        "python": sys.version,
        "cwd": os.getcwd(),
        "env": dict(os.environ),
    }

@app.get("/dbcheck")
def dbcheck():
    client = MongoClient(os.environ["MONGO_URI"])
    db = client.get_database("admin")
    return {"ok": db.command("ping")}

@app.get("/backtest")
def backtest(
    symbol: str = Query(..., description="Ticker symbol to backtest, e.g. AAPL"),
    start: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end: date = Query(..., description="End date (YYYY-MM-DD)"),
    strategy: str = Query("baseline", description="Strategy name, e.g. 'baseline' or 'nn_v1'"),
):
    """
    Run a backtest over the given date range for the given symbol.

    For now this is a thin wrapper over service.run_backtest() which returns stub data.
    """
    if start >= end:
        raise HTTPException(status_code=400, detail="start must be before end")

    result = service.run_backtest(symbol=symbol, start=start, end=end, strategy=strategy)
    return result


@app.post("/run_daily")
@app.get("/run_daily")
def run_daily(force: Optional[bool] = Query(False, description="Ignore caches and force a full run")):
    """
    Trigger the daily BlueHorseshoe pipeline.

    In the future, you can:
      - use `force` to bypass cached results
      - kick off more expensive recomputations
    """
    # For now, we just ignore `force` and return stub data.
    result = service.run_daily()
    result["force"] = force
    return result

@app.post("/load_symbols")
@app.get("/load_symbols")
def load_symbols():
    """
    Fetch the symbol list from Alpha Vantage and store it in MongoDB.

    Returns:
        {
            "count": number of symbols inserted/updated,
            "sample": [...]
        }
    """
    try:
        symbols = get_symbol_list_from_net()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch symbols: {e}")

    if not symbols:
        raise HTTPException(status_code=500, detail="Symbol list is empty")

    count = sync_symbols_to_mongo(symbols)

    return {
        "status": "ok",
        "count": count,
        "sample": symbols[:5],  # convenient sanity check
    }
