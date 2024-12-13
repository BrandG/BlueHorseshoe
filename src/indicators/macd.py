"""
This module contains the implementation of the MACD (Moving Average Convergence Divergence) indicator.

Classes:
    MACD: A class to calculate and update the MACD indicator, generate buy/sell signals, and graph the results.
"""
import pandas as pd
import talib as ta
from globals import GraphData, graph

class MACD:
    """
    MACD (Moving Average Convergence Divergence)
    A class to calculate and update the MACD indicator, generate buy/sell signals, and graph the results.

    Attributes:
        _data (pd.DataFrame): The input data containing 'close' prices and 'date'.
        macd (pd.Series): The MACD series.
        signal (pd.Series): The signal line series.
        hist (pd.Series): The histogram series.

    Methods:
        __init__(data): Initializes the MACD object with the given data.
        update(data): Updates the MACD, signal, and histogram values with the given data.
        value: Returns a dictionary indicating buy/sell signals based on the MACD and signal line.
        __str__(): Returns a string representation of the MACD, signal, and histogram values.
        graph(): Plots the MACD, signal line, and close prices, highlighting buy/sell points.
    """
    _data = None

    def __init__(self, data):
        """
        Initializes the MACD indicator with the provided data.

        Args:
            data (pandas.DataFrame): The input data for the MACD indicator.
        """
        self.update(data)

    def update(self, data):
        """
        Update the MACD indicator with new data.

        Parameters:
        data (pandas.DataFrame): A DataFrame containing the stock data with at least a 'close' column.

        Updates the following attributes:
        macd (numpy.ndarray): The MACD values.
        signal (numpy.ndarray): The signal line values.
        hist (numpy.ndarray): The histogram values.
        """
        self._data = data
        self.macd, self.signal, self.hist = ta.MACD(  # type: ignore
            self._data['close'], fastperiod=12, slowperiod=26, signalperiod=9)

    @property
    def value(self):
        """
        Determines buy and sell signals based on the MACD and signal line values.

        The method compares the most recent MACD value with the signal line value to 
        generate buy and sell signals. A buy signal is generated when the MACD line 
        crosses above the signal line, and a sell signal is generated when the MACD 
        line crosses below the signal line.

        Returns:
            dict: A dictionary containing boolean values for 'buy' and 'sell' signals.
                  {'buy': bool, 'sell': bool}
        """
        macd_list = self.macd.tolist()
        signal_list = self.signal.tolist()
        buy = macd_list[-1] > signal_list[-1] and macd_list[-2] <= signal_list[-2]
        sell = macd_list[-1] < signal_list[-1] and macd_list[-2] >= signal_list[-2]
        return {'buy': buy, 'sell': sell}

    def __str__(self):
        return f"MACD: {self.macd:.2f}, Signal: {self.signal:.2f}, Hist: {self.hist:.2f}"

    # pylint: disable=unused-variable
    def graph(self):
        """
        Generates and displays a graph for the MACD (Moving Average Convergence Divergence) indicator.

        The graph includes the MACD line, signal line, and the normalized closing prices of the data.
        It also marks buy and sell points based on the crossover of the MACD and signal lines.

        Raises:
            ValueError: If the data is not initialized.

        Notes:
            - The MACD and signal lines are normalized to a range of 0 to 1.
            - Buy points are marked when the MACD line crosses above the signal line.
            - Sell points are marked when the MACD line crosses below the signal line.

        """
        macd_list = (((self.macd / self.macd.max()) / 2) + 0.5).tolist()
        signal_list = (((self.signal / self.signal.max()) / 2) + 0.5).tolist()
        if self._data is None:
            raise ValueError("Data is not initialized.")
        price_list = (self._data['close'] /
                      self._data['close'].max()).tolist()
        buy_points = []
        sell_points = []
        for i in range(len(self._data['close'])):
            if macd_list[i] > signal_list[i] and macd_list[i-1] <= signal_list[i-1]:
                buy_points.append(
                    {'x': i, 'y': price_list[i-1], 'color': 'green'})
            elif macd_list[i] < signal_list[i] and macd_list[i-1] >= signal_list[i-1]:
                sell_points.append(
                    {'x': i, 'y': price_list[i-1], 'color': 'red'})
        points = buy_points + sell_points

        x_values = [pd.to_datetime(date).strftime('%Y-%m')
                    for date in self._data['date']]
        graph(GraphData(x_label='Date', y_label='Percentage', title='MACD',
                        x_values=x_values, curves=[{'curve': macd_list, 'label': 'MACD', 'color': 'orange'},
                                                    {'curve': signal_list,
                                                        'label': 'signal list', 'color': 'red'},
                                                    {'curve': price_list,
                                                    'label': 'Close', 'color': 'green'}
                                                    ],
                        points=points
                        ))
