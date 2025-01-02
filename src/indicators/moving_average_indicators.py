"""
This module provides the MovingAverageIndicator class for calculating moving average crossover signals from financial data.

Classes:
    MovingAverageIndicator: A class to calculate moving average crossover signals from financial data.

Usage example:

    data = pd.DataFrame({'close': [1, 2, 3, 4, 5]})
    indicator = MovingAverageIndicator(data)
    signal = indicator.calculate_crossovers()
"""
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
        self.data = data

    def calculate_crossovers(self):
        """
        Calculate the crossover signals based on Exponential Moving Averages (EMAs).

        This function computes three EMAs (fast, medium, and slow) from the 'close' prices in the data.
        It then determines if a crossover has occurred where the fast EMA is greater than the medium EMA,
        and the medium EMA is greater than the slow EMA.

        Returns:
            float: 1.0 if the fast EMA is greater than the medium EMA and the medium EMA is greater than the slow EMA, otherwise 0.0.
        """
        data = self.data.copy()

        fast_ema = data['close'].ewm(span=9).mean()
        med_ema = data['close'].ewm(span=21).mean()
        slow_ema = (data['close'].ewm(span=50).mean() + data['close'].ewm(span=200).mean()) / 2

        return 1.0 if fast_ema > med_ema > slow_ema else 0.0
