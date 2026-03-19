"""
detailed_scoring.py

Provides per-sub-indicator raw score collection for LOO weight analysis.
Wraps each indicator class to capture individual sub-indicator contributions
before weight multiplication, enabling mathematical reconstruction of
leave-one-out variants without re-running the full scoring pipeline.
"""

import logging
from typing import Dict, Tuple

import pandas as pd
from ta.volatility import AverageTrueRange

from bluehorseshoe.analysis.constants import (
    ATR_WINDOW, MIN_VOLUME_THRESHOLD
)
from bluehorseshoe.analysis.indicators.candlestick_indicators import CandlestickIndicator
from bluehorseshoe.analysis.indicators.limit_indicators import (
    LimitIndicator, PIVOT_MULTIPLIER, FIFTY_TWO_WEEK_MULTIPLIER
)
from bluehorseshoe.analysis.indicators.mean_reversion_indicators import MeanReversionIndicator
from bluehorseshoe.analysis.indicators.momentum_indicators import MomentumIndicator
from bluehorseshoe.analysis.indicators.moving_average_indicators import MovingAverageIndicator
from bluehorseshoe.analysis.indicators.price_action_indicators import PriceActionIndicator
from bluehorseshoe.analysis.indicators.trend_indicators import TrendIndicator
from bluehorseshoe.analysis.indicators.curve_indicators import CurveIndicator
from bluehorseshoe.analysis.indicators.volume_indicators import VolumeIndicator
from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer
from bluehorseshoe.core.config import weights_config


