"""
Module for performing technical analysis and scoring.
"""

from functools import lru_cache
from typing import Dict, Optional

import numpy as np
import pandas as pd

from bluehorseshoe.analysis.constants import (
    TREND_PERIOD, STRONG_R2_THRESHOLD, MIN_VOLUME_THRESHOLD,
    OVERSOLD_RSI_THRESHOLD_EXTREME, OVERSOLD_RSI_REWARD_EXTREME,
    OVERSOLD_RSI_THRESHOLD_MODERATE, OVERSOLD_RSI_REWARD_MODERATE,
    OVERSOLD_BB_REWARD,
    PENALTY_EMA_OVEREXTENSION_MODERATE, PENALTY_EMA_OVEREXTENSION_EXTREME,
    PENALTY_EMA_THRESHOLD_MODERATE, PENALTY_EMA_THRESHOLD_EXTREME,
    PENALTY_RSI_THRESHOLD_EXTREME, PENALTY_RSI_SCORE_EXTREME,
    PENALTY_RSI_THRESHOLD_MODERATE, PENALTY_RSI_SCORE_MODERATE,
    PENALTY_VOLUME_EXHAUSTION
)
from bluehorseshoe.analysis.strategy_registry import get_strategy
from bluehorseshoe.analysis.indicators.candlestick_indicators import CandlestickIndicator
from bluehorseshoe.analysis.indicators.limit_indicators import LimitIndicator
from bluehorseshoe.analysis.indicators.momentum_indicators import MomentumIndicator
from bluehorseshoe.analysis.indicators.moving_average_indicators import MovingAverageIndicator
from bluehorseshoe.analysis.indicators.mean_reversion_indicators import MeanReversionIndicator
from bluehorseshoe.analysis.indicators.price_action_indicators import PriceActionIndicator
from bluehorseshoe.analysis.indicators.trend_indicators import TrendIndicator
from bluehorseshoe.analysis.indicators.volume_indicators import VolumeIndicator

