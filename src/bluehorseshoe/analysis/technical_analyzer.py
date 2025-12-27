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
    def calculate_technical_score(days: pd.DataFrame) -> float:
        """
        Calculate a technical score by analyzing multiple indicators and applying safety filters:
        1. Base indicator scoring (Trend, Volume, Momentum, etc.)
        2. Overextension Penalty: Subtract points if price is too far above EMAs.
        3. RSI Overbought Penalty: Subtract points if RSI > 70.
        4. Volume Exhaustion Penalty: Subtract points if volume spike is too extreme.
        """
        # 1) Early exit if average volume is too low
        if len(days) == 0 or days.iloc[-1].get('avg_volume_20', 0) < MIN_VOLUME_THRESHOLD:
            return 0.0

        total_score : float = 0
        for indicator in [TrendIndicator(days), VolumeIndicator(days), LimitIndicator(days), CandlestickIndicator(days),
                          MovingAverageIndicator(days), MomentumIndicator(days)]:
            total_score += indicator.get_score().buy

        # --- SAFETY FILTERS (Penalties for 'Buying the Peak') ---
        last_row = days.iloc[-1]
        
        # A) EMA Overextension (Mean Reversion Risk)
        # Using 9-day EMA to check for short-term overextension
        ema9 = days['close'].ewm(span=9).mean().iloc[-1]
        dist_ema9 = (last_row['close'] / ema9) - 1
        if dist_ema9 > 0.10: # > 10% above EMA9
            total_score -= 5.0
            logging.debug("Penalty: Overextended above EMA9 (%.2f%%)", dist_ema9 * 100)

        # B) RSI Overbought (Exhaustion Risk)
        rsi = last_row.get('rsi_14', 50)
        if rsi > 75:
            total_score -= 3.0
            logging.debug("Penalty: RSI Overbought (%.2f)", rsi)
        elif rsi > 70:
            total_score -= 1.0

        # C) Volume Exhaustion (Blow-off Top Risk)
        avg_vol = last_row.get('avg_volume_20', 1)
        vol_ratio = last_row['volume'] / avg_vol
        if vol_ratio > 3.0: # > 3x average volume
            total_score -= 2.0
            logging.debug("Penalty: Volume Exhaustion (%.2f ratio)", vol_ratio)

        return float(total_score)