class DetailedScorer:
    """
    Scores all baseline sub-indicators individually, returning raw (unweighted)
    scores for each. This enables LOO reconstruction by subtracting any
    indicator's weighted contribution from the total.
    """

    # Maps indicator category → (class, weight_category, sub_map_style)
    # sub_map_style: 'weighted' = (func, weight_key), 'unweighted' = func, 'constant' = (func, constant)
    INDICATOR_CATEGORIES = {
        'trend': ('weighted', TrendIndicator, 'trend'),
        'momentum': ('weighted', MomentumIndicator, 'momentum'),
        'volume': ('weighted', VolumeIndicator, 'volume'),
        'candlestick': ('weighted', CandlestickIndicator, 'candlestick'),
        'moving_average': ('unweighted', MovingAverageIndicator, None),
        'limit': ('constant', LimitIndicator, None),
        'price_action': ('weighted', PriceActionIndicator, 'price_action'),
        'mean_reversion_specific': ('weighted', MeanReversionIndicator, 'mean_reversion_specific'),
        'curve': ('weighted', CurveIndicator, 'curve'),
    }

    @staticmethod
    def _get_sub_map(indicator_instance) -> dict:
        """
        Extract the sub_map from an indicator instance by inspecting
        its get_score method's local structure. We replicate the sub_map
        definitions here since they're defined inside get_score().
        """
        cls_name = type(indicator_instance).__name__

        if cls_name == 'TrendIndicator':
            inst = indicator_instance
            return {
                'stochastic': (inst.calculate_stochastic, 'STOCHASTIC_MULTIPLIER'),
                'ichimoku': (inst.calculate_ichimoku_score, 'ICHIMOKU_MULTIPLIER'),
                'psar': (inst.calculate_psar_score, 'PSAR_MULTIPLIER'),
                'heiken_ashi': (inst.calculate_heiken_ashi, 'HEIKEN_ASHI_MULTIPLIER'),
                'adx': (inst.calculate_dmi_adx, 'ADX_MULTIPLIER'),
                'donchian': (inst.calculate_donchian, 'DONCHIAN_MULTIPLIER'),
                'supertrend': (inst.calculate_supertrend, 'SUPERTREND_MULTIPLIER'),
                'ttm_squeeze': (inst.calculate_ttm_squeeze, 'TTM_SQUEEZE_MULTIPLIER'),
                'aroon': (inst.calculate_aroon, 'AROON_MULTIPLIER'),
                'keltner': (inst.calculate_keltner, 'KELTNER_MULTIPLIER'),
            }
        elif cls_name == 'MomentumIndicator':
            inst = indicator_instance
            return {
                'macd': (inst.calculate_macd, 'MACD_MULTIPLIER'),
                'roc': (inst.calculate_roc, 'ROC_MULTIPLIER'),
                'rsi': (inst.calculate_rsi, 'RSI_MULTIPLIER'),
                'bb_position': (inst.calculate_bb_position, 'BB_MULTIPLIER'),
                'williams_r': (inst.calculate_williams_r, 'WILLIAMS_R_MULTIPLIER'),
                'cci': (inst.calculate_cci, 'CCI_MULTIPLIER'),
            }
        elif cls_name == 'VolumeIndicator':
            inst = indicator_instance
            return {
                'obv': (inst.score_obv_trend, 'OBV_MULTIPLIER'),
                'cmf': (inst.calculate_cmf_with_ta, 'CMF_MULTIPLIER'),
                'atr_band': (inst.score_atr_band, 'ATR_BAND_MULTIPLIER'),
                'atr_spike': (inst.score_atr_spike, 'ATR_SPIKE_MULTIPLIER'),
                'avg_volume': (inst.calculate_avg_volume, None),
                'mfi': (inst.calculate_mfi, 'MFI_MULTIPLIER'),
                'vwap': (inst.calculate_vwap, 'VWAP_MULTIPLIER'),
                'force_index': (inst.calculate_force_index, 'FORCE_INDEX_MULTIPLIER'),
                'ad_line': (inst.calculate_ad_line, 'AD_LINE_MULTIPLIER'),
                'rvol': (inst.calculate_rvol, 'RVOL_MULTIPLIER'),
            }
        elif cls_name == 'CandlestickIndicator':
            inst = indicator_instance
            return {
                'soldiers': (inst.detect_three_white_soldiers, 'THREE_WHITE_SOLDIERS_MULTIPLIER'),
                'methods': (inst.find_rise_fall_3_methods, 'RISE_FALL_3_METHODS_MULTIPLIER'),
                'marubozu': (inst.find_marubozu, 'MARUBOZU_MULTIPLIER'),
                'belt_hold': (inst.find_belt_hold, 'BELT_HOLD_MULTIPLIER'),
                'engulfing': (inst.find_engulfing, 'ENGULFING_MULTIPLIER'),
                'hammer': (inst.find_hammer, 'HAMMER_MULTIPLIER'),
            }
        elif cls_name == 'MovingAverageIndicator':
            inst = indicator_instance
            return {
                'ma_score': (inst.calculate_ma_score, None),
                'crossovers': (inst.calculate_crossovers, None),
            }
        elif cls_name == 'LimitIndicator':
            inst = indicator_instance
            return {
                'pivot': (inst.score_pivot_levels, '_CONSTANT_'),
                '52_week': (inst.score_52_week_range, '_CONSTANT_'),
            }
        elif cls_name == 'PriceActionIndicator':
            inst = indicator_instance
            return {
                'gap': (inst.calculate_gap_score, 'GAP_MULTIPLIER'),
            }
        elif cls_name == 'MeanReversionIndicator':
            inst = indicator_instance
            return {
                'rsi_divergence': (inst.calculate_rsi_divergence, 'RSI_DIVERGENCE_MULTIPLIER'),
                'zscore': (inst.calculate_zscore, 'ZSCORE_MULTIPLIER'),
                'connors_rsi': (inst.calculate_connors_rsi, 'CONNORS_RSI_MULTIPLIER'),
                'dv2': (inst.calculate_dv2, 'DV2_MULTIPLIER'),
                'short_roc': (inst.calculate_short_roc, 'SHORT_ROC_MULTIPLIER'),
            }
        elif cls_name == 'CurveIndicator':
            inst = indicator_instance
            return {
                'motif_score': (lambda: inst.calculate_motif_score(40), 'MOTIF_SCORE_MULTIPLIER'),
            }
        return {}

    @staticmethod
    def _get_constant_multiplier(sub_name: str) -> float:
        """Get hard-coded multiplier for LimitIndicator sub-indicators."""
        if sub_name == 'pivot':
            return PIVOT_MULTIPLIER
        elif sub_name == '52_week':
            return FIFTY_TWO_WEEK_MULTIPLIER
        return 1.0

    @staticmethod
    def score_all_indicators(days: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, float], float]:
        """
        Score all baseline sub-indicators, returning raw and weighted scores.

        Args:
            days: DataFrame with OHLCV + indicator columns for a single symbol.

        Returns:
            Tuple of:
            - raw_scores: {category.sub_indicator: raw_score} (before weight multiplication)
            - weighted_scores: {category.sub_indicator: weighted_score} (after weight multiplication)
            - total_score: sum of all weighted scores + baseline modifiers
        """
        if len(days) == 0:
            return {}, {}, 0.0

        if TechnicalAnalyzer._is_dead_or_flat(days):
            return {}, {}, 0.0

        raw_scores = {}
        weighted_scores = {}
        total = 0.0

        # Score each indicator category
        category_configs = {
            'trend': (TrendIndicator, 'trend'),
            'momentum': (MomentumIndicator, 'momentum'),
            'volume': (VolumeIndicator, 'volume'),
            'candlestick': (CandlestickIndicator, 'candlestick'),
            'moving_average': (MovingAverageIndicator, None),
            'limit': (LimitIndicator, None),
            'price_action': (PriceActionIndicator, 'price_action'),
            'mean_reversion_specific': (MeanReversionIndicator, 'mean_reversion_specific'),
        }

        for category, (cls, weight_category) in category_configs.items():
            try:
                indicator_inst = cls(days)
            except (ValueError, Exception) as e:
                logging.debug("Failed to create %s: %s", category, e)
                continue

            sub_map = DetailedScorer._get_sub_map(indicator_inst)
            if not sub_map:
                continue

            # Load weights for this category
            weights = {}
            if weight_category:
                weights = weights_config.get_weights(weight_category)

            for sub_name, (func, weight_key) in sub_map.items():
                try:
                    raw_score = float(func())
                except Exception as e:
                    logging.debug("Failed to score %s.%s: %s", category, sub_name, e)
                    raw_score = 0.0

                key = f"{category}.{sub_name}"
                raw_scores[key] = raw_score

                # Calculate weighted score
                if weight_key is None:
                    # No weight (moving_average) - raw score is the weighted score
                    multiplier = 1.0
                elif weight_key == '_CONSTANT_':
                    # Hard-coded constant (limit)
                    multiplier = DetailedScorer._get_constant_multiplier(sub_name)
                else:
                    multiplier = weights.get(weight_key, 1.0)

                w_score = raw_score * multiplier
                weighted_scores[key] = w_score
                total += w_score

        # Add baseline modifiers (penalties/bonuses)
        mod_score, mod_components = TechnicalAnalyzer._calculate_baseline_modifiers(days)
        for mod_name, mod_value in mod_components.items():
            if mod_value != 0.0:
                key = f"modifier.{mod_name}"
                raw_scores[key] = mod_value
                weighted_scores[key] = mod_value
        total += mod_score

        return raw_scores, weighted_scores, total

    @staticmethod
    def get_setup_data(days: pd.DataFrame) -> Dict[str, float]:
        """
        Extract setup data needed for LOO reconstruction of entry/stop/target.

        Args:
            days: DataFrame with OHLCV + indicator columns.

        Returns:
            Dict with close, atr, swing_low_5, swing_high_20 values.
        """
        last_row = days.iloc[-1]

        # ATR
        if 'ATR' not in days.columns:
            days = days.copy()
            days['ATR'] = AverageTrueRange(
                high=days['high'],
                low=days['low'],
                close=days['close'],
                window=ATR_WINDOW
            ).average_true_range()
        atr = days['ATR'].values[-1]
        if pd.isna(atr):
            atr = last_row['close'] * 0.02

        return {
            'close': float(last_row['close']),
            'atr': float(atr),
            'swing_low_5': float(days['low'].rolling(window=5).min().iloc[-1]),
            'swing_high_20': float(days['high'].rolling(window=20).max().iloc[-1]),
        }
