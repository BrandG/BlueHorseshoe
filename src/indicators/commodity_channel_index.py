"""
A module for the Commodity Channel Index (CCI) trend analysis.

Classes:
    CCITrend: A class for analyzing trends using the Commodity Channel Index (CCI) indicator.
Methods:
    __init__(data): Initializes the CCITrend class with the provided data.
    graph(cci): Generates a graph for the Commodity Channel Index (CCI) and the closing prices.
    get_results(show=False): Calculate the Commodity Channel Index (CCI) for the given data and return buy/sell signals.
"""

import pandas as pd
import talib as ta

from globals import GraphData, graph

class CCITrend:
    """
    A class to represent the Commodity Channel Index (CCI) trend analysis.

    Attributes:
        _data (pandas.DataFrame): The input data containing 'high', 'low', 'close', and 'date' columns.

    Methods:
        __init__(data):
            Initializes the CCITrend with the given data.
            data (pandas.DataFrame): The input data containing 'high', 'low', 'close', and 'date' columns.
    
        graph(cci):
    
        get_results(show=False):
    """
    def __init__(self, data):
        self.update(data)

    def update(self, data):
        self._data = data
        self._cci = ta.CCI(self._data['high'], self._data['low'], self._data['close'], timeperiod=14).to_list() # type: ignore

    @property
    def value(self):
        return {'buy': self._cci[-1] < -100, 'sell':self._cci[-1] > 100}

    def graph(self, cci):
        """
        Generates a graph for the Commodity Channel Index (CCI) and the closing prices.

        Parameters:
        cci (list or pandas.Series): The Commodity Channel Index values.

        This function creates a graph with the following features:
        - Points where the CCI is greater than 100 are marked in green.
        - Points where the CCI is less than -100 are marked in red.
        - The x-axis represents dates formatted as 'YYYY-MM'.
        - The y-axis represents the price, normalized to a percentage of the maximum closing price.
        - Two curves are plotted:
            - The CCI curve, normalized to a percentage of its maximum value, in blue.
            - The closing price curve, normalized to a percentage of its maximum value, in black.
        """
        points = []
        for i in range(len(self._data['close'])):
            if cci[i] > 100:
                points.append({'x': i, 'y': self._data['close'].iloc[i-1]*100/self._data['close'].max(), 'color': 'green'})
            elif cci[i] < -100:
                points.append({'x': i, 'y': self._data['close'].iloc[i-1]*100/self._data['close'].max(), 'color': 'red'})
        x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
        graph(GraphData(x_label='Date',
            y_label='Price',
            title='CCI',
            x_values=x_values,
            curves=[
                {'curve': cci*100 / cci.max(),'label': 'CCI', 'color': 'blue'},
                {'curve': self._data['close']*100/self._data['close'].max(),'label': 'Price', 'color': 'black'},
                ], points=points))
