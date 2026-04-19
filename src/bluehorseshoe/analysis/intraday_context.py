"""Intraday context analysis from daily OHLCV bars.

Phase 1: daily-bar proxy -- computes failed breakout detection, close strength,
and range expansion from existing enriched DataFrames.

Phase 2: 5-min bar confirmation for top N candidates.
"""

import math
from typing import Tuple

import pandas as pd

# ---------------------------------------------------------------------------
# Tier 1 Constants (daily-bar proxy)
# Each weight controls direct score-point contribution (no intermediate clamp).
# The integration weight in constants.py is the strategy-level multiplier.
# ---------------------------------------------------------------------------
LOOKBACK_DAYS = 20
FAILED_BREAKOUT_PENALTY = 0.5       # Score points lost on failed breakout
FAILED_BREAKDOWN_BONUS = 0.0        # Empirically zero impact — disabled
CLOSE_STRENGTH_WEIGHT = 2.0         # (close_str - 0.5) × this; range ±1.0
WIDE_RANGE_THRESHOLD = 1.5          # Detection threshold (not a weight)
WIDE_RANGE_REVERSAL_PENALTY = 0.0   # Empirically zero impact — disabled
CONTEXT_BULLISH_THRESHOLD = 0.2
CONTEXT_BEARISH_THRESHOLD = -0.2

# ---------------------------------------------------------------------------
# Tier 2 Constants (Phase 2 - intraday confirmation)
# ---------------------------------------------------------------------------
BREAKOUT_HOLD_BARS = 6
VOLUME_CONFIRMATION_MULT = 2.0
INTRADAY_TRAILING_BARS = 20


def detect_failed_breakout(
    df: pd.DataFrame, lookback: int = LOOKBACK_DAYS,
) -> Tuple[bool, bool, float, float]:
    """Detect failed breakout/breakdown from daily bars.

    Uses the prior ``lookback`` bars (excluding the current bar) to compute
    resistance (max high) and support (min low). Then checks whether the
    last bar pierced but failed to close beyond these levels.

    Returns:
        (failed_breakout, failed_breakdown, resistance, support)
    """
    if len(df) < 3:
        last = df.iloc[-1]
        return False, False, float(last["high"]), float(last["low"])

    effective_lookback = min(lookback, len(df) - 1)
    prior = df.iloc[-(effective_lookback + 1):-1]
    resistance = float(prior["high"].max())
    support = float(prior["low"].min())
    last = df.iloc[-1]

    failed_breakout = bool(last["high"] > resistance and last["close"] < resistance)
    failed_breakdown = bool(last["low"] < support and last["close"] > support)

    return failed_breakout, failed_breakdown, resistance, support


def close_strength(row) -> float:
    """Position of close within the day's range.

    Returns 0.0 (closed at low) to 1.0 (closed at high).
    Returns 0.5 for zero-range bars (high == low).
    """
    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])
    if high == low:
        return 0.5
    result = (close - low) / (high - low)
    return max(0.0, min(1.0, result))


def range_expansion(high: float, low: float, atr: float) -> float:
    """Ratio of today's range to ATR(14).

    Returns 1.0 if ATR is zero or NaN.
    """
    if atr is None or math.isnan(atr) or atr <= 0:
        return 1.0
    return (high - low) / atr


def compute_context_score(
    failed_breakout: bool,
    failed_breakdown: bool,
    close_str: float,
    range_exp: float,
) -> Tuple[float, str]:
    """Composite context score from daily bar signals.

    Returns:
        (context_score, context_label)
        context_score: unbounded — each signal contributes directly via its own
        weight.  The strategy-level integration weight in constants.py scales
        the total before adding to the candidate score.
        context_label: "bullish", "bearish", or "neutral"
    """
    score = 0.0

    if failed_breakout:
        score -= FAILED_BREAKOUT_PENALTY

    if failed_breakdown:
        score += FAILED_BREAKDOWN_BONUS

    score += (close_str - 0.5) * CLOSE_STRENGTH_WEIGHT

    if range_exp > WIDE_RANGE_THRESHOLD and close_str < 0.3:
        score -= WIDE_RANGE_REVERSAL_PENALTY

    if score > CONTEXT_BULLISH_THRESHOLD:
        label = "bullish"
    elif score < CONTEXT_BEARISH_THRESHOLD:
        label = "bearish"
    else:
        label = "neutral"

    return score, label


