"""
This module contains the implementation of the AverageTrueRange class, which calculates the Average True Range (ATR) 
indicator for a given dataset. The ATR is used to measure market volatility and can be used to set stop-loss levels 
and generate buy/sell signals based on breakout levels.
"""
import numpy as np
import pandas as pd
import talib as ta
from globals import GraphData, graph


class AverageTrueRange:
    """
    A class to calculate and utilize the Average True Range (ATR) for financial data analysis.

    Attributes:
    -----------
    _data : pandas.DataFrame
        The input data containing 'high', 'low', and 'close' prices.
    _multiplier : float
        The multiplier used for calculating stop-loss levels and breakout signals.
    _atr : pandas.Series
        The calculated ATR values.
    _atr_value : float
        The most recent ATR value.
    _close_price : float
        The most recent closing price.
    _atr_midpoint : float
        The median value of the ATR list.
    _high_volatility : bool
        Indicates if the current volatility is high based on ATR.

    Methods:
    --------
    __init__(data):
        Initializes the AverageTrueRange with the given data.
    value:
        Property that returns a dictionary with volatility status, stop-loss levels, and buy/sell signals.
    update(data, multiplier=1.5):
        Updates the ATR calculations with new data and an optional multiplier.
    graph_this():
        Generates a graph of the normalized closing prices and ATR values, highlighting high volatility points.
    """

    def __init__(self, data):
        """
        Initializes the AverageTrueRange instance with the provided data.

        Args:
            data (list or pandas.DataFrame): The input data used to calculate the Average True Range.
        """
        self.update(data)

    @property
    def value(self):
        """
        Calculate stop-loss levels, breakout signals, and generate buy/sell signals based on the Average True Range (ATR).

        Returns:
            dict: A dictionary containing:
                - 'volatility' (str): 'high' if volatility is high, otherwise 'low'.
                - 'stop_loss_long' (float): The stop-loss level for long positions.
                - 'stop_loss_short' (float): The stop-loss level for short positions.
                - 'buy' (bool): True if a buy signal is generated, otherwise False.
                - 'sell' (bool): True if a sell signal is generated, otherwise False.
        """
        # Example of using ATR for stop-loss levels
        stop_loss_long = float((self._close_price - (self._multiplier * self._atr_value)).round(2))
        stop_loss_short = float((self._close_price + (self._multiplier * self._atr_value)).round(2))

        # Example of using ATR for breakout signals
        breakout_up = self._close_price + (self._multiplier * self._atr_value)
        breakout_down = self._close_price - (self._multiplier * self._atr_value)

        # Generate signals (this is just an example, you can customize the logic)
        buy_signal = bool(self._close_price > breakout_up)
        sell_signal = bool(self._close_price < breakout_down)

        return {'volatility': 'high' if self._high_volatility else 'low',
                'stop_loss_long': stop_loss_long,
                'stop_loss_short': stop_loss_short,
                'buy': buy_signal,
                'sell': sell_signal}

    def update(self, data, multiplier=1.5):
        """
        Update the Average True Range (ATR) indicator with new data and calculate related metrics.

        Parameters:
        data (pd.DataFrame): A DataFrame containing 'high', 'low', and 'close' price data.
        multiplier (float, optional): A multiplier for the ATR calculation. Default is 1.5.

        Attributes:
        self._data (pd.DataFrame): The input data.
        self._multiplier (float): The multiplier for the ATR calculation.
        self._atr (pd.Series): The calculated ATR values.
        self._atr_value (float): The most recent ATR value.
        self._close_price (float): The most recent closing price.
        self._atr_midpoint (float): The median value of the ATR series.
        self._high_volatility (bool): A flag indicating if the most recent ATR value is higher than the median ATR value.
        """
        self._data = data
        self._multiplier = multiplier

        self._atr = ta.ATR(self._data['high'], self._data['low'], self._data['close'], timeperiod=14) # type: ignore

        self._atr_value = self._atr.iloc[-1]
        self._close_price = self._data['close'].iloc[-1]

        # Calculate the midpoint of the ATR list
        self._atr_midpoint = np.median(self._atr)

        # Determine high volatility
        self._high_volatility = self._atr_value > self._atr_midpoint


    # pylint: disable=unused-variable
    def graph_this(self):
        """
        Generates and displays a graph for the Average True Range (ATR) and normalized closing prices.

        This method normalizes the closing prices and ATR values, then plots them on a graph.
        It also highlights points of high volatility in green.

        The x-axis represents dates in 'YYYY-MM' format, and the y-axis represents the normalized percentage values.

        The graph includes:
        - A blue curve for the ATR values.
        - A green curve for the normalized closing prices.
        - Green points indicating high volatility.

        Returns:
            None
        """
        price_data = (self._data['close'] / self._data['close'].max()).tolist()
        atr_list = (self._atr / self._atr.max()).tolist()
        points = []
        for i in range(len(self._data['close'])):
            if self._high_volatility[i]:
                points.append({'x': i, 'y': price_data[i], 'color': 'green'})

        x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
        graph(GraphData(x_label='Date', y_label='Percentage', title='ATR',
                            x_values=x_values, curves=[{'curve': atr_list, 'label': 'ATR', 'color':'blue'},
                                                        {'curve': price_data,
                                                        'label': 'Close', 'color': 'green'}],
                                                        points=points))
