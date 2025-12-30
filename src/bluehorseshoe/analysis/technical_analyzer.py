import logging
import numpy as np
import pandas as pd
from functools import lru_cache
from typing import Dict, Optional

from bluehorseshoe.analysis.constants import (
    TREND_PERIOD, STRONG_R2_THRESHOLD, MIN_VOLUME_THRESHOLD,
    OVERSOLD_RSI_THRESHOLD_EXTREME, OVERSOLD_RSI_REWARD_EXTREME,
    OVERSOLD_RSI_THRESHOLD_MODERATE, OVERSOLD_RSI_REWARD_MODERATE,
    OVERSOLD_BB_REWARD, PENALTY_EMA_OVEREXTENSION,
    PENALTY_RSI_THRESHOLD_EXTREME, PENALTY_RSI_SCORE_EXTREME,
    PENALTY_RSI_THRESHOLD_MODERATE, PENALTY_RSI_SCORE_MODERATE,
    PENALTY_VOLUME_EXHAUSTION
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
    def calculate_technical_score(days: pd.DataFrame, strategy: str = "baseline") -> Dict[str, float]:
        """
        Calculate a technical score based on the specified strategy.
        Returns a dictionary of component scores for granular analysis.
        """
        if strategy == "mean_reversion":
            return TechnicalAnalyzer.calculate_mean_reversion_score(days)
        return TechnicalAnalyzer.calculate_baseline_score(days)

    @staticmethod
    def calculate_baseline_score(days: pd.DataFrame) -> Dict[str, float]:
        """
        Trend-following scoring: Rewards strength, momentum, and breakouts.
        """
        components = {}
        
        if len(days) == 0 or days.iloc[-1].get('avg_volume_20', 0) < MIN_VOLUME_THRESHOLD:
            return {"total": 0.0}

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

        last_row = days.iloc[-1]
        
        # EMA Overextension Penalty (Trend logic: Don't buy the peak of a parabolic move)
        ema9 = days['close'].ewm(span=9).mean().iloc[-1]
        dist_ema9 = (last_row['close'] / ema9) - 1
        if dist_ema9 > 0.10:
            components["penalty_ema_overextension"] = PENALTY_EMA_OVEREXTENSION
            total_score += PENALTY_EMA_OVEREXTENSION

        # RSI Overbought Penalty
        rsi = last_row.get('rsi_14', 50)
        if rsi > PENALTY_RSI_THRESHOLD_EXTREME:
            components["penalty_rsi"] = PENALTY_RSI_SCORE_EXTREME
            total_score += PENALTY_RSI_SCORE_EXTREME
        elif rsi > PENALTY_RSI_THRESHOLD_MODERATE:
            components["penalty_rsi"] = PENALTY_RSI_SCORE_MODERATE
            total_score += PENALTY_RSI_SCORE_MODERATE

        # RSI Oversold Signal (In baseline/trend-following, this is a penalty/caution)
        if rsi < OVERSOLD_RSI_THRESHOLD_EXTREME:
            components["bonus_oversold_rsi"] = OVERSOLD_RSI_REWARD_EXTREME
            total_score += OVERSOLD_RSI_REWARD_EXTREME
        elif rsi < OVERSOLD_RSI_THRESHOLD_MODERATE:
            components["bonus_oversold_rsi"] = OVERSOLD_RSI_REWARD_MODERATE
            total_score += OVERSOLD_RSI_REWARD_MODERATE

        # Bollinger Band Oversold Signal
        bb_lower = last_row.get('bb_lower')
        if bb_lower is not None and last_row['close'] < bb_lower:
            components["bonus_oversold_bb"] = OVERSOLD_BB_REWARD
            total_score += OVERSOLD_BB_REWARD

        # Volume Exhaustion Penalty
        avg_vol = last_row.get('avg_volume_20', 1)
        vol_ratio = last_row['volume'] / avg_vol
        if vol_ratio > 3.0:
            components["penalty_volume_exhaustion"] = PENALTY_VOLUME_EXHAUSTION
            total_score += PENALTY_VOLUME_EXHAUSTION

        components["total"] = float(total_score)
        return components

    @staticmethod
    def calculate_mean_reversion_score(days: pd.DataFrame) -> Dict[str, float]:
        """
        Mean-reversion scoring: Rewards oversold conditions and "buying the dip".
        """
        components = {}
        
        if len(days) == 0 or days.iloc[-1].get('avg_volume_20', 0) < MIN_VOLUME_THRESHOLD:
            return {"total": 0.0}

        last_row = days.iloc[-1]
        total_score = 0.0

        # 1. RSI Oversold (The primary driver)
        rsi = last_row.get('rsi_14', 50)
        if rsi < OVERSOLD_RSI_THRESHOLD_EXTREME:
            components["bonus_oversold_rsi"] = abs(OVERSOLD_RSI_REWARD_EXTREME)
            total_score += abs(OVERSOLD_RSI_REWARD_EXTREME)
        elif rsi < OVERSOLD_RSI_THRESHOLD_MODERATE:
            components["bonus_oversold_rsi"] = abs(OVERSOLD_RSI_REWARD_MODERATE)
            total_score += abs(OVERSOLD_RSI_REWARD_MODERATE)

        # 2. Bollinger Band Oversold
        bb_lower = last_row.get('bb_lower')
        bb_upper = last_row.get('bb_upper')
        if bb_lower is not None and bb_upper is not None and bb_upper > bb_lower:
            if last_row['close'] < bb_lower:
                components["bonus_oversold_bb"] = abs(OVERSOLD_BB_REWARD)
                total_score += abs(OVERSOLD_BB_REWARD)

        # 3. Distance from Moving Average (Inverse of trend logic)
        ma20 = days['close'].rolling(window=20).mean().iloc[-1]
        dist_ma20 = (last_row['close'] / ma20) - 1
        if dist_ma20 < -0.05:
            bonus = 2.0 if dist_ma20 < -0.10 else 1.0
            components["bonus_ma_dist"] = bonus
            total_score += bonus

        # 4. Candlestick Reversals (Hammers, etc.)
        cs = CandlestickIndicator(days)
        # We only care about bullish patterns appearing at the bottom
        if cs.get_score().buy > 0:
            components["candlestick"] = 2.0
            total_score += 2.0

        components["total"] = float(total_score)
        return components

