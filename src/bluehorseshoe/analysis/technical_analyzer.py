import logging
import numpy as np
import pandas as pd
from functools import lru_cache
from typing import Dict, Optional

from bluehorseshoe.analysis.constants import (
    TREND_PERIOD, STRONG_R2_THRESHOLD, MIN_VOLUME_THRESHOLD,
    OVERSOLD_RSI_THRESHOLD_EXTREME, OVERSOLD_RSI_REWARD_EXTREME,
    OVERSOLD_RSI_THRESHOLD_MODERATE, OVERSOLD_RSI_REWARD_MODERATE,
    OVERSOLD_BB_REWARD, OVERSOLD_BB_POSITION_THRESHOLD,
    MR_OVERSOLD_RSI_REWARD_EXTREME, MR_OVERSOLD_RSI_REWARD_MODERATE,
    MR_OVERSOLD_BB_REWARD, MR_BELLOW_LOW_BB_BONUS,
    PENALTY_EMA_OVEREXTENSION,
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
    def calculate_technical_score(days: pd.DataFrame, strategy: str = "baseline", enabled_indicators: Optional[list[str]] = None, aggregation: str = "sum") -> Dict[str, float]:
        """
        Calculate a technical score based on the specified strategy.
        Returns a dictionary of component scores for granular analysis.
        """
        if strategy == "mean_reversion":
            return TechnicalAnalyzer.calculate_mean_reversion_score(days, enabled_indicators=enabled_indicators, aggregation=aggregation)
        return TechnicalAnalyzer.calculate_baseline_score(days, enabled_indicators=enabled_indicators, aggregation=aggregation)

    @staticmethod
    def calculate_baseline_score(days: pd.DataFrame, enabled_indicators: Optional[list[str]] = None, aggregation: str = "sum") -> Dict[str, float]:
        """
        Trend-following scoring: Rewards strength, momentum, and breakouts.
        'aggregation' can be 'sum' or 'product'.
        """
        components = {}
        
        if len(days) == 0 or days.iloc[-1].get('avg_volume_20', 0) < MIN_VOLUME_THRESHOLD:
            return {"total": 0.0}

        all_indicators_classes = {
            "trend": TrendIndicator,
            "volume": VolumeIndicator,
            "limit": LimitIndicator,
            "candlestick": CandlestickIndicator,
            "moving_average": MovingAverageIndicator,
            "momentum": MomentumIndicator
        }

        # Parse granular indicators if provided (e.g., "momentum:macd")
        indicator_filters = {}
        if enabled_indicators:
            for item in enabled_indicators:
                if ":" in item:
                    group, sub = item.split(":", 1)
                    if group not in indicator_filters:
                        indicator_filters[group] = []
                    indicator_filters[group].append(sub)
                else:
                    indicator_filters[item] = None

        # Instantiate and score
        total_score = 1.0 if aggregation == "product" else 0.0
        active_indicator_count = 0

        for name, cls in all_indicators_classes.items():
            if enabled_indicators and name not in indicator_filters:
                continue
            
            indicator_inst = cls(days)
            sub_filters = indicator_filters.get(name)
            
            try:
                score = indicator_inst.get_score(enabled_sub_indicators=sub_filters, aggregation=aggregation).buy
            except TypeError:
                # Fallback for indicators not yet updated to support sub-filters
                score = indicator_inst.get_score().buy
                
            components[name] = float(score)
            
            if aggregation == "product":
                total_score *= score
            else:
                total_score += score
            
            active_indicator_count += 1

        # If product resulted in 0 or no indicators were active
        if active_indicator_count == 0:
            total_score = 0.0

        # Only apply penalties and bonuses if we are running the full baseline
        if not enabled_indicators:
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

            # RSI Oversold Signal (Refined: Reward if in Uptrend, otherwise Penalty)
            trend = TechnicalAnalyzer.calculate_trend(days)
            is_uptrend = "Uptrend" in trend
            
            if rsi < OVERSOLD_RSI_THRESHOLD_EXTREME:
                reward = abs(OVERSOLD_RSI_REWARD_EXTREME) if is_uptrend else OVERSOLD_RSI_REWARD_EXTREME
                components["bonus_oversold_rsi"] = reward
                total_score += reward
            elif rsi < OVERSOLD_RSI_THRESHOLD_MODERATE:
                reward = abs(OVERSOLD_RSI_REWARD_MODERATE) if is_uptrend else OVERSOLD_RSI_REWARD_MODERATE
                components["bonus_oversold_rsi"] = reward
                total_score += reward

            # Bollinger Band Oversold Signal
            bb_lower = last_row.get('bb_lower')
            if bb_lower is not None and last_row['close'] < bb_lower:
                reward = abs(OVERSOLD_BB_REWARD) if is_uptrend else OVERSOLD_BB_REWARD
                total_score += reward

            # Volume Exhaustion / Selling Climax
            avg_vol = last_row.get('avg_volume_20', 1)
            vol_ratio = last_row['volume'] / avg_vol
            
            if rsi < OVERSOLD_RSI_THRESHOLD_EXTREME and vol_ratio > 2.0:
                # Selling climax: Extreme oversold + high volume = strong reversal potential
                components["bonus_selling_climax"] = 3.0
                total_score += 3.0
            elif vol_ratio > 3.0:
                # Simple exhaustion penalty (could be buying climax at the top)
                components["penalty_volume_exhaustion"] = PENALTY_VOLUME_EXHAUSTION
                total_score += PENALTY_VOLUME_EXHAUSTION

        components["total"] = float(total_score)
        return components

    @staticmethod
    def calculate_mean_reversion_score(days: pd.DataFrame, enabled_indicators: Optional[list[str]] = None, aggregation: str = "sum") -> Dict[str, float]:
        """
        Mean-reversion scoring: Rewards oversold conditions and "buying the dip".
        """
        components = {}
        
        if len(days) == 0 or days.iloc[-1].get('avg_volume_20', 0) < MIN_VOLUME_THRESHOLD:
            return {"total": 0.0}

        from bluehorseshoe.core.config import weights_config
        weights = weights_config.get_weights('mean_reversion')

        last_row = days.iloc[-1]
        total_score = 1.0 if aggregation == "product" else 0.0
        active_count = 0

        # Define components
        def add_to_score(name, score):
            nonlocal total_score, active_count
            components[name] = float(score)
            if aggregation == "product":
                total_score *= score
            else:
                total_score += score
            active_count += 1

        # 1. RSI Oversold (The primary driver)
        if (not enabled_indicators or "rsi" in enabled_indicators) and weights.get('RSI_MULTIPLIER', 1.0) > 0:
            rsi = last_row.get('rsi_14', 50)
            rsi_score = 0.0
            if rsi < OVERSOLD_RSI_THRESHOLD_EXTREME:
                rsi_score = MR_OVERSOLD_RSI_REWARD_EXTREME
            elif rsi < OVERSOLD_RSI_THRESHOLD_MODERATE:
                rsi_score = MR_OVERSOLD_RSI_REWARD_MODERATE
            
            rsi_score *= weights.get('RSI_MULTIPLIER', 1.0)
            if rsi_score > 0 or enabled_indicators:
                add_to_score("bonus_oversold_rsi", rsi_score)

        # 2. Bollinger Band Position (Granular)
        if (not enabled_indicators or "bb" in enabled_indicators) and weights.get('BB_MULTIPLIER', 1.0) > 0:
            bb_lower = last_row.get('bb_lower')
            bb_upper = last_row.get('bb_upper')
            bb_bonus = 0.0
            if bb_lower is not None and bb_upper is not None and bb_upper > bb_lower:
                # Calculate %B (Bollinger Band Position)
                bb_pos = (last_row['close'] - bb_lower) / (bb_upper - bb_lower)
                if bb_pos < OVERSOLD_BB_POSITION_THRESHOLD:
                    bb_bonus = MR_OVERSOLD_BB_REWARD
                    # Extra bonus if price is actually below the lower band
                    if last_row['close'] < bb_lower:
                        bb_bonus += MR_BELLOW_LOW_BB_BONUS
            
            bb_bonus *= weights.get('BB_MULTIPLIER', 1.0)
            if bb_bonus > 0 or enabled_indicators:
                add_to_score("bonus_oversold_bb", bb_bonus)

        # 3. Distance from Moving Average (Inverse of trend logic)
        if (not enabled_indicators or "ma_dist" in enabled_indicators) and weights.get('MA_DIST_MULTIPLIER', 1.0) > 0:
            ema20 = last_row.get('ema_20')
            ma_bonus = 0.0
            if ema20 is not None:
                dist_ema20 = (last_row['close'] / ema20) - 1
                if dist_ema20 < -0.05:
                    # Scale bonus based on distance
                    ma_bonus = 3.0 if dist_ema20 < -0.10 else 1.5
            
            ma_bonus *= weights.get('MA_DIST_MULTIPLIER', 1.0)
            if ma_bonus > 0 or enabled_indicators:
                add_to_score("bonus_ma_dist", ma_bonus)

        # 4. Candlestick Reversals (Hammers, etc.)
        if (not enabled_indicators or "candlestick" in enabled_indicators) and weights.get('CANDLESTICK_MULTIPLIER', 1.0) > 0:
            cs = CandlestickIndicator(days)
            # We only care about bullish patterns appearing at the bottom
            cs_score = 2.0 if cs.get_score().buy > 0 else 0.0
            
            cs_score *= weights.get('CANDLESTICK_MULTIPLIER', 1.0)
            if cs_score > 0 or enabled_indicators:
                add_to_score("candlestick", cs_score)

        if active_count == 0 or (aggregation == "product" and total_score == 0):
            total_score = 0.0

        components["total"] = float(total_score)
        return components

