"""
Module: short_term_trend
This module provides the ShortTermTrend class for analyzing short-term trends in financial data.
It includes methods for calculating Exponential Moving Averages (EMAs) and Pivot Points, and generating buy/sell signals based on these indicators.
Classes:
    ShortTermTrend: A class for analyzing short-term trends using EMAs and Pivot Points.
Methods:
    __init__(data): Initializes the ShortTermTrend class with the provided data.
    get_ema_signals(show=False): Determines buy/sell signals based on the 5-day and 20-day EMAs.
    get_pivot_points(show=False): Calculates pivot points and support/resistance levels.
"""

import pandas as pd
import talib as ta
from globals import GraphData, graph

class ShortTermTrend:
    """
    A class to analyze short-term trends in financial data using technical indicators.
    Attributes:
        data (pd.DataFrame): A DataFrame containing the financial data with columns 'close', 'high', 'low', and 'date'.
    Methods:
        get_ema_signals(show=False):
            Optionally, display a graph of the EMAs and buy/sell points.
        get_pivot_points(show=False):
            Optionally, display a graph of the pivot points and buy/sell points.
    """

    def __init__(self, data):
        self._data = data

    # 5/20 exponential moving averages
    def get_ema_signals(self, show = False):
        """
        Args:
            show (bool): If True, displays a graph of the EMAs and buy/sell points. Default is False.

        Determine buy/sell signals based on the 5-day and 20-day Exponential Moving Averages (EMAs).
        If the 'show' parameter is set to True, a graph of the EMAs and the buy/sell points will be displayed.

        Returns:
            dict: A dictionary containing 'buy' and 'sell' signals.
                'buy' is True when the 5-day EMA crosses above the 20-day EMA.
                'sell' is True when the 5-day EMA crosses below the 20-day EMA.
        """
        ema_5 = ta.EMA(self._data['close'], timeperiod=5) # type: ignore
        ema_20 = ta.EMA(self._data['close'], timeperiod=20) # type: ignore

        # pylint: disable=unused-variable
        def graph_this(ema_5, ema_20):
            ema_5_list = ema_5.tolist()
            ema_20_list = ema_20.tolist()

            buy_points = []
            sell_points = []
            for i in range(len(self._data['close'])):
                if ema_5_list[i] > ema_20_list[i] and ema_5_list[i-1] <= ema_20_list[i-1]:
                    buy_points.append({'x': i, 'y': self._data['close'].iloc[i-1], 'color': 'green'})
                elif ema_5_list[i] < ema_20_list[i] and ema_5_list[i-1] >= ema_20_list[i-1]:
                    sell_points.append({'x': i, 'y': self._data['close'].iloc[i-1], 'color': 'red'})
            points = buy_points + sell_points

            x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
            graph(GraphData(x_label='Date',
                y_label='Price',
                title='EMAs',
                x_values=x_values,
                curves=[
                    {'curve': self._data['close'].tolist(),'label': 'Close', 'color': 'blue'},
                    {'curve': ema_5.tolist(),'label': 'EMA-5', 'color': 'orange'},
                    {'curve': ema_20.tolist(),'label': 'EMA-20', 'color': 'red'},
                    ],
                points=points))
        if show:
            graph_this(ema_5, ema_20)

        buy_signal = bool(ema_5.iloc[-1] > ema_20.iloc[-1] and ema_5.iloc[-2] <= ema_20.iloc[-2])
        sell_signal = bool(ema_5.iloc[-1] < ema_20.iloc[-1] and ema_5.iloc[-2] >= ema_20.iloc[-2])

        return {'buy': buy_signal, 'sell': sell_signal}

    # Pivot Points
    def get_pivot_points(self, show = False):
        """
        Calculate pivot points and support/resistance levels, and optionally display a graph.

        Parameters:
            show (bool): If True, display a graph of the pivot points and buy/sell signals.

        Returns:
            dict: A dictionary with 'buy' and 'sell' signals based on the latest close price compared to the pivot point.
        """
        pivot_points = pd.DataFrame(index=self._data.index)
        pivot_points['P'] = (self._data['high'] + self._data['low'] + self._data['close']) / 3
        pivot_points['R1'] = 2 * pivot_points['P'] - self._data['low']
        pivot_points['S1'] = 2 * pivot_points['P'] - self._data['high']
        pivot_points['R2'] = pivot_points['P'] + (self._data['high'] - self._data['low'])
        pivot_points['S2'] = pivot_points['P'] - (self._data['high'] - self._data['low'])
        pivot_points['R3'] = self._data['high'] + 2 * (pivot_points['P'] - self._data['low'])
        pivot_points['S3'] = self._data['low'] - 2 * (self._data['high'] - pivot_points['P'])

        def graph_this(pivot_points):
            buy_points = []
            sell_points = []
            for i in range(len(self._data['close'])):
                if self._data['close'][i] > pivot_points['P'][i] and self._data['close'][i-1] <= pivot_points['P'][i-1]:
                    buy_points.append({'x': i, 'y': self._data['close'].iloc[i-1], 'color': 'green'})
                elif self._data['close'][i] < pivot_points['P'][i] and self._data['close'][i-1] >= pivot_points['P'][i-1]:
                    sell_points.append({'x': i, 'y': self._data['close'].iloc[i-1], 'color': 'red'})
            points = buy_points + sell_points
            x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
            graph(GraphData(x_label='Date',
                y_label='Price',
                title='Pivot Points',
                x_values=x_values,
                curves=[
                    {'curve': self._data['close'].tolist(),'label': 'Close', 'color': 'blue'},
                    {'curve': pivot_points['P'],'label': 'P', 'color': 'green'},
                    ], points=points))
        if show:
            graph_this(pivot_points)

        close_list = self._data['close'].tolist()
        pivot_points_list = pivot_points['P'].tolist()

        return {'buy':bool(close_list[-1] < pivot_points_list[-1]), 'sell':bool(close_list[-1] > pivot_points_list[-1])}
