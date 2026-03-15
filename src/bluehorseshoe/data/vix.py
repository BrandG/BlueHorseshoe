"""
vix.py

Fetch VIX (CBOE Volatility Index) data from CBOE's free delayed API.
Provides market-wide implied volatility metrics for regime analysis.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

CBOE_VIX_URL = "https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/_VIX.json"


def fetch_vix_history(days: int = 90) -> List[Dict[str, Any]]:
    """Fetch VIX OHLC history from CBOE's free delayed API.

    Args:
        days: Number of recent trading days to return.

    Returns:
        List of dicts with keys: date, open, high, low, close.
        Empty list on any failure.
    """
    try:
        resp = requests.get(CBOE_VIX_URL, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        raw = payload.get("data", [])
        if not raw:
            logger.warning("VIX: CBOE response contained no data")
            return []

        rows: List[Dict[str, Any]] = []
        for entry in raw:
            try:
                rows.append({
                    "date": entry["date"][:10],  # "YYYY-MM-DD"
                    "open": float(entry["open"]),
                    "high": float(entry["high"]),
                    "low": float(entry["low"]),
                    "close": float(entry["close"]),
                })
            except (KeyError, TypeError, ValueError):
                continue

        # Return only the last N days
        return rows[-days:] if len(rows) > days else rows

    except Exception:  # pylint: disable=broad-except
        logger.warning("VIX: Failed to fetch from CBOE", exc_info=True)
        return []


def get_vix_snapshot(target_date: str) -> Optional[Dict[str, Any]]:
    """Build a VIX snapshot for the given target date.

    Calls fetch_vix_history(), finds the row matching target_date
    (or the most recent row before it), and computes derived metrics.

    Args:
        target_date: Date string in YYYY-MM-DD format.

    Returns:
        Dict with keys: close, change_1d, sma_20, percentile_90d, fear_level.
        None if data is unavailable.
    """
    history = fetch_vix_history(days=120)  # extra buffer for SMA-20
    if not history:
        return None

    # Find row matching target_date or most recent before it
    idx = None
    for i in range(len(history) - 1, -1, -1):
        if history[i]["date"] <= target_date:
            idx = i
            break

    if idx is None:
        logger.warning("VIX: No data on or before %s", target_date)
        return None

    row = history[idx]
    vix_close = row["close"]

    # 1-day change
    change_1d = 0.0
    if idx >= 1:
        prev_close = history[idx - 1]["close"]
        if prev_close > 0:
            change_1d = ((vix_close - prev_close) / prev_close) * 100.0

    # 20-day SMA
    sma_start = max(0, idx - 19)
    sma_window = [h["close"] for h in history[sma_start:idx + 1]]
    sma_20 = sum(sma_window) / len(sma_window)

    # 90-day percentile rank
    pct_start = max(0, idx - 89)
    pct_window = sorted(h["close"] for h in history[pct_start:idx + 1])
    rank = sum(1 for v in pct_window if v <= vix_close)
    percentile_90d = (rank / len(pct_window)) * 100.0

    # Fear level buckets
    if vix_close <= 15:
        fear_level = "Low"
    elif vix_close <= 20:
        fear_level = "Moderate"
    elif vix_close <= 30:
        fear_level = "Elevated"
    else:
        fear_level = "High"

    return {
        "close": round(vix_close, 2),
        "change_1d": round(change_1d, 2),
        "sma_20": round(sma_20, 2),
        "percentile_90d": round(percentile_90d, 1),
        "fear_level": fear_level,
    }
