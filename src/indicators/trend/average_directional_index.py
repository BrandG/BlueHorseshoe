"""
This module calculates the Average Directional Index (ADX) and its components (Plus Directional Indicator and Minus Directional Indicator) 
for a given dataset. It also provides functionality to graph the ADX and its components along with the price data.

Classes:
    AverageDirectionalIndex: A class to calculate and update ADX values, determine the strength of the trend, and graph the results.

Dependencies:
    pandas
    talib
    globals (GraphData, graph)
"""

import pandas as pd
import talib as ta
from globals import GraphData, graph
from indicators.indicator import Indicator


class AverageDirectionalIndex(Indicator):

    """
        A class to calculate the Average Directional Index (ADX) and its components, determine the trend direction and strength, 
        and graph the results.

        Attributes:
            _data (pd.DataFrame): The input data containing 'high', 'low', 'close', and 'date' columns.
            _adx (dict): A dictionary to store the ADX, Plus Directional Indicator (DMP_14), and Minus Directional Indicator (DMN_14) values.
            _adx_strength (str): A string representing the strength of the trend ('very strong', 'strong', 'threshold', 'weak').

        Methods:
            __init__(data): Initializes the AverageDirectionalIndex with the given data.
            update(data): Updates the ADX values and trend strength based on the given data.
            value: Returns a dictionary with the trend direction ('up' or 'down') and strength.
            graph(): Graphs the ADX, its components, and the price data.
    """

    def __init__(self, data):
        """
            Initializes the AverageDirectionalIndex with the given data.

            Args:
                data (pd.DataFrame): The input data containing 'high', 'low', 'close', and 'date' columns.
        """

        self.update(data)

    def update(self, data):
        """
            Updates the ADX values and trend strength based on the given data.

            Args:
                data (pd.DataFrame): The input data containing 'high', 'low', 'close', and 'date' columns.
        """

        self._data = data

        self._adx = {}
        self._adx['DMP_14'] = ta.PLUS_DI( # type: ignore
            self._data['high'], self._data['low'], self._data['close'], timeperiod=14).to_list()
        self._adx['DMN_14'] = ta.MINUS_DI( # type: ignore
            self._data['high'], self._data['low'], self._data['close'], timeperiod=14).to_list()
        self._adx['ADX_14'] = ta.ADX(self._data['high'], self._data['low'], # type: ignore
                                     self._data['close'], timeperiod=14).to_list()

        last_price = self._data['close'].to_list()[-1]
        if last_price != 0:
            self._adx_strength = 1 + round(float(self._adx['ADX_14'][-1]/last_price), 2) * 2
        else:
            self._adx_strength = 0

    @property
    def value(self):
        """
            Returns a dictionary with the trend direction ('up' or 'down') and strength.

            Returns:
                dict: A dictionary with the trend direction ('up' or 'down') and strength.
        """
        if len(self._adx['DMP_14']) < 2:
            return {'direction': 'up', 'strength': 0}
        return {'direction': 'up' if self._adx['DMP_14'][-1] > self._adx['DMN_14'][-2] else 'down', 'strength': self._adx_strength}

    def graph(self):
        """
            Graphs the ADX, its components, and the price data.
        """
        points = []
        for i in range(len(self._data['close'])):
            if self._adx['ADX_14'][i] > 25:
                if self._adx['DMP_14'][i] > self._adx['DMN_14'][i]:
                    points.append(
                        {'x': i, 'y': self._data['close'].iloc[i-1]*100/self._data['close'].max(), 'color': 'green'})
                elif self._adx['DMN_14'][i] > self._adx['DMP_14'][i]:
                    points.append(
                        {'x': i, 'y': self._data['close'].iloc[i-1]*100/self._data['close'].max(), 'color': 'red'})
        x_values = [pd.to_datetime(date).strftime('%Y-%m')
                    for date in self._data['date']]
        graph(GraphData(x_label='Date',
                        y_label='Price',
                        title='ADX',
                        x_values=x_values,
                        curves=[
                            {'curve': self._adx['DMP_14'],
                                'label': 'Positive', 'color': 'blue'},
                            {'curve': self._adx['DMN_14'],
                                'label': 'Negative', 'color': 'red'},
                            {'curve': self._adx['ADX_14'],
                                'label': 'ADX', 'color': 'yellow'},
                            {'curve': self._data['close']*100/self._data['close'].max(
                            ), 'label': 'Price', 'color': 'black'},
                        ], points=points))
