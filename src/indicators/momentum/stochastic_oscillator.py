"""
This module contains the implementation of the Stochastic Oscillator indicator
using the TA-Lib library. The Stochastic Oscillator is a momentum indicator
comparing a particular closing price of a security to a range of its prices
over a certain period of time.

Classes:
    StochasticOscillator: A class to calculate and provide signals based on
                          the Stochastic Oscillator indicator.
"""
import talib as ta
from globals import ReportSingleton
from indicators.indicator import Indicator


class StochasticOscillator(Indicator):
    """
    A class to represent the Stochastic Oscillator indicator.

    Attributes:
        _data (DataFrame): The input data containing 'high', 'low', and 'close' prices.
        _slowk (numpy.ndarray): The %K values of the Stochastic Oscillator.
        _slowd (numpy.ndarray): The %D values of the Stochastic Oscillator.

    Methods:
        __init__(data):
            Initializes the StochasticOscillator with the provided data.
        
        update(data):
            Updates the Stochastic Oscillator values with the new data.
        
        value:
            Provides the current buy, sell, or hold signal based on the Stochastic Oscillator values.
        
        graph():
            Placeholder method to generate a graph of the Stochastic Oscillator values.
    """

    def __init__(self, data):
        """
        Initializes the Stochastic Oscillator with the provided data.

        Args:
            data (list or pandas.DataFrame): The input data for the Stochastic Oscillator.
        """
        self.update(data)

    def update(self, data):
        """
        Update the stochastic oscillator with new market data.

        Parameters:
        data (dict): A dictionary containing 'high', 'low', and 'close' price data.
                 The keys should be strings and the values should be lists or arrays of prices.

        Updates:
        self._data: Stores the input data.
        self._slowk: The %K line of the stochastic oscillator.
        self._slowd: The %D line of the stochastic oscillator.
        """
        self._data = data
        self._slowk, self._slowd = ta.STOCH(self._data['high'], self._data['low'], self._data['close'],  # type: ignore
                                fastk_period=5, slowk_period=3, slowk_matype=0,
                                slowd_period=3, slowd_matype=0)

    @property
    def value(self):
        """
        Determines the trading signal based on the stochastic oscillator values.

        The method compares the current and previous values of the %K (slowk) and %D (slowd) lines
        to generate a trading signal. It returns a dictionary indicating whether to buy, sell, or hold.

        Returns:
            dict: A dictionary with keys 'buy', 'sell', and 'hold', each mapped to a boolean value.
              - 'buy': True if %K crosses above %D, otherwise False.
              - 'sell': True if %K crosses below %D, otherwise False.
              - 'hold': True if there is no crossover signal, otherwise False.
        """
        slowd_list = self._slowd.tolist()
        slowk_list = self._slowk.tolist()

        buy = sell = hold = False
        if slowk_list[-1] > slowd_list[-1] and slowk_list[-2] <= slowd_list[-2]:
            buy = True
        elif slowk_list[-1] < slowd_list[-1] and slowk_list[-2] >= slowd_list[-2]:
            sell = True
        else:
            hold = True
        return {'buy': buy, 'sell': sell, 'hold': hold}

    # pylint: disable=unused-variable
    def graph(self):
        """
        Generates a graph for the stochastic oscillator and writes the values of slowd and slowk to the report.

        To Do:
            Implement the graph generation logic.

        Writes:
            str: The values of slowd and slowk to the report.
        """
        # To Do: Fill this in
        ReportSingleton().write(f'{self._slowd}, {self._slowk}')
