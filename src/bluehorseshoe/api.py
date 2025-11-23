# src/bluehorseshoe/api.py
from fastapi import FastAPI, Query, HTTPException, Body
from datetime import date
from typing import Optional, Dict, Any
import os
from pymongo import MongoClient
from . import service
from .symbols import refresh_symbols, refresh_historical_for_symbol, get_historical_from_mongo

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

@app.post("/trigger")
@app.get("/trigger")
def trigger_action(action: str = Query(..., description="Name of the action to trigger"), 
                  payload: Optional[Dict[str, Any]] = Body(default=None)):
    """
    Flexible endpoint for triggering backend actions during development.
    
    This endpoint allows you to trigger custom backend actions without needing to
    create specific endpoints for each temporary action. Perfect for development
    and testing scenarios where the action logic changes frequently.
    
    Args:
        action: String identifier for the action to trigger
        payload: Optional JSON payload with parameters for the action
        
    Examples:
        POST /trigger?action=test_analysis
        POST /trigger?action=debug_symbols {"symbol": "AAPL", "verbose": true}
        POST /trigger?action=cleanup_data {"days_old": 30}
    """
    try:
        result = service.handle_trigger_action(action, payload or {})
        return {
            "status": "success",
            "action": action,
            "result": result
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Action '{action}' failed: {str(e)}")

@app.post("/load_symbols")
@app.get("/load_symbols")
def load_symbols():
    return refresh_symbols()

@app.post("/load_symbol/{symbol}")
@app.get("/load_symbol/{symbol}")
def load_symbol(symbol: str, recent: bool = False):
    return refresh_historical_for_symbol(symbol, recent=recent)

@app.get("/historicals/{symbol}")
def historicals(symbol: str, recent: bool = False):
    return {"symbol": symbol, "days": get_historical_from_mongo(symbol, recent=recent)}
