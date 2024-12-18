"""
This module calculates and graphs pivot points for financial data.

Classes:
    PivotPoints: A class to calculate and graph pivot points based on high, low, and close prices.

Functions:
    update(data): Updates the pivot points with new data.
    value: Returns a dictionary indicating buy or sell signals based on the last close price and pivot point.
    graph(): Graphs the pivot points and close prices, highlighting buy and sell signals.
"""
import pandas as pd
from globals import GraphData, graph
from indicators.indicator import Indicator


class PivotPoints(Indicator):
    """
    A class to calculate and graph pivot points based on high, low, and close prices.

    Attributes:
        _data (pd.DataFrame): The input data containing high, low, and close prices.
        _pivot_points (pd.DataFrame): The calculated pivot points.

    Methods:
        __init__(data): Initializes the PivotPoints object with the given data.
        update(data): Updates the pivot points with new data.
        value: Returns a dictionary indicating buy or sell signals based on the last close price and pivot point.
        graph(): Graphs the pivot points and close prices, highlighting buy and sell signals.
    """

    def __init__(self, data):
        """
        Initializes the PivotPoints object with the given data.

        Args:
            data (pd.DataFrame): The input data containing high, low, and close prices.
        """
        self.update(data)

    def update(self, data):
        """
        Updates the pivot points with new data.

        Args:
            data (pd.DataFrame): The input data containing high, low, and close prices.
        """
        self._data = data

        pivot_points = pd.DataFrame(index=self._data.index)
        pivot_points['P'] = (self._data['high'] + self._data['low'] + self._data['close']) / 3
        pivot_points['R1'] = 2 * pivot_points['P'] - self._data['low']
        pivot_points['S1'] = 2 * pivot_points['P'] - self._data['high']
        pivot_points['R2'] = pivot_points['P'] + (self._data['high'] - self._data['low'])
        pivot_points['S2'] = pivot_points['P'] - (self._data['high'] - self._data['low'])
        pivot_points['R3'] = self._data['high'] + 2 * (pivot_points['P'] - self._data['low'])
        pivot_points['S3'] = self._data['low'] - 2 * (self._data['high'] - pivot_points['P'])
        self._pivot_points = pivot_points

    @property
    def value(self):
        """
        Returns a dictionary indicating buy or sell signals based on the last close price and pivot point.

        Returns:
            dict: A dictionary with 'buy' and 'sell' keys indicating the signals.
        """
        last_close = self._data['close'].tolist()[-1]
        last_pivot_point = self._pivot_points['P'].tolist()[-1]

        return {'buy':bool(last_close < last_pivot_point), 'sell':bool(last_close > last_pivot_point)}

    def graph(self):
        """
        Graphs the pivot points and close prices, highlighting buy and sell signals.
        """
        points = []
        for i in range(len(self._data['close'])):
            if self._data['close'][i] > self._pivot_points['P'][i] and self._data['close'][i-1] <= self._pivot_points['P'][i-1]:
                points.append({'x': i, 'y': self._data['close'].iloc[i-1], 'color': 'green'})
            elif self._data['close'][i] < self._pivot_points['P'][i] and self._data['close'][i-1] >= self._pivot_points['P'][i-1]:
                points.append({'x': i, 'y': self._data['close'].iloc[i-1], 'color': 'red'})
        x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
        graph(GraphData(x_label='Date',
            y_label='Price',
            title='Pivot Points',
            x_values=x_values,
            curves=[
                {'curve': self._data['close'].tolist(),'label': 'Close', 'color': 'blue'},
                {'curve': self._pivot_points['P'],'label': 'P', 'color': 'green'},
                ], points=points))
