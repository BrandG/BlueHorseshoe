# src/bluehorseshoe/service.py

from datetime import date
from typing import Dict, Any


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

