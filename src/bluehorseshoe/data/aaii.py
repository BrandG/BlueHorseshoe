"""
aaii.py

Fetch AAII (American Association of Individual Investors) Bull/Bear
Sentiment Survey data.  Published every Thursday since 1987, the survey
measures retail investor sentiment and acts as a contrarian indicator —
extreme bullishness often precedes pullbacks, extreme bearishness
precedes rallies.

Primary source : Nasdaq Data Link API (dataset AAII/AAII_SENTIMENT).
Fallback       : Direct Excel download from aaii.com.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import io

import pandas as pd
import requests

from bluehorseshoe.core.config import get_settings

logger = logging.getLogger(__name__)

AAII_EXCEL_URL = "https://www.aaii.com/files/surveys/sentiment.xls"


def _normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure bullish/bearish/neutral are in 0-1 decimal form."""
    for key in ("bullish", "bearish", "neutral"):
        val = row.get(key, 0.0)
        if val is None:
            val = 0.0
        # If value > 1 it's in percentage form (e.g. 38.5) — convert to decimal
        if val > 1:
            row[key] = val / 100.0
        else:
            row[key] = float(val)
    row["bull_bear_spread"] = round((row["bullish"] - row["bearish"]) * 100, 2)
    return row


def fetch_aaii_history(weeks: int = 52) -> List[Dict[str, Any]]:
    """Fetch AAII sentiment survey history.

    Tries Nasdaq Data Link API first (requires NASDAQ_DATA_LINK_API_KEY).
    Falls back to direct Excel download from aaii.com.

    Args:
        weeks: Number of recent weeks to return.

    Returns:
        List of dicts with keys: date, bullish, bearish, neutral,
        bull_bear_spread.  Empty list on failure.
    """
    # --- Primary: Nasdaq Data Link API ---
    try:
        api_key = get_settings().nasdaq_data_link_api_key
    except Exception:  # pylint: disable=broad-except
        api_key = ""

    if api_key:
        try:
            import nasdaqdatalink  # pylint: disable=import-outside-toplevel
            nasdaqdatalink.ApiConfig.api_key = api_key
            df = nasdaqdatalink.get("AAII/AAII_SENTIMENT")
            return _dataframe_to_rows(df, weeks)
        except Exception:  # pylint: disable=broad-except
            logger.warning("AAII: Nasdaq Data Link API failed, trying Excel fallback", exc_info=True)

    # --- Fallback: direct Excel download ---
    try:
        resp = requests.get(AAII_EXCEL_URL, timeout=30)
        resp.raise_for_status()
        buf = io.BytesIO(resp.content)
        # Try openpyxl first (xlsx), fall back to xlrd (xls)
        try:
            df = pd.read_excel(buf, engine="openpyxl")
        except Exception:  # pylint: disable=broad-except
            buf.seek(0)
            df = pd.read_excel(buf, engine="xlrd")
        return _dataframe_to_rows(df, weeks)
    except Exception:  # pylint: disable=broad-except
        logger.warning("AAII: Excel fallback also failed", exc_info=True)
        return []


def _dataframe_to_rows(df: pd.DataFrame, weeks: int) -> List[Dict[str, Any]]:
    """Convert an AAII DataFrame (from any source) into standardized rows."""
    # Normalize column names to lowercase
    df.columns = [str(c).strip().lower() for c in df.columns]

    # Detect date column
    date_col = None
    for candidate in ("date", "reported date", "report date"):
        if candidate in df.columns:
            date_col = candidate
            break
    if date_col is None:
        # Fall back to first column if it looks like dates
        date_col = df.columns[0]

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col])
    df = df.sort_values(date_col).reset_index(drop=True)

    # Detect sentiment columns
    bullish_col = _find_column(df, ["bullish"])
    bearish_col = _find_column(df, ["bearish"])
    neutral_col = _find_column(df, ["neutral"])

    if not bullish_col or not bearish_col:
        logger.warning("AAII: Could not find bullish/bearish columns in data")
        return []

    rows: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        try:
            row = {
                "date": r[date_col].strftime("%Y-%m-%d"),
                "bullish": float(r[bullish_col]) if pd.notna(r[bullish_col]) else 0.0,
                "bearish": float(r[bearish_col]) if pd.notna(r[bearish_col]) else 0.0,
                "neutral": float(r[neutral_col]) if neutral_col and pd.notna(r[neutral_col]) else 0.0,
            }
            row = _normalize_row(row)
            rows.append(row)
        except (TypeError, ValueError):
            continue

    return rows[-weeks:] if len(rows) > weeks else rows


def _find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """Find a column whose name contains one of the candidate substrings."""
    for col in df.columns:
        for cand in candidates:
            if cand in col:
                return col
    return None


def get_aaii_snapshot(target_date: str) -> Optional[Dict[str, Any]]:
    """Build an AAII sentiment snapshot for the given target date.

    Finds the most recent survey on or before target_date, computes:
    - spread_normalized: bull_bear_spread / 50, clamped to [-1, 1]
    - spread_8w_avg: 8-week rolling average of the spread
    - percentile_52w: percentile rank of current spread in the last 52 weeks
    - signal: text classification based on spread thresholds

    Args:
        target_date: Date string in YYYY-MM-DD format.

    Returns:
        Dict with snapshot metrics, or None if data is unavailable.
    """
    history = fetch_aaii_history(weeks=60)  # extra buffer for 8-week avg + percentile
    if not history:
        return None

    # Find the most recent row on or before target_date
    idx = None
    for i in range(len(history) - 1, -1, -1):
        if history[i]["date"] <= target_date:
            idx = i
            break

    if idx is None:
        logger.warning("AAII: No data on or before %s", target_date)
        return None

    row = history[idx]
    spread = row["bull_bear_spread"]

    # Normalized spread: spread / 50, clamped [-1, 1]
    spread_normalized = max(-1.0, min(1.0, spread / 50.0))

    # 8-week rolling average
    start_8w = max(0, idx - 7)
    window_8w = [history[i]["bull_bear_spread"] for i in range(start_8w, idx + 1)]
    spread_8w_avg = sum(window_8w) / len(window_8w)

    # 52-week percentile rank
    start_52w = max(0, idx - 51)
    window_52w = sorted(history[i]["bull_bear_spread"] for i in range(start_52w, idx + 1))
    rank = sum(1 for v in window_52w if v <= spread)
    percentile_52w = (rank / len(window_52w)) * 100.0

    # Signal classification based on spread
    if spread >= 25:
        signal = "Extreme Bullish"
    elif spread >= 10:
        signal = "Bullish"
    elif spread <= -25:
        signal = "Extreme Bearish"
    elif spread <= -10:
        signal = "Bearish"
    else:
        signal = "Neutral"

    return {
        "date": row["date"],
        "bullish": row["bullish"],
        "bearish": row["bearish"],
        "neutral": row["neutral"],
        "bull_bear_spread": round(spread, 2),
        "spread_normalized": round(spread_normalized, 4),
        "spread_8w_avg": round(spread_8w_avg, 2),
        "percentile_52w": round(percentile_52w, 1),
        "signal": signal,
    }
