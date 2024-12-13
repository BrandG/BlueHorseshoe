"""
Module: standard_deviation

This module provides the StandardDeviation class for calculating and analyzing the standard deviation of stock prices.
It uses the TA-Lib library to compute the standard deviation and provides methods to update the data, retrieve the 
current standard deviation value, and graph the standard deviation along with the stock's closing prices.

Classes:
    StandardDeviation: A class to calculate and analyze the standard deviation of stock prices.
"""
import pandas as pd
import talib as ta

from globals import GraphData, graph


class StandardDeviation:
    """
    A class to calculate and analyze the standard deviation of stock prices.

    Attributes:
        _data (pd.DataFrame): The stock price data.
        _std_deviation (pd.Series): The calculated standard deviation of the stock prices.

    Methods:
        __init__(data):
            Initializes the StandardDeviation instance with the provided data.

        update(data, period=20):
            Updates the stock price data and recalculates the standard deviation for the given period.

        value:
            Returns the current standard deviation value and the volatility level ('high' or 'low').

        graph():
            Plots the standard deviation and the stock's closing prices on a graph.
    """

    def __init__(self, data):
        """
        Initializes the StandardDeviation instance with the provided data.

        Args:
            data (list or array-like): The data set for which the standard deviation will be calculated.
        """
        self.update(data)

    def update(self, data, period=20):
        """
        Updates the standard deviation indicator with new data.

        Args:
            data (pd.DataFrame): A DataFrame containing the price data with at least a 'close' column.
            period (int, optional): The time period over which to calculate the standard deviation. Defaults to 20.

        Returns:
            None
        """
        self._data = data

        self._std_deviation = ta.STDDEV(self._data['close'], timeperiod=period) # type: ignore

    @property
    def value(self):
        """
        Calculate the current standard deviation and determine the volatility level.

        Returns:
            dict: A dictionary containing:
                - 'current_stdev' (float): The current standard deviation.
                - 'volatility' (str): The volatility level, either 'high' or 'low', 
                  based on whether the current standard deviation is above or below 
                  the mean standard deviation.
        """
        current_volatility = float(self._std_deviation.iloc[-1])
        volatility_level = 'high' if current_volatility > self._std_deviation.mean() else 'low'

        return {'current_stdev': current_volatility, 'volatility': volatility_level}

    # pylint: disable=unused-variable
    def graph(self):
        """
        Generates and displays a graph of the standard deviation and closing prices of the data.

        The graph will have the following characteristics:
        - X-axis: Dates formatted as 'YYYY-MM'.
        - Y-axis: Percentage values.
        - Title: 'Standard Deviation'.
        - Two curves:
            - Standard Deviation (normalized and colored orange).
            - Closing Prices (normalized and colored green).

        The data for the graph is derived from the instance's `_data` and `_std_deviation` attributes.

        Returns:
            None
        """
        price_data = (self._data['close'] / self._data['close'].max()).tolist()
        stdev_list = (self._std_deviation / self._std_deviation.max()).tolist()
        x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
        graph(GraphData(x_label='Date', y_label='Percentage', title='Standard Deviation',
                            x_values=x_values, curves=[{'curve': stdev_list, 'label': 'stDev', 'color':'orange'},
                                                        {'curve': price_data, 'label': 'Close', 'color': 'green'}
                                                        ]))
