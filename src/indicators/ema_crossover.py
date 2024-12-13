"""
This module contains the EMACrossover class which calculates and analyzes
Exponential Moving Average (EMA) crossovers for a given dataset.

Classes:
    EMACrossover: A class to calculate and analyze EMA crossovers.

Methods:
    __init__(data): Initializes the EMACrossover instance with the given data.
    update(data): Updates the EMA calculations with new data.
    value: Returns a dictionary indicating buy and sell signals based on EMA crossovers.
    graph(): Generates a graph of the close prices and EMA values, highlighting buy and sell points.

Attributes:
    _data: The input data containing 'close' prices.
    _ema_5: The 5-period EMA of the close prices.
    _ema_20: The 20-period EMA of the close prices.
"""

import talib as ta
import pandas as pd

from globals import GraphData, graph

class EMACrossover:
    """
    A class to represent an Exponential Moving Average (EMA) crossover indicator.

    Attributes:
    -----------
    _data : pandas.DataFrame
        The input data containing 'close' prices and 'date'.
    _ema_5 : pandas.Series
        The 5-period EMA of the 'close' prices.
    _ema_20 : pandas.Series
        The 20-period EMA of the 'close' prices.

    Methods:
    --------
    __init__(data):
        Initializes the EMACrossover with the given data.
    update(data):
        Updates the internal data and recalculates the EMAs.
    value:
        Returns a dictionary with 'buy' and 'sell' signals based on EMA crossovers.
    graph():
        Generates a graph of the 'close' prices, EMAs, and buy/sell points.
    """

    def __init__(self, data):
        """
        Initializes the EMA Crossover indicator with the provided data.

        Args:
            data (pandas.DataFrame): The input data for the EMA Crossover indicator.
        """
        self.update(data)

    def update(self, data):
        """
        Update the EMA crossover indicator with new data.

        This method updates the internal data and recalculates the 5-period and 
        20-period Exponential Moving Averages (EMA) based on the 'close' prices 
        from the provided data.

        Args:
            data (pd.DataFrame): A pandas DataFrame containing the 'close' prices 
                     used to calculate the EMAs. The DataFrame should 
                     have a column named 'close'.
        """
        self._data = data

        self._ema_5 = ta.EMA(self._data['close'], timeperiod=5) # type: ignore
        self._ema_20 = ta.EMA(self._data['close'], timeperiod=20) # type: ignore

    @property
    def value(self):
        """
        Determines buy and sell signals based on the Exponential Moving Average (EMA) crossover strategy.

        The method compares the current and previous values of two EMAs (5-period and 20-period) to generate buy and sell signals.
        A buy signal is generated when the 5-period EMA crosses above the 20-period EMA.
        A sell signal is generated when the 5-period EMA crosses below the 20-period EMA.

        Returns:
            dict: A dictionary containing:
                - 'buy' (bool): True if a buy signal is generated, False otherwise.
                - 'sell' (bool): True if a sell signal is generated, False otherwise.
        """
        buy_signal = bool(self._ema_5.iloc[-1] > self._ema_20.iloc[-1] and self._ema_5.iloc[-2] <= self._ema_20.iloc[-2])
        sell_signal = bool(self._ema_5.iloc[-1] < self._ema_20.iloc[-1] and self._ema_5.iloc[-2] >= self._ema_20.iloc[-2])

        return {'buy': buy_signal, 'sell': sell_signal}

    # pylint: disable=unused-variable
    def graph(self):
        """
        Generates and displays a graph showing the closing prices and EMA (Exponential Moving Average) crossover points.

        The graph includes:
        - Closing prices of the stock.
        - EMA-5 (5-period Exponential Moving Average).
        - EMA-20 (20-period Exponential Moving Average).
        - Buy points where EMA-5 crosses above EMA-20.
        - Sell points where EMA-5 crosses below EMA-20.

        The x-axis represents the dates, and the y-axis represents the prices.

        Buy points are marked in green, and sell points are marked in red.

        Returns:
            None
        """
        ema_5_list = self._ema_5.tolist()
        ema_20_list = self._ema_20.tolist()

        points = []
        for i in range(len(self._data['close'])):
            if ema_5_list[i] > ema_20_list[i] and ema_5_list[i-1] <= ema_20_list[i-1]:
                points.append({'x': i, 'y': self._data['close'].iloc[i-1], 'color': 'green'})
            elif ema_5_list[i] < ema_20_list[i] and ema_5_list[i-1] >= ema_20_list[i-1]:
                points.append({'x': i, 'y': self._data['close'].iloc[i-1], 'color': 'red'})

        x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
        graph(GraphData(x_label='Date',
            y_label='Price',
            title='EMAs',
            x_values=x_values,
            curves=[
                {'curve': self._data['close'].tolist(),'label': 'Close', 'color': 'blue'},
                {'curve': ema_5_list,'label': 'EMA-5', 'color': 'orange'},
                {'curve': ema_20_list,'label': 'EMA-20', 'color': 'red'},
                ],
            points=points))
