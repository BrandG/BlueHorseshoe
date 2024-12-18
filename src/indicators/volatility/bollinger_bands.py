"""
A class to calculate and analyze Bollinger Bands for a given dataset.
Attributes:
-----------
_data : pd.DataFrame
    The input data containing stock prices.
_upper_band : pd.Series
    The upper Bollinger Band.
_lower_band : pd.Series
    The lower Bollinger Band.
Methods:
--------
__init__(data):
    Initializes the BollingerBands object with the given data.
value:
    Returns a dictionary indicating whether to buy or sell based on the Bollinger Bands and the current volatility.
update(data, window=20, num_std=2, show=False):
    Updates the Bollinger Bands with the given data, window size, and number of standard deviations.
graph():
    Plots the Bollinger Bands along with buy and sell points on a graph.
"""

import talib as ta
import pandas as pd
from globals import GraphData, graph


class BollingerBands:
    """
    A class to calculate and analyze Bollinger Bands for a given dataset.
    Attributes:
    -----------
    _data : pandas.DataFrame
        The input data containing the 'close' prices.
    _upper_band : pandas.Series
        The upper Bollinger Band.
    _lower_band : pandas.Series
        The lower Bollinger Band.
    Methods:
    --------
    __init__(data):
        Initializes the BollingerBands object with the given data.
    value:
        Returns a dictionary indicating buy/sell signals and volatility status.
    update(data, window=20, num_std=2, show=False):
        Updates the Bollinger Bands with the given data and parameters.
    graph():
        Generates a graph of the Bollinger Bands with buy/sell points.
    """

    def __init__(self, data):
        """
        Initializes the BollingerBands indicator with the provided data.

        Args:
            data (list or pandas.Series): The input data for calculating Bollinger Bands.
        """
        self.update(data)

    @property
    def value(self):
        """
        Determines the buy and sell signals based on Bollinger Bands and the volatility.

        Returns:
            dict: A dictionary containing:
                - 'buy' (bool): True if the closing price is below the lower Bollinger Band, otherwise False.
                - 'sell' (bool): True if the closing price is above the upper Bollinger Band, otherwise False.
                - 'volatility' (str): 'high' if either buy or sell signal is True, otherwise 'low'.
        """
        buy = bool(self._data['close'].iloc[-1] < self._lower_band.iloc[-1])
        sell = bool(self._data['close'].iloc[-1] > self._upper_band.iloc[-1])

        return {'buy': buy, 'sell': sell, 'volatility': 'high' if (buy or sell) else 'low'}

    def update(self, data, window=20, num_std=2):
        """
        Update the Bollinger Bands with new data.

        Parameters:
        data (pd.DataFrame): The input data containing at least a 'close' column.
        window (int, optional): The number of periods to use for the moving average. Default is 20.
        num_std (int, optional): The number of standard deviations to use for the upper and lower bands. Default is 2.
        show (bool, optional): Whether to display the Bollinger Bands plot. Default is False.

        Returns:
        None
        """
        self._data = data
        self._upper_band, _, self._lower_band = ta.BBANDS(self._data['close'], timeperiod=window, nbdevup=num_std,  # type: ignore
                                                          nbdevdn=num_std, matype=0)

    # pylint: disable=unused-variable
    def graph(self):
        """
        Generates a graph for Bollinger Bands with buy and sell points.

        This method creates a graph that displays the upper and lower Bollinger Bands along with the closing prices.
        It also highlights the buy and sell points where the closing price crosses the lower and upper bands, respectively.

        The graph includes:
        - Upper Bollinger Band (orange)
        - Lower Bollinger Band (red)
        - Closing Prices (green)
        - Buy Points (green dots)
        - Sell Points (red dots)

        The x-axis represents the dates, formatted as 'YYYY-MM', and the y-axis represents the percentage.

        Parameters:
        None

        Returns:
        None
        """
        buy_list = (self._data['close'] < self._lower_band).tolist()
        sell_list = (self._data['close'] > self._upper_band).tolist()
        buy_points = []
        sell_points = []
        for i in range(len(self._data['close'])):
            if buy_list[i]:
                buy_points.append({'x': i, 'y': self._data['close'].iloc[i], 'color': 'green'})
            elif sell_list[i]:
                sell_points.append({'x': i, 'y': self._data['close'].iloc[i], 'color': 'red'})
        points = buy_points + sell_points

        x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
        graph(GraphData(x_label='Date', y_label='Percentage', title='Boillinger Bands',
                            x_values=x_values, curves=[{'curve': self._upper_band, 'label': 'upper band', 'color':'orange'},
                                                        {'curve': self._lower_band, 'label': 'lower band', 'color':'red'},
                                                        {'curve': self._data['close'].tolist(),
                                                        'label': 'Close', 'color': 'green'}
                                                        ],
                                                        points=points))
