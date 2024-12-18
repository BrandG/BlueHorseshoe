"""
This module contains the implementation of the AROON indicator using the TA-Lib library.
The AROON indicator is used to identify trends and potential reversals in the market.

Classes:
    AROON: A class to calculate and update the AROON indicator, generate buy/sell signals, and graph the results.
"""
import pandas as pd
import talib as ta
from globals import GraphData, graph

class AROON:
    """
    AROON Indicator
    A class to calculate and update the AROON indicator, generate buy/sell signals, and graph the results.

    Attributes:
        _data (pd.DataFrame): The input data containing 'high' and 'low' prices.
        aroondown (pd.Series): The AROON down series.
        aroonup (pd.Series): The AROON up series.

    Methods:
        __init__(data): Initializes the AROON object with the given data.
        update(data): Updates the AROON up and down values with the given data.
        value: Returns a dictionary indicating the AROON up and down values.
        graph(): Plots the AROON up and down values along with the close prices.
    """
    _data = None

    def __init__(self, data):
        """
        Initializes the AROON indicator with the provided data.

        Args:
            data (pandas.DataFrame): The input data for the AROON indicator.
        """
        self.update(data)

    def update(self, data):
        """
        Update the AROON indicator with new data.

        Parameters:
        data (pandas.DataFrame): A DataFrame containing the stock data with 'high' and 'low' columns.

        Updates the following attributes:
        aroondown (numpy.ndarray): The AROON down values.
        aroonup (numpy.ndarray): The AROON up values.
        """
        self._data = data
        self.aroondown, self.aroonup = ta.AROON(  # type: ignore
            self._data['high'], self._data['low'], timeperiod=14)

    @property
    def value(self):
        """
        Returns the AROON up and down values.

        Returns:
            dict: A dictionary containing the AROON up and down values.
                  {'direction': 'up' if aroonup > aroondown else 'down', 'buy': buy_signal, 'sell': sell_signal}
        """
        if len(self.aroonup) <= 2 or len(self.aroondown) <= 2:
            return {'direction': 'error', 'buy': False, 'sell': False}
        
        buy_signal = self.aroonup[-1] > self.aroondown[-1] and self.aroonup[-2] <= self.aroondown[-2]
        sell_signal = self.aroonup[-1] < self.aroondown[-1] and self.aroonup[-2] >= self.aroondown[-2]
        return {'direction': 'up' if self.aroonup[-1] > self.aroondown[-1] else 'down', 'buy': buy_signal, 'sell': sell_signal}

    def graph(self):
        """
        Generates and displays a graph for the AROON indicator.

        The graph includes the AROON up and down values and the normalized closing prices of the data.

        Raises:
            ValueError: If the data is not initialized.

        Notes:
            - The AROON up and down values are normalized to a range of 0 to 100.
            - Buy points are marked when the AROON up value crosses above the AROON down value.
            - Sell points are marked when the AROON up value crosses below the AROON down value.
        """
        aroondown_list = self.aroondown.tolist()
        aroonup_list = self.aroonup.tolist()
        if self._data is None:
            raise ValueError("Data is not initialized.")
        price_list = (self._data['close'] /
                      self._data['close'].max()).tolist()
        buy_points = []
        sell_points = []
        for i in range(len(self._data['close'])):
            if aroonup_list[i] > aroondown_list[i] and aroonup_list[i-1] <= aroondown_list[i-1]:
                buy_points.append(
                    {'x': i, 'y': price_list[i-1], 'color': 'green'})
            elif aroonup_list[i] < aroondown_list[i] and aroonup_list[i-1] >= aroondown_list[i-1]:
                sell_points.append(
                    {'x': i, 'y': price_list[i-1], 'color': 'red'})
        points = buy_points + sell_points

        x_values = [pd.to_datetime(date).strftime('%Y-%m')
                    for date in self._data['date']]
        graph(GraphData(x_label='Date', y_label='Percentage', title='AROON',
                        x_values=x_values, curves=[{'curve': aroonup_list, 'label': 'AROON Up', 'color': 'blue'},
                                                    {'curve': aroondown_list,
                                                        'label': 'AROON Down', 'color': 'red'},
                                                    {'curve': price_list,
                                                    'label': 'Close', 'color': 'green'}
                                                    ],
                        points=points
                        ))
