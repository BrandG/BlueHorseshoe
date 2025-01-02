"""
This module provides the MovingAverageIndicator class for calculating moving average crossover signals from financial data.

Classes:
    MovingAverageIndicator: A class to calculate moving average crossover signals from financial data.

Usage example:

    data = pd.DataFrame({'close': [1, 2, 3, 4, 5]})
    indicator = MovingAverageIndicator(data)
    signal = indicator.calculate_crossovers()
"""
import numpy as np
import pandas as pd

class MovingAverageIndicator: # pylint: disable=too-few-public-methods
    """
    A class to calculate moving average crossover signals from financial data.

    Attributes:
        data (pd.DataFrame): A pandas DataFrame containing the financial data with at least a 'close' column.

    Methods:
        calculate_crossovers():
    """

    def __init__(self, data: pd.DataFrame):
        required_cols = ['close', 'volume']
        self.data = data[required_cols].copy()

    def calculate_wma(self) -> pd.Series:
        """
        Calculates a Weighted Moving Average (WMA) for the given DataFrame.

        :param df:         DataFrame containing price data
        :param window:     Lookback period for the WMA (e.g., 20)
        :param price_col:  The column name containing prices (default 'Close')
        :return:           A Pandas Series containing the WMA
        """
        df = self.data
        # The weights are 1, 2, ..., window
        weights = np.arange(1, 20 + 1)

        # Use rolling apply with a custom function that does the weighted average
        def wma_function(x):
            return np.dot(x, weights) / weights.sum()

        wma_series = df['close'].rolling(window=20).apply(wma_function, raw=True)
        return wma_series

    def calculate_vwma(self) -> pd.Series:
        """
        Calculates a Volume-Weighted Moving Average (VWMA) over the specified window.

        :param df:          DataFrame with columns for price and volume
        :param window:      Lookback period (e.g., 20)
        :param price_col:   The column name for price (default 'Close')
        :param volume_col:  The column name for volume (default 'Volume')
        :return:            A Pandas Series for the VWMA
        """
        df = self.data
        # Rolling sum of (Price * Volume) / rolling sum of Volume
        pv = df['close'] * df['volume']
        rolling_pv = pv.rolling(window=20).sum()
        rolling_vol = df['volume'].rolling(window=20).sum() + 1e-10  # Avoid division by zero

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
        if len(self.data) < 1:
            return score  # Not enough data

        # Grab the last bar's values
        last_row = self.data.iloc[-1]
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
        data = self.data

        fast_ema = data['close'].ewm(span=9).mean()
        med_ema = data['close'].ewm(span=21).mean()
        slow_ema = (data['close'].ewm(span=50).mean() + data['close'].ewm(span=200).mean()) / 2

        return 1.0 if fast_ema[-1] > med_ema[-1] > slow_ema[-1] else 0.0

    def calculate_score(self) -> float:
        """
        Calculate the score based on the moving average crossover signals.

        This function calculates the moving average crossover signal and assigns a score based on the result.

        Returns:
            float: The score based on the moving average crossover signals.
        """

        return self.calculate_ma_score()
            # + self.calculate_crossovers()
