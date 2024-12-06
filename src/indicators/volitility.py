"""
Module: volitility
This module provides a class `Volitility` that includes methods to calculate and 
analyze financial volatility indicators such as Average True Range (ATR), 
Bollinger Bands, and Standard Deviation. These methods can generate buy/sell \
signals and report volatility levels.

Classes:
    Volitility: A class to calculate and analyze financial volatility indicators.
Methods:
    __init__(data):
        Initializes the Volitility class with the provided data.
    get_atr(multiplier=1.5, show=False):
            show (bool): Whether to display the graph of ATR and high volatility points.
    get_bollinger_bands(window=20, num_std=2, show=False):
            show (bool): Whether to display the graph of Bollinger Bands and buy/sell points.
            dict: A dictionary containing 'buy', 'sell', and 'volatility' signals.
    get_standard_deviation_volatility(period=20, show=False):
            show (bool): Whether to display the graph of standard deviation and price data.
"""
import numpy as np
import pandas as pd
import talib as ta

from globals import GraphData, graph


class Volitility:
    """
    A class to calculate and analyze volatility indicators for financial data.
    This class provides methods to calculate various volatility indicators such as Average True Range (ATR),
    Bollinger Bands, and Standard Deviation. It also generates buy/sell signals based on these indicators
    and provides options to visualize the results.
    Attributes:
        _data (pd.DataFrame): A DataFrame containing the financial data with columns 'high', 'low', 'close', and 'date'.
    Methods:
        get_atr(multiplier=1.5, show=False):
        get_bollinger_bands(window=20, num_std=2, show=False):
        get_standard_deviation_volatility(period=20, show=False):
    """
    def __init__(self, data):
        self._data = data

    # Average True Range (ATR)
    def get_atr(self, multiplier=1.5, show = False):
        """
        Generate buy/sell signals based on ATR and report high volatility.

        This method uses the ATR to set stop-loss levels, identify potential breakout points, and report high volatility.

        Args:
            multiplier (float): The multiplier for setting stop-loss levels or identifying breakouts.

        Returns:
            dict: A dictionary with 'buy', 'sell', and 'high_volatility' signals.
                  'buy' is 'true' if a buy signal is generated, otherwise 'false'.
                  'sell' is 'true' if a sell signal is generated, otherwise 'false'.
                  'high_volatility' is 'true' if the current ATR is higher than the midpoint of the ATR list, otherwise 'false'.
        """
        atr = ta.ATR(self._data['high'], self._data['low'], self._data['close'], timeperiod=14) # type: ignore

        atr_value = atr.iloc[-1]
        close_price = self._data['close'].iloc[-1]

        # Calculate the midpoint of the ATR list
        atr_midpoint = np.median(atr)

        # Determine high volatility
        high_volatility = atr_value > atr_midpoint

        # Example of using ATR for stop-loss levels
        stop_loss_long = float((close_price - (multiplier * atr_value)).round(2))
        stop_loss_short = float((close_price + (multiplier * atr_value)).round(2))

        # Example of using ATR for breakout signals
        breakout_up = close_price + (multiplier * atr_value)
        breakout_down = close_price - (multiplier * atr_value)

        # Generate signals (this is just an example, you can customize the logic)
        buy_signal = bool(close_price > breakout_up)
        sell_signal = bool(close_price < breakout_down)

        # pylint: disable=unused-variable
        def graph_this(atr, high_volatility):
            price_data = (self._data['close'] / self._data['close'].max()).tolist()
            atr_list = (atr / atr.max()).tolist()
            points = []
            for i in range(len(self._data['close'])):
                if high_volatility[i]:
                    points.append({'x': i, 'y': price_data[i], 'color': 'green'})

            x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
            graph(GraphData(x_label='Date', y_label='Percentage', title='ATR',
                                x_values=x_values, curves=[{'curve': atr_list, 'label': 'ATR', 'color':'blue'},
                                                            {'curve': price_data,
                                                            'label': 'Close', 'color': 'green'}],
                                                            points=points))
        if show:
            graph_this(atr, (atr > atr.mean()).tolist())

        return {'volatility': 'high' if high_volatility else 'low',
                'stop_loss_long': stop_loss_long,
                'stop_loss_short': stop_loss_short,
                'buy': buy_signal,
                'sell': sell_signal}

    # Bollinger Bands
    def get_bollinger_bands(self, window=20, num_std=2, show = False):
        """
        Calculate the Bollinger Bands and generate buy/sell signals.

        The Bollinger Bands are calculated using the closing prices of the data. The function also calculates the
        moving average and the upper and lower bands based on the standard deviation.

        Args:
            window (int): The window size for the moving average.
            num_std (int): The number of standard deviations for the bands.
            
        Returns:
            dict: A dictionary containing:
                - 'buy' (bool): True if a buy signal is generated, False otherwise.
                - 'sell' (bool): True if a sell signal is generated, False otherwise.
        """
        upper_band, _, lower_band = ta.BBANDS(self._data['close'], timeperiod=window, nbdevup=num_std, nbdevdn=num_std, matype=0) # type: ignore

        buy = bool(self._data['close'].iloc[-1] < lower_band.iloc[-1])
        sell = bool(self._data['close'].iloc[-1] > upper_band.iloc[-1])

        # pylint: disable=unused-variable
        def graph_this(upper_band, lower_band):
            buy_list = (self._data['close'] < lower_band).tolist()
            sell_list = (self._data['close'] > upper_band).tolist()
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
                                x_values=x_values, curves=[{'curve': upper_band, 'label': 'upper band', 'color':'orange'},
                                                            {'curve': lower_band, 'label': 'lower band', 'color':'red'},
                                                            {'curve': self._data['close'].tolist(),
                                                            'label': 'Close', 'color': 'green'}
                                                            ],
                                                            points=points))
        if show:
            graph_this(upper_band, lower_band)

        return {'buy': buy, 'sell': sell, 'volatility': 'high' if (buy or sell) else 'low'}

    # Standard Deviation
    def get_standard_deviation_volatility(self, period=20, show = False):
        """
        Calculate and report price volatility using the standard deviation.

        This method calculates the standard deviation of the closing prices over a specified period to determine price volatility.

        Args:
            period (int): The period for calculating the moving average and standard deviation.

        Returns:
            dict: A dictionary containing the current volatility value and a volatility level ('high' or 'low').
        """
        std_deviation = ta.STDDEV(self._data['close'], timeperiod=period) # type: ignore
        current_volatility = float(std_deviation.iloc[-1])
        volatility_level = 'high' if current_volatility > std_deviation.mean() else 'low'

        # pylint: disable=unused-variable
        def graph_this(std_deviation):
            price_data = (self._data['close'] / self._data['close'].max()).tolist()
            stdev_list = (std_deviation / std_deviation.max()).tolist()
            x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
            graph(GraphData(x_label='Date', y_label='Percentage', title='Standard Deviation',
                                x_values=x_values, curves=[{'curve': stdev_list, 'label': 'stDev', 'color':'orange'},
                                                            {'curve': price_data, 'label': 'Close', 'color': 'green'}
                                                            ]))
        if show:
            graph_this(std_deviation)

        return {'current_stdev': current_volatility, 'volatility': volatility_level}
