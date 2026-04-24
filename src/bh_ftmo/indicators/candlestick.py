"""Candlestick pattern detectors for BH FTMO.

Hand-rolled per decision 15D (fully independent of bluehorseshoe/ and of talib).
Every threshold is configurable — Phase 2c tunes them empirically for 4h forex.

All pattern detectors return a boolean ``pd.Series`` aligned to the input ``ohlc``.
They can be composed with ``|`` / ``&`` operators.

Bar anatomy helpers (``body_size``, ``upper_shadow``, etc.) are exposed for
callers that need to build custom patterns or score intensity continuously.
"""
from __future__ import annotations

import pandas as pd

from bh_ftmo.indicators._common import _require_ohlc


# ---- Anatomy helpers ---------------------------------------------------


def body_size(ohlc: pd.DataFrame) -> pd.Series:
    """Absolute body size: |close - open|."""
    _require_ohlc(ohlc)
    out = (ohlc["close"] - ohlc["open"]).abs()
    out.name = "body_size"
    return out


def total_range(ohlc: pd.DataFrame) -> pd.Series:
    """High - low."""
    _require_ohlc(ohlc)
    out = ohlc["high"] - ohlc["low"]
    out.name = "total_range"
    return out


def upper_shadow(ohlc: pd.DataFrame) -> pd.Series:
    """High - max(open, close). Zero when close/open is at or above high (rare)."""
    _require_ohlc(ohlc)
    out = ohlc["high"] - ohlc[["open", "close"]].max(axis=1)
    out.name = "upper_shadow"
    return out


def lower_shadow(ohlc: pd.DataFrame) -> pd.Series:
    """min(open, close) - low."""
    _require_ohlc(ohlc)
    out = ohlc[["open", "close"]].min(axis=1) - ohlc["low"]
    out.name = "lower_shadow"
    return out


def is_bullish(ohlc: pd.DataFrame) -> pd.Series:
    """Close > open (the body is up)."""
    _require_ohlc(ohlc)
    out = ohlc["close"] > ohlc["open"]
    out.name = "is_bullish"
    return out


def is_bearish(ohlc: pd.DataFrame) -> pd.Series:
    """Close < open (the body is down)."""
    _require_ohlc(ohlc)
    out = ohlc["close"] < ohlc["open"]
    out.name = "is_bearish"
    return out


# ---- Single-bar patterns ----------------------------------------------


def is_doji(ohlc: pd.DataFrame, *, body_frac: float = 0.1) -> pd.Series:
    """Indecision: body is at most ``body_frac`` of total range.

    Requires non-zero range (flat bars → False).
    """
    _require_ohlc(ohlc)
    if not 0 < body_frac <= 1:
        raise ValueError(f"body_frac must be in (0, 1], got {body_frac}")
    rng = total_range(ohlc)
    out = (rng > 0) & (body_size(ohlc) <= body_frac * rng)
    out.name = "is_doji"
    return out


def is_hammer(
    ohlc: pd.DataFrame,
    *,
    body_frac_max: float = 0.35,
    lower_shadow_min: float = 0.5,
    upper_shadow_max: float = 0.15,
) -> pd.Series:
    """Bullish reversal candle: small body, long lower shadow, short upper shadow.

    Defaults:
      - body ≤ 35% of range
      - lower shadow ≥ 50% of range
      - upper shadow ≤ 15% of range

    Note: "hammer" traditionally implies appearance at the bottom of a
    downtrend. This detector is context-free — it fires on shape alone.
    Caller composes with a trend filter for strict-hammer semantics.
    """
    _require_ohlc(ohlc)
    rng = total_range(ohlc)
    body = body_size(ohlc)
    lower = lower_shadow(ohlc)
    upper = upper_shadow(ohlc)
    out = (
        (rng > 0)
        & (body <= body_frac_max * rng)
        & (lower >= lower_shadow_min * rng)
        & (upper <= upper_shadow_max * rng)
    )
    out.name = "is_hammer"
    return out


def is_shooting_star(
    ohlc: pd.DataFrame,
    *,
    body_frac_max: float = 0.35,
    upper_shadow_min: float = 0.5,
    lower_shadow_max: float = 0.15,
) -> pd.Series:
    """Bearish reversal (inverted hammer): small body, long upper shadow,
    short lower shadow. Defaults mirror :func:`is_hammer`.
    """
    _require_ohlc(ohlc)
    rng = total_range(ohlc)
    body = body_size(ohlc)
    upper = upper_shadow(ohlc)
    lower = lower_shadow(ohlc)
    out = (
        (rng > 0)
        & (body <= body_frac_max * rng)
        & (upper >= upper_shadow_min * rng)
        & (lower <= lower_shadow_max * rng)
    )
    out.name = "is_shooting_star"
    return out


# ---- Two-bar patterns -------------------------------------------------


def is_bullish_engulfing(
    ohlc: pd.DataFrame,
    *,
    min_body_frac: float = 0.3,
) -> pd.Series:
    """Bullish engulfing: prior bar bearish, current bar bullish, current body
    fully engulfs prior body (current_open <= prior_close AND
    current_close >= prior_open). Both bars must have a non-negligible body
    (at least ``min_body_frac`` of their range) to exclude dojis.
    """
    _require_ohlc(ohlc)
    if not 0 < min_body_frac <= 1:
        raise ValueError(f"min_body_frac must be in (0, 1], got {min_body_frac}")

    prev_open = ohlc["open"].shift(1)
    prev_close = ohlc["close"].shift(1)
    prev_range = (ohlc["high"].shift(1) - ohlc["low"].shift(1)).replace(0, pd.NA)
    prev_body_frac = (prev_open - prev_close).abs() / prev_range

    rng = total_range(ohlc).replace(0, pd.NA)
    body_frac = body_size(ohlc) / rng

    cond = (
        (prev_close < prev_open)          # prior bar bearish
        & (ohlc["close"] > ohlc["open"])  # current bar bullish
        & (ohlc["open"] <= prev_close)    # opens at/below prior close
        & (ohlc["close"] >= prev_open)    # closes at/above prior open
        & (body_frac >= min_body_frac)
        & (prev_body_frac >= min_body_frac)
    )
    out = cond.fillna(False).astype(bool)
    out.name = "is_bullish_engulfing"
    return out


def is_bearish_engulfing(
    ohlc: pd.DataFrame,
    *,
    min_body_frac: float = 0.3,
) -> pd.Series:
    """Bearish engulfing: prior bar bullish, current bar bearish, current body
    fully engulfs prior body.
    """
    _require_ohlc(ohlc)
    if not 0 < min_body_frac <= 1:
        raise ValueError(f"min_body_frac must be in (0, 1], got {min_body_frac}")

    prev_open = ohlc["open"].shift(1)
    prev_close = ohlc["close"].shift(1)
    prev_range = (ohlc["high"].shift(1) - ohlc["low"].shift(1)).replace(0, pd.NA)
    prev_body_frac = (prev_close - prev_open).abs() / prev_range

    rng = total_range(ohlc).replace(0, pd.NA)
    body_frac = body_size(ohlc) / rng

    cond = (
        (prev_close > prev_open)          # prior bar bullish
        & (ohlc["close"] < ohlc["open"])  # current bar bearish
        & (ohlc["open"] >= prev_close)    # opens at/above prior close
        & (ohlc["close"] <= prev_open)    # closes at/below prior open
        & (body_frac >= min_body_frac)
        & (prev_body_frac >= min_body_frac)
    )
    out = cond.fillna(False).astype(bool)
    out.name = "is_bearish_engulfing"
    return out
