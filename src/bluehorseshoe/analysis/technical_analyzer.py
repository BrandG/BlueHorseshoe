import logging
import numpy as np
import pandas as pd
from functools import lru_cache
from typing import Dict, Optional

from bluehorseshoe.analysis.constants import (
    TREND_PERIOD, STRONG_R2_THRESHOLD, MIN_VOLUME_THRESHOLD
)
from bluehorseshoe.analysis.indicators.candlestick_indicators import CandlestickIndicator
from bluehorseshoe.analysis.indicators.limit_indicators import LimitIndicator
from bluehorseshoe.analysis.indicators.momentum_indicators import MomentumIndicator
from bluehorseshoe.analysis.indicators.moving_average_indicators import MovingAverageIndicator
from bluehorseshoe.analysis.indicators.trend_indicators import TrendIndicator
from bluehorseshoe.analysis.indicators.volume_indicators import VolumeIndicator

class TechnicalAnalyzer:
    """Handles technical analysis calculations with optimized methods."""

    @staticmethod
    @lru_cache(maxsize=128)
    def _calculate_r2(prices: tuple) -> float:
        """Calculate R-squared value with caching for repeated calculations."""
        prices_array = np.array(prices)
        x = np.arange(len(prices_array))
        slope, intercept = np.polyfit(x, prices_array, 1)
        y_pred = slope * x + intercept
        ss_res = np.sum((prices_array - y_pred) ** 2)
        ss_tot = np.sum((prices_array - np.mean(prices_array)) ** 2)
        return (1 - (ss_res / ss_tot)) if ss_tot != 0 else 0

    @staticmethod
    def _rolling_window(a: np.ndarray, window: int) -> np.ndarray:
        """Create a rolling window view of the array."""
        shape = a.shape[:-1] + (a.shape[-1] - window + 1, window)
        strides = a.strides + (a.strides[-1],)
        return np.lib.stride_tricks.as_strided(a, shape=shape, strides=strides, writeable=False)

    @classmethod
    def calculate_trend(cls, df: pd.DataFrame) -> str:
        """Calculate trend with vectorized operations."""
        if len(df) < TREND_PERIOD:
            return "Insufficient data"

        prices = df['close'].values[-TREND_PERIOD:]
        x = np.arange(TREND_PERIOD)
        slope, _ = np.polyfit(x, prices, 1)
        r2_value = cls._calculate_r2(tuple(prices))

        # Use dictionary for trend lookup
        trend_map = {
            (True, True): "Strong Uptrend",
            (True, False): "Weak Uptrend",
            (False, True): "Strong Downtrend",
            (False, False): "Weak Downtrend"
        }

        return trend_map.get((slope > 0, r2_value > STRONG_R2_THRESHOLD), "No Clear Trend")

    @staticmethod
    def calculate_technical_score(days: pd.DataFrame) -> Dict[str, float]:
        """
        Calculate a technical score by analyzing multiple indicators and applying safety filters.
        Returns a dictionary of component scores for granular analysis.
        """
        components = {}
        
        # 1) Early exit if average volume is too low
        if len(days) == 0 or days.iloc[-1].get('avg_volume_20', 0) < MIN_VOLUME_THRESHOLD:
            return {"total": 0.0}

        # Base indicator scoring
        indicators = {
            "trend": TrendIndicator(days),
            "volume": VolumeIndicator(days),
            "limit": LimitIndicator(days),
            "candlestick": CandlestickIndicator(days),
            "moving_average": MovingAverageIndicator(days),
            "momentum": MomentumIndicator(days)
        }
        
        total_score = 0.0
        for name, indicator in indicators.items():
            score = indicator.get_score().buy
            components[name] = float(score)
            total_score += score

        # --- SAFETY FILTERS (Penalties) ---
        last_row = days.iloc[-1]
        
        # A) EMA Overextension
        ema9 = days['close'].ewm(span=9).mean().iloc[-1]
        dist_ema9 = (last_row['close'] / ema9) - 1
        if dist_ema9 > 0.10:
            components["penalty_ema_overextension"] = -5.0
            total_score -= 5.0

        # B) RSI Overbought
        rsi = last_row.get('rsi_14', 50)
        if rsi > 75:
            components["penalty_rsi"] = -3.0
            total_score -= 3.0
        elif rsi > 70:
            components["penalty_rsi"] = -1.0
            total_score -= 1.0

        # C) Volume Exhaustion
        avg_vol = last_row.get('avg_volume_20', 1)
        vol_ratio = last_row['volume'] / avg_vol
        if vol_ratio > 3.0:
            components["penalty_volume_exhaustion"] = -2.0
            total_score -= 2.0

        components["total"] = float(total_score)
        return components
