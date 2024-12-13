"""
Ichimoku Cloud Indicator

This module contains the Ichimoku class which calculates the Ichimoku Cloud components for a given dataset.
The Ichimoku Cloud is a technical analysis indicator that defines support and resistance, identifies trend direction,
gauges momentum, and provides trading signals.

Classes:
    Ichimoku: A class to calculate and plot the Ichimoku Cloud components.

Usage example:
    data = pd.DataFrame({
        'high': [high_values],
        'low': [low_values],
        'close': [close_values]
    ichimoku = Ichimoku(data)
    results = ichimoku.get_results(show=True)
"""
from matplotlib import pyplot as plt
import numpy as np
import pandas as pd

class Ichimoku:
    """
    A class to calculate and visualize the Ichimoku Cloud components for a given dataset.


    Attributes:
        _data (pd.DataFrame): The input data containing 'high', 'low', and 'close' prices.
        _ichimoku_df (pd.DataFrame): A DataFrame to store the calculated Ichimoku Cloud components.

    Methods:
        get_results(show=False):
            Calculate the Ichimoku Cloud components and optionally plot the results.
            Returns a dictionary with 'buy', 'sell', and 'strength' signals.

        graph_this():
            Plot the Ichimoku Cloud components along with the closing prices.
    """

    def __init__(self, data):
        self._data = data
        self._ichimoku_df = pd.DataFrame()

    @property
    def value(self):
        """
        Args:
            show (bool): If True, the function will call `graph_this` to plot the Ichimoku Cloud.

            dict: A dictionary containing:
            - 'buy' (bool): True if Senkou Span A is above Senkou Span B, indicating a buy signal.
            - 'sell' (bool): True if Senkou Span A is below Senkou Span B, indicating a sell signal.
            - 'strength' (float): The absolute difference between Senkou Span A and Senkou Span B, rounded to 2 decimal places.

        Returns:
            None
                 
        Calculate the Ichimoku Cloud components for the given data.

        The Ichimoku Cloud is a technical analysis indicator that defines support and resistance,
        identifies trend direction, gauges momentum, and provides trading signals.

        This function calculates the following components:
        - Tenkan-sen (Conversion Line)
        - Kijun-sen (Base Line)
        - Senkou Span A (Leading Span A)
        - Senkou Span B (Leading Span B)

        The function also includes a nested function `graph_this` to plot the Ichimoku Cloud,
        but it is not called within this function.

        """

        data=self._data
        high_9 = data['high'].rolling(window=9).max()
        low_9 = data['low'].rolling(window=9).min()
        tenkan_sen = (high_9 + low_9) / 2

        high_26 = data['high'].rolling(window=26).max()
        low_26 = data['low'].rolling(window=26).min()
        kijun_sen = (high_26 + low_26) / 2

        senkou_span_a = (tenkan_sen + kijun_sen) / 2

        high_52 = data['high'].rolling(window=52).max()
        low_52 = data['low'].rolling(window=52).min()
        senkou_span_b = (high_52 + low_52) / 2

        # Add 26 entries to the front of the data['close'] dataframe
        data['close'] = pd.concat([pd.Series([np.nan]*13), data['close']]).reset_index(drop=True)

        return {'buy': bool(senkou_span_a.iloc[-1] > senkou_span_b.iloc[-1]),
                'sell': bool(senkou_span_a.iloc[-1] < senkou_span_b.iloc[-1]),
                'strength': float(abs(senkou_span_a.iloc[-1] - senkou_span_b.iloc[-1]).round(2))}

    # pylint: disable=unused-variable
    def graph(self):
        """
        Generates and saves a plot of the Ichimoku indicator along with the closing prices.

        The plot includes:
        - Closing prices
        - Senkou Span A
        - Senkou Span B
        - A shaded area between Senkou Span A and Senkou Span B, colored light green if
            Senkou Span A is above Senkou Span B, and light coral if Senkou Span A is below
            Senkou Span B.

        The plot is saved as 'Ichimoku.png' in the 'graphs' directory.
        """
        data=self._data

        plt.figure(figsize=(14, 7))
        plt.plot(data.index, data['close'], label='Close')
        plt.plot(self._ichimoku_df.index, self._ichimoku_df['senkou_span_a'], label='Senkou Span A')
        plt.plot(self._ichimoku_df.index, self._ichimoku_df['senkou_span_b'], label='Senkou Span B')
        plt.fill_between(
            self._ichimoku_df.index,
            self._ichimoku_df['senkou_span_a'],
            self._ichimoku_df['senkou_span_b'],
            where=(self._ichimoku_df['senkou_span_a'] >= self._ichimoku_df['senkou_span_b']).tolist(),
            color='lightgreen', alpha=0.5)
        plt.fill_between(
            self._ichimoku_df.index,
            self._ichimoku_df['senkou_span_a'],
            self._ichimoku_df['senkou_span_b'],
            where=(self._ichimoku_df['senkou_span_a'] < self._ichimoku_df['senkou_span_b']).tolist(),
            color='lightcoral', alpha=0.5)
        plt.legend()
        plt.savefig('graphs/Ichimoku.png')