class TechnicalAnalyzer:
    """Handles technical analysis calculations with optimized methods."""
    # pylint: disable=too-few-public-methods

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

    @staticmethod
    def _is_dead_or_flat(days: pd.DataFrame) -> bool:
        """
        Detects if a stock is 'dead', halted, or pinned (e.g., pending acquisition).
        Criteria: Extremely low volatility over the last 5 days.
        """
        if len(days) < 5:
            return False

        recent = days.tail(5)
        avg_close = recent['close'].mean()

        # 1. Check ATR (normalized)
        # Calculate approximate True Range for last 5 days
        high_low = recent['high'] - recent['low']
        # We need previous close for the full TR, but simple H-L is usually enough to catch dead stocks
        avg_tr = high_low.mean()

        if avg_tr / avg_close < 0.005: # Less than 0.5% average daily range
            return True

        # 2. Check Standard Deviation of Close
        std_dev = recent['close'].std()
        if std_dev / avg_close < 0.002: # Extremely pinned price
            return True

        return False

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
    def calculate_technical_score(
        days: pd.DataFrame,
        strategy: str = "baseline",
        enabled_indicators: Optional[list[str]] = None,
        aggregation: str = "sum"
    ) -> Dict[str, float]:
        """
        Calculate a technical score based on the specified strategy.
        Returns a dictionary of component scores for granular analysis.

        Delegates to ``calculate_score_for_strategy()`` via the strategy
        registry so that new strategies are automatically supported.
        """
        strat_obj = get_strategy(strategy)
        return TechnicalAnalyzer.calculate_score_for_strategy(
            days, strat_obj,
            enabled_indicators=enabled_indicators,
            aggregation=aggregation,
        )

    @staticmethod
    def calculate_score_for_strategy(
        days: pd.DataFrame,
        strategy,
        enabled_indicators: Optional[list[str]] = None,
        aggregation: str = "sum"
    ) -> Dict[str, float]:
        """
        Calculate a technical score using a ``TradingStrategy`` object.

        Uses ``strategy.weight_prefix`` to load the correct indicator weights.
        """
        if len(days) == 0:
            return {"total": 0.0}

        if TechnicalAnalyzer._is_dead_or_flat(days):
            return {"total": 0.0}

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

        total_score, components, active_count = TechnicalAnalyzer._score_indicators(
            days, indicator_filters, aggregation,
            weight_prefix=strategy.weight_prefix,
        )

        if active_count == 0:
            total_score = 0.0

        # Apply baseline modifiers (same penalties/bonuses for all strategies)
        if not enabled_indicators:
            mod_score, mod_components = TechnicalAnalyzer._calculate_baseline_modifiers(days)
            total_score += mod_score
            components.update(mod_components)

        components["total"] = float(total_score)
        return components

    @staticmethod
    def _calculate_baseline_modifiers(days: pd.DataFrame) -> tuple[float, Dict[str, float]]:
        """Calculates penalties and bonuses for the baseline strategy."""
        components = {
            "penalty_ema_overextension": 0.0,
            "penalty_rsi": 0.0,
            "bonus_oversold_rsi": 0.0,
            "bonus_oversold_bb": 0.0,
            "bonus_selling_climax": 0.0,
            "penalty_volume_exhaustion": 0.0
        }

        last_row = days.iloc[-1]
        score_adj = 0.0

        # EMA Overextension Penalty
        ema9 = days['close'].ewm(span=9).mean().iloc[-1]
        dist_ema9 = (last_row['close'] / ema9) - 1
        if dist_ema9 > PENALTY_EMA_THRESHOLD_EXTREME:
            components["penalty_ema_overextension"] = PENALTY_EMA_OVEREXTENSION_EXTREME
            score_adj += PENALTY_EMA_OVEREXTENSION_EXTREME
        elif dist_ema9 > PENALTY_EMA_THRESHOLD_MODERATE:
            components["penalty_ema_overextension"] = PENALTY_EMA_OVEREXTENSION_MODERATE
            score_adj += PENALTY_EMA_OVEREXTENSION_MODERATE

        # RSI Checks
        rsi = last_row.get('rsi_14', 50)

        # Overbought Penalty
        if rsi > PENALTY_RSI_THRESHOLD_EXTREME:
            components["penalty_rsi"] = PENALTY_RSI_SCORE_EXTREME
            score_adj += PENALTY_RSI_SCORE_EXTREME
        elif rsi > PENALTY_RSI_THRESHOLD_MODERATE:
            components["penalty_rsi"] = PENALTY_RSI_SCORE_MODERATE
            score_adj += PENALTY_RSI_SCORE_MODERATE

        # Oversold Signal (Reward if Uptrend)
        trend = TechnicalAnalyzer.calculate_trend(days)
        is_uptrend = "Uptrend" in trend

        if rsi < OVERSOLD_RSI_THRESHOLD_EXTREME:
            reward = abs(OVERSOLD_RSI_REWARD_EXTREME) if is_uptrend else OVERSOLD_RSI_REWARD_EXTREME
            components["bonus_oversold_rsi"] = reward
            score_adj += reward
        elif rsi < OVERSOLD_RSI_THRESHOLD_MODERATE:
            reward = abs(OVERSOLD_RSI_REWARD_MODERATE) if is_uptrend else OVERSOLD_RSI_REWARD_MODERATE
            components["bonus_oversold_rsi"] = reward
            score_adj += reward

        # Bollinger Band Oversold
        bb_lower = last_row.get('bb_lower')
        if bb_lower is not None and last_row['close'] < bb_lower:
            reward = abs(OVERSOLD_BB_REWARD) if is_uptrend else OVERSOLD_BB_REWARD
            components["bonus_oversold_bb"] = reward
            score_adj += reward

        # Volume Exhaustion
        avg_vol = last_row.get('avg_volume_20', 1)
        vol_ratio = last_row['volume'] / avg_vol

        if rsi < OVERSOLD_RSI_THRESHOLD_EXTREME and vol_ratio > 2.0:
            components["bonus_selling_climax"] = 3.0
            score_adj += 3.0
        elif vol_ratio > 3.0:
            components["penalty_volume_exhaustion"] = PENALTY_VOLUME_EXHAUSTION
            score_adj += PENALTY_VOLUME_EXHAUSTION

        return score_adj, components


    @staticmethod
    def _score_indicators(
        days: pd.DataFrame,
        indicator_filters: Dict[str, Optional[list[str]]],
        aggregation: str,
        weight_prefix: str = ""
    ) -> tuple[float, Dict[str, float], int]:
        """Calculates combined score from all active indicator classes.

        Args:
            weight_prefix: When set (e.g. "mr_"), indicator classes load weights
                from prefixed categories (mr_trend, mr_momentum, etc.).
        """
        all_indicators_classes = {
            "trend": TrendIndicator,
            "volume": VolumeIndicator,
            "limit": LimitIndicator,
            "candlestick": CandlestickIndicator,
            "moving_average": MovingAverageIndicator,
            "momentum": MomentumIndicator,
            "price_action": PriceActionIndicator,
            "mean_reversion_specific": MeanReversionIndicator
        }

        components = {}
        total_score = 1.0 if aggregation == "product" else 0.0
        active_count = 0

        for name, cls in all_indicators_classes.items():
            if indicator_filters and name not in indicator_filters:
                continue

            weight_category = f"{weight_prefix}{name}" if weight_prefix else None
            indicator_inst = cls(days, weight_category=weight_category)
            sub_filters = indicator_filters.get(name)

            try:
                score = indicator_inst.get_score(
                    enabled_sub_indicators=sub_filters,
                    aggregation=aggregation
                ).buy
            except TypeError:
                score = indicator_inst.get_score().buy

            components[name] = float(score)
            if aggregation == "product":
                total_score *= score
            else:
                total_score += score
            active_count += 1

        return total_score, components, active_count

    @staticmethod
    def calculate_baseline_score(
        days: pd.DataFrame,
        enabled_indicators: Optional[list[str]] = None,
        aggregation: str = "sum"
    ) -> Dict[str, float]:
        """
        Trend-following scoring: Rewards strength, momentum, and breakouts.
        'aggregation' can be 'sum' or 'product'.
        """
        if len(days) == 0:
            return {"total": 0.0}

        if TechnicalAnalyzer._is_dead_or_flat(days):
            return {"total": 0.0}

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

        total_score, components, active_count = TechnicalAnalyzer._score_indicators(
            days, indicator_filters, aggregation
        )

        if active_count == 0:
            total_score = 0.0

        # Only apply penalties and bonuses if we are running the full baseline
        if not enabled_indicators:
            mod_score, mod_components = TechnicalAnalyzer._calculate_baseline_modifiers(days)
            total_score += mod_score
            components.update(mod_components)

        components["total"] = float(total_score)
        return components

    @staticmethod
    def calculate_mean_reversion_score(
        days: pd.DataFrame,
        enabled_indicators: Optional[list[str]] = None,
        aggregation: str = "sum"
    ) -> Dict[str, float]:
        """
        Mean-reversion scoring using the standard indicator pipeline with MR weights.
        Negative-lift indicators (overextension signals) become buy signals for
        reversion opportunity detection.
        """
        if len(days) == 0:
            return {"total": 0.0}

        if TechnicalAnalyzer._is_dead_or_flat(days):
            return {"total": 0.0}

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

        # Use standard indicator pipeline with MR weight categories
        total_score, components, active_count = TechnicalAnalyzer._score_indicators(
            days, indicator_filters, aggregation, weight_prefix="mr_"
        )

        if active_count == 0:
            total_score = 0.0

        # Apply baseline modifiers (same penalties/bonuses)
        if not enabled_indicators:
            mod_score, mod_components = TechnicalAnalyzer._calculate_baseline_modifiers(days)
            total_score += mod_score
            components.update(mod_components)

        components["total"] = float(total_score)
        return components