def compute_daily_context(
    df: pd.DataFrame, lookback: int = LOOKBACK_DAYS,
) -> dict:
    """Main Tier 1 entry point: compute daily-bar context for the last bar.

    Args:
        df: enriched OHLCV DataFrame (must have high, low, close columns;
            optionally atr_14 or ATR).
        lookback: number of prior bars for resistance/support.

    Returns:
        Dict with keys: failed_breakout, failed_breakdown, close_strength,
        range_expansion, resistance, support, context_score, context_label.
    """
    failed_bo, failed_bd, resistance, support = detect_failed_breakout(df, lookback)

    last = df.iloc[-1]
    cs = close_strength(last)

    atr_val = last.get("atr_14")
    if atr_val is None or (isinstance(atr_val, float) and math.isnan(atr_val)):
        atr_val = last.get("ATR")
    if atr_val is None or (isinstance(atr_val, float) and math.isnan(atr_val)):
        atr_val = float(last["high"]) - float(last["low"])

    re = range_expansion(float(last["high"]), float(last["low"]), float(atr_val))

    ctx_score, ctx_label = compute_context_score(failed_bo, failed_bd, cs, re)

    return {
        "failed_breakout": failed_bo,
        "failed_breakdown": failed_bd,
        "close_strength": round(cs, 4),
        "range_expansion": round(re, 4),
        "resistance": resistance,
        "support": support,
        "context_score": round(ctx_score, 4),
        "context_label": ctx_label,
    }


def compute_intraday_confirmation(
    intraday_df: pd.DataFrame, resistance: float,
) -> dict:
    """Compute intraday confirmation from 5-minute bars."""
    neutral = {
        "breakout_accepted": False,
        "volume_confirmed": False,
        "intraday_trend": "mixed",
        "close_trajectory": "flat",
        "confirmation_score": 0.0,
    }
    required = {"open", "high", "low", "close", "volume"}
    if intraday_df is None or intraday_df.empty or not required.issubset(intraday_df.columns):
        return neutral

    df = intraday_df.copy()
    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    if df.empty:
        return neutral

    above_resistance = df["close"] > resistance
    groups = (above_resistance != above_resistance.shift()).cumsum()
    run_lengths = above_resistance.groupby(groups).sum()
    breakout_accepted = bool(run_lengths.max() >= BREAKOUT_HOLD_BARS)

    cross_idx = None
    for i in range(1, len(df)):
        if df.iloc[i]["high"] > resistance and df.iloc[i - 1]["high"] <= resistance:
            cross_idx = i
            break

    if cross_idx is not None and cross_idx >= INTRADAY_TRAILING_BARS:
        trailing_avg = df.iloc[cross_idx - INTRADAY_TRAILING_BARS:cross_idx]["volume"].mean()
        volume_confirmed = bool(df.iloc[cross_idx]["volume"] > trailing_avg * VOLUME_CONFIRMATION_MULT)
    else:
        volume_confirmed = False

    n = len(df)
    third = max(1, n // 3)
    first_third_close = df.iloc[third - 1]["close"]
    last_third_close = df.iloc[-1]["close"]
    mid_close = df.iloc[min(2 * third - 1, n - 1)]["close"]

    if last_third_close > first_third_close and last_third_close > mid_close:
        intraday_trend = "up"
    elif last_third_close < first_third_close and last_third_close < mid_close:
        intraday_trend = "down"
    else:
        intraday_trend = "mixed"

    tail = df.tail(min(6, len(df)))
    if len(tail) >= 3:
        slope = tail["close"].iloc[-1] - tail["close"].iloc[0]
        avg_range = (tail["high"] - tail["low"]).mean()
        if avg_range > 0:
            normalized = slope / avg_range
            if normalized > 0.3:
                close_trajectory = "rising"
            elif normalized < -0.3:
                close_trajectory = "falling"
            else:
                close_trajectory = "flat"
        else:
            close_trajectory = "flat"
    else:
        close_trajectory = "flat"

    score = 0.0
    if breakout_accepted:
        score += 0.4
    if volume_confirmed:
        score += 0.25
    if intraday_trend == "up":
        score += 0.2
    elif intraday_trend == "down":
        score -= 0.1
    if close_trajectory == "rising":
        score += 0.15
    elif close_trajectory == "falling":
        score -= 0.1
    confirmation_score = max(0.0, min(1.0, score))

    return {
        "breakout_accepted": breakout_accepted,
        "volume_confirmed": volume_confirmed,
        "intraday_trend": intraday_trend,
        "close_trajectory": close_trajectory,
        "confirmation_score": round(confirmation_score, 4),
    }
