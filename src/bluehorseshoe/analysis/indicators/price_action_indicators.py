"""
price_action_indicators.py

This module contains the PriceActionIndicator class, which calculates price action-based
technical indicators using daily stock data. Currently implements Gap Analysis.

Classes:
    PriceActionIndicator: A class to calculate price action indicators.

Methods:
    calculate_gap_score() -> float: Analyzes overnight gaps with volume confirmation
    get_score() -> IndicatorScore: Returns aggregated price action score
"""

from typing import Optional
import numpy as np
import pandas as pd

from bluehorseshoe.analysis.indicators.indicator import Indicator, IndicatorScore
from bluehorseshoe.core.config import weights_config


class PriceActionIndicator(Indicator):
    """
    PriceActionIndicator

    A class to calculate price action-based technical indicators using daily OHLCV data.
    Currently implements Gap Analysis to detect overnight gaps and volume confirmation.

    Gap Analysis is powerful for swing trading because:
    - Many breakouts start with gap-ups
    - Gaps with volume indicate institutional buying
    - Gap direction shows momentum shift
    """

    def __init__(self, data: pd.DataFrame):
        self.weights = weights_config.get_weights('price_action')
        self.required_cols = ['open', 'close', 'volume']
        super().__init__(data)

    def calculate_gap_score(self) -> float:
        """
        Calculate Gap Analysis score based on overnight gap and volume confirmation.

        Gap Analysis measures the difference between today's open and yesterday's close.
        A gap-up with strong volume suggests institutional accumulation and breakout potential.
        A gap-down suggests institutional distribution and potential weakness.

        Scoring Logic:
        - Gap up >2% with volume >1.5x average = +2.0 (strong breakout)
        - Gap up >1% with volume >1.2x average = +1.0 (moderate breakout)
        - Gap up >0.5% = +0.5 (small gap, neutral)
        - Gap down >2% = -2.0 (strong weakness)
        - Gap down >1% = -1.0 (moderate weakness)
        - No significant gap = 0.0

        Returns:
            float: Score from -2.0 to +2.0 based on gap size and volume
        """
        if len(self.days) < 21:  # Need 20 days for volume average + 1 for gap
            return 0.0

        # Get today's open and yesterday's close
        today_open = self.days['open'].iloc[-1]
        yesterday_close = self.days['close'].iloc[-2]

        # Calculate gap percentage
        gap_pct = ((today_open - yesterday_close) / yesterday_close) * 100

        # Calculate volume confirmation
        today_volume = self.days['volume'].iloc[-1]
        avg_volume_20 = self.days['volume'].iloc[-21:-1].mean()  # Last 20 days (excluding today)
        volume_ratio = today_volume / avg_volume_20 if avg_volume_20 > 0 else 1.0

        # Score gap-ups (bullish)
        if gap_pct > 2.0:
            # Strong gap up
            if volume_ratio > 1.5:
                return 2.0  # Strong gap with strong volume = institutional buying
            elif volume_ratio > 1.2:
                return 1.5  # Strong gap with moderate volume
            else:
                return 1.0  # Strong gap but weak volume (less reliable)

        elif gap_pct > 1.0:
            # Moderate gap up
            if volume_ratio > 1.2:
                return 1.0  # Moderate gap with good volume
            else:
                return 0.5  # Moderate gap with normal volume

        elif gap_pct > 0.5:
            # Small gap up
            return 0.5

        # Score gap-downs (bearish)
        elif gap_pct < -2.0:
            # Strong gap down = weakness
            return -2.0

        elif gap_pct < -1.0:
            # Moderate gap down
            return -1.0

        elif gap_pct < -0.5:
            # Small gap down
            return -0.5

        # No significant gap
        return 0.0

    def get_score(self, enabled_sub_indicators: Optional[list[str]] = None, aggregation: str = "sum") -> IndicatorScore:
        """
        Compute the overall buy and sell scores derived from price action indicators.

        Currently only implements Gap Analysis. Future price action indicators could include:
        - Inside bars
        - Outside bars
        - Key reversal patterns
        - Range expansion/contraction

        Args:
            enabled_sub_indicators: List of sub-indicators to enable (default: all)
            aggregation: How to combine scores - "sum" or "product" (default: sum)

        Returns:
            IndicatorScore: Named tuple with buy_score and sell_score
        """
        buy_score = 1.0 if aggregation == "product" else 0.0
        active_count = 0

        # Mapping of sub-indicator names to their calculation methods and weight keys
        sub_map = {
            'gap': (self.calculate_gap_score, 'GAP_MULTIPLIER'),
        }

        for name, (func, weight_key) in sub_map.items():
            if enabled_sub_indicators is None or name in enabled_sub_indicators:
                multiplier = self.weights[weight_key] if weight_key else 1.0
                if multiplier == 0.0:
                    continue  # Skip calculation if multiplier is zero
                score = func() * multiplier  # pylint: disable=not-callable
                if aggregation == "product":
                    buy_score *= score
                else:
                    buy_score += score
                active_count += 1

        if active_count == 0 or (aggregation == "product" and buy_score == 0):
            buy_score = 0.0

        sell_score = 0.0
        return IndicatorScore(buy_score, sell_score)

    def graph(self):
        """Reserved for visualizing gap analysis."""
        pass
