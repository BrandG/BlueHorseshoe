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
from datetime import datetime
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
        if len(data['close'].to_list()) <= 2:
            return {'buy': 0, 'sell': 0}
        high_9 = data['high'].rolling(window=9).max()
        low_9 = data['low'].rolling(window=9).min()
        self._ichimoku_df['tenkan_sen'] = (high_9 + low_9) / 2
        if len(self._ichimoku_df['tenkan_sen'].to_list()) <= 2:
            return {'buy': 0, 'sell': 0}

        high_26 = data['high'].rolling(window=26).max()
        low_26 = data['low'].rolling(window=26).min()
        self._ichimoku_df['kijun_sen'] = (high_26 + low_26) / 2
        if len(self._ichimoku_df['kijun_sen'].to_list()) <= 2:
            return {'buy': 0, 'sell': 0}

        self._ichimoku_df['senkou_span_a'] = ((self._ichimoku_df['tenkan_sen'] + self._ichimoku_df['kijun_sen']) / 2).shift(26)
        if len(self._ichimoku_df['senkou_span_a'].to_list()) <= 2:
            return {'buy': 0, 'sell': 0}

        high_52 = data['high'].rolling(window=52).max()
        low_52 = data['low'].rolling(window=52).min()
        self._ichimoku_df['senkou_span_b'] = ((high_52 + low_52) / 2).shift(26)
        if len(self._ichimoku_df['senkou_span_a'].to_list()) <= 2:
            return {'buy': 0, 'sell': 0}

        # pad the front of the data['close'] dataframe with NaNs to align with the Ichimoku data
        data['close'] = pd.concat([pd.Series([np.nan]*52), data['close']]).reset_index(drop=True)
        self._ichimoku_df['chikou_span'] = data['close'].shift(-26)
        if len(self._ichimoku_df['senkou_span_a'].to_list()) <= 2:
            return {'buy': 0, 'sell': 0}

        buy = sell = 0
        last_price = data['close'].iloc[-1]
        last_baseline = self._ichimoku_df['kijun_sen'].iloc[-1]
        last_conversion = self._ichimoku_df['tenkan_sen'].iloc[-1]
        last_senkou_span_a = kumo_a = self._ichimoku_df['senkou_span_a'].iloc[-1]
        last_senkou_span_b = kumo_b = self._ichimoku_df['senkou_span_b'].iloc[-1]
        last_lagging_span = self._ichimoku_df['chikou_span'].iloc[-1]
        kumo_top = max(kumo_a, kumo_b)
        kumo_bottom = min(kumo_a, kumo_b)

        lagging_crosses_price_up = self._ichimoku_df['chikou_span'].iloc[-2] < data['close'].iloc[-2] and \
                                last_lagging_span > last_price
        lagging_crosses_price_down = self._ichimoku_df['chikou_span'].iloc[-2] > data['close'].iloc[-2] and \
                                last_lagging_span < last_price

        buy += 1 if last_price > kumo_top else 0 + \
            2 if (last_price > kumo_top) and lagging_crosses_price_up else 0 + \
            1 if last_price > last_conversion else 0 + \
            1 if last_price > last_baseline else 0 + \
            1 if last_conversion > kumo_top and last_baseline > kumo_top else 0 + \
            1 if last_senkou_span_a > last_senkou_span_b else 0 + \
            1 if last_conversion > last_baseline and last_baseline > kumo_top else 0 + \
            1 if last_lagging_span > kumo_top else 0 + \
            1 if last_lagging_span > last_price else 0 + \
            1 if last_lagging_span > last_baseline else 0

        # # I don't know how to use this yet.
        # strength = abs(kumo_a - kumo_b)
        # strength = last_price - last_conversion

        sell += 1 if last_price < kumo_bottom else 0 + \
            2 if (last_price < kumo_bottom) and lagging_crosses_price_down else 0 + \
            1 if last_price < last_conversion else 0 + \
            1 if last_price < last_baseline else 0 + \
            1 if last_conversion < kumo_bottom and last_baseline < kumo_bottom else 0 + \
            1 if last_senkou_span_a < last_senkou_span_b else 0 + \
            1 if last_conversion < last_baseline and last_baseline < kumo_bottom else 0 + \
            1 if last_lagging_span < kumo_bottom else 0 + \
            1 if last_lagging_span < last_price else 0 + \
            1 if last_lagging_span < last_baseline else 0

        return {'buy': buy, 'sell': sell}

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
        plt.plot(self._data['close'].index, data['close'], label='Price')
        plt.plot(self._ichimoku_df.index, self._ichimoku_df['tenkan_sen'], label='tenkan_sen (Conversion)', color='orange')
        plt.plot(self._ichimoku_df.index, self._ichimoku_df['kijun_sen'], label='kijun_sen (Base Line)', color='gray')
        plt.plot(self._ichimoku_df.index, self._ichimoku_df['chikou_span'], label='chikou_span (Lagging Span)', color='purple')
        plt.plot(self._ichimoku_df.index, self._ichimoku_df['senkou_span_a'], label='Senkou Span A', color='blue')
        plt.plot(self._ichimoku_df.index, self._ichimoku_df['senkou_span_b'], label='Senkou Span B', color='red')
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
        current_time_ms = int(datetime.now().timestamp() * 1000)
        plt.savefig(f'/workspaces/BlueHorseshoe/src/graphs/Ichimoku_{current_time_ms}.png')
