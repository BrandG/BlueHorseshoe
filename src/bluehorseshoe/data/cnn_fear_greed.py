"""
cnn_fear_greed.py

Fetch CNN Fear & Greed Index data from CNN's undocumented API.
Provides composite market sentiment (7 indicators) for regime analysis.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

CNN_FG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def fetch_cnn_history(days: int = 90) -> List[Dict[str, Any]]:
    """Fetch CNN Fear & Greed historical scores.

    Args:
        days: Number of recent days to return.

    Returns:
        List of dicts with keys: date, score.
        Empty list on any failure.
    """
    try:
        resp = requests.get(CNN_FG_URL, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        raw = payload.get("fear_and_greed_historical", {}).get("data", [])
        if not raw:
            logger.warning("CNN F&G: Response contained no historical data")
            return []

        rows: List[Dict[str, Any]] = []
        for entry in raw:
            try:
                from datetime import datetime, timezone
                ts_ms = entry["x"]
                dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
                rows.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "score": float(entry["y"]),
                })
            except (KeyError, TypeError, ValueError):
                continue

        return rows[-days:] if len(rows) > days else rows

    except Exception:  # pylint: disable=broad-except
        logger.warning("CNN F&G: Failed to fetch data", exc_info=True)
        return []


def _classify_rating(score: float) -> str:
    """Classify a 0-100 score into CNN's sentiment buckets."""
    if score <= 24:
        return "Extreme Fear"
    if score <= 44:
        return "Fear"
    if score <= 55:
        return "Neutral"
    if score <= 74:
        return "Greed"
    return "Extreme Greed"


def get_cnn_snapshot(target_date: str) -> Optional[Dict[str, Any]]:
    """Build a CNN Fear & Greed snapshot for the given target date.

    Calls fetch_cnn_history(), finds the row matching target_date
    (or the most recent row before it), and computes derived metrics.

    Args:
        target_date: Date string in YYYY-MM-DD format.

    Returns:
        Dict with keys: score, change_1d, sma_20, percentile_90d, rating.
        None if data is unavailable.
    """
    history = fetch_cnn_history(days=120)  # extra buffer for SMA-20
    if not history:
        return None

    # Find row matching target_date or most recent before it
    idx = None
    for i in range(len(history) - 1, -1, -1):
        if history[i]["date"] <= target_date:
            idx = i
            break

    if idx is None:
        logger.warning("CNN F&G: No data on or before %s", target_date)
        return None

    row = history[idx]
    score = row["score"]

    # 1-day change
    change_1d = 0.0
    if idx >= 1:
        prev_score = history[idx - 1]["score"]
        if prev_score > 0:
            change_1d = ((score - prev_score) / prev_score) * 100.0

    # 20-day SMA
    sma_start = max(0, idx - 19)
    sma_window = [h["score"] for h in history[sma_start:idx + 1]]
    sma_20 = sum(sma_window) / len(sma_window)

    # 90-day percentile rank
    pct_start = max(0, idx - 89)
    pct_window = sorted(h["score"] for h in history[pct_start:idx + 1])
    rank = sum(1 for v in pct_window if v <= score)
    percentile_90d = (rank / len(pct_window)) * 100.0

    rating = _classify_rating(score)

    return {
        "score": round(score, 1),
        "change_1d": round(change_1d, 2),
        "sma_20": round(sma_20, 1),
        "percentile_90d": round(percentile_90d, 1),
        "rating": rating,
    }
