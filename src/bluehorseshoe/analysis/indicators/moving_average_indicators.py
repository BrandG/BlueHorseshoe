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

    def calculate_wma(self) -> pd.Series:
        """
        Calculates a Weighted Moving Average (WMA) using vectorized numpy convolution.

        :return: A Pandas Series containing the WMA
        """
        window = 20
        weights = np.arange(1, window + 1, dtype=float)
        weights /= weights.sum()

        close = self.days['close'].values
        if len(close) < window:
            return pd.Series(np.full(len(close), np.nan), index=self.days.index)

        wma = np.convolve(close, weights[::-1], mode='valid')

        result = np.full(len(close), np.nan)
        result[window - 1:] = wma
        return pd.Series(result, index=self.days.index)

    def calculate_vwma(self) -> pd.Series:
        """
        Calculates a Volume-Weighted Moving Average (VWMA) over the specified window.

        :param df:          DataFrame with columns for price and volume
        :param window:      Lookback period (e.g., 20)
        :param price_col:   The column name for price (default 'Close')
        :param volume_col:  The column name for volume (default 'Volume')
        :return:            A Pandas Series for the VWMA
        """
        # Rolling sum of (Price * Volume) / rolling sum of Volume
        pv = self.days['close'] * self.days['volume']
        rolling_pv = pv.rolling(window=20).sum()
        rolling_vol = self.days['volume'].rolling(window=20).sum() + 1e-10  # Avoid division by zero

        return rolling_pv / rolling_vol

    def calculate_ma_score(self) -> float:
        """
        Example scoring function that:
        1) Calculates a 20-bar WMA
        2) Calculates a 20-bar VWMA
        3) Scores how the last bar's 'Close' relates to these weighted averages
        """
        score = 0.0

        # 1) Calculate WMA over last 20 bars
        wma_20 = self.calculate_wma()

        # 2) Calculate VWMA over last 20 bars
        vwma_20 = self.calculate_vwma()

        # We'll examine the latest row (if it exists)
        if len(self.days) < 1:
            return score  # Not enough data

        # Grab the last bar's values
        last_row = self.days.iloc[-1]
        close_price = last_row['close']

        # 3) Score logic: +1 if above WMA, +1 if above VWMA
        if pd.notna(wma_20.iloc[-1]):
            if close_price > wma_20.iloc[-1]:
                score += 1
            else:
                score -= 1  # or 0, depending on your preference

        if pd.notna(vwma_20.iloc[-1]):
            if close_price > vwma_20.iloc[-1]:
                score += 1
            else:
                score -= 1  # or 0

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
