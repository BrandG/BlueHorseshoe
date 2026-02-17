"""
This module provides the MovingAverageIndicator class for calculating moving average crossover signals from financial data.

Classes:
    MovingAverageIndicator: A class to calculate moving average crossover signals from financial data.

Usage example:

    data = pd.DataFrame({'close': [1, 2, 3, 4, 5]})
    indicator = MovingAverageIndicator(data)
    signal = indicator.calculate_crossovers()
"""
from typing import Optional
import numpy as np
import pandas as pd

from bluehorseshoe.analysis.indicators.indicator import Indicator, IndicatorScore

class MovingAverageIndicator(Indicator):
    """
    A class to calculate moving average crossover signals from financial data.

    Attributes:
        data (pd.DataFrame): A pandas DataFrame containing the financial data with at least a 'close' column.

    Methods:
        calculate_crossovers():
    """

    def __init__(self, data: pd.DataFrame):
        self.required_cols = ['close', 'volume']
        super().__init__(data)

    def calculate_wma(self, window: int = 20) -> float:
        """
        Calculates the current Weighted Moving Average (WMA) value.

        :param window: Lookback period for the WMA (default 20)
        :return:       The WMA value for the most recent bar, or NaN if insufficient data
        """
        if len(self.days) < window:
            return float('nan')

        close = self.days['close'].values[-window:]
        weights = np.arange(1, window + 1, dtype=float)
        return np.dot(close, weights) / weights.sum()

    def calculate_vwma(self, window: int = 20) -> float:
        """
        Calculates the current Volume-Weighted Moving Average (VWMA) value.

        :param window: Lookback period (default 20)
        :return:       The VWMA value for the most recent bar, or NaN if insufficient data
        """
        if len(self.days) < window:
            return float('nan')

        close = self.days['close'].values[-window:]
        volume = self.days['volume'].values[-window:]
        vol_sum = volume.sum()
        if vol_sum == 0:
            return float('nan')
        return (close * volume).sum() / vol_sum

    def calculate_ma_score(self) -> float:
        """
        Scoring function that:
        1) Calculates a 20-bar WMA
        2) Calculates a 20-bar VWMA
        3) Scores how the last bar's close relates to these weighted averages
        """
        score = 0.0
        close_price = self.days['close'].values[-1]

        wma_val = self.calculate_wma()
        if not np.isnan(wma_val):
            score += 1.0 if close_price > wma_val else -1.0

        vwma_val = self.calculate_vwma()
        if not np.isnan(vwma_val):
            score += 1.0 if close_price > vwma_val else -1.0

        return score

    def calculate_crossovers(self) -> float:
        """
        Calculate the crossover signals based on Exponential Moving Averages (EMAs).

        This function computes three EMAs (fast, medium, and slow) from the 'close' prices in the data.
        It then determines if a crossover has occurred where the fast EMA is greater than the medium EMA,
        and the medium EMA is greater than the slow EMA.

        Returns:
            float: 1.0 if the fast EMA is greater than the medium EMA and the medium EMA is greater than the slow EMA, otherwise 0.0.
        """
        fast_ema = self.days['close'].ewm(span=9).mean()
        med_ema = self.days['close'].ewm(span=21).mean()
        slow_ema = (self.days['close'].ewm(span=50).mean() + self.days['close'].ewm(span=200).mean()) / 2

        if not fast_ema.empty and not med_ema.empty and not slow_ema.empty:
            return 1.0 if fast_ema.iloc[-1] > med_ema.iloc[-1] > slow_ema.iloc[-1] else 0.0
        return 0.0

    def get_score(self, enabled_sub_indicators: Optional[list[str]] = None, aggregation: str = "sum") -> IndicatorScore:
        """
        Calculate the score based on the moving average crossover signals.
        """
        buy_score = 1.0 if aggregation == "product" else 0.0
        active_count = 0

        sub_map = {
            'ma_score': self.calculate_ma_score,
            'crossovers': self.calculate_crossovers
        }

        for name, func in sub_map.items():
            if enabled_sub_indicators is None or name in enabled_sub_indicators:
                score = func()
                if aggregation == "product":
                    buy_score *= score
                else:
                    buy_score += score
                active_count += 1

        if active_count == 0 or (aggregation == "product" and buy_score == 0):
            buy_score = 0.0

        sell_score = 0.0
        return IndicatorScore(buy_score, sell_score)

    def graph(self) -> None:
        pass
