"""
This module contains the MomentumOscillators class, which provides methods to calculate various momentum oscillators
for financial data, including the Relative Strength Index (RSI), Stochastic Oscillator, and Moving Average Convergence
Divergence (MACD). These indicators are used to generate buy, sell, and hold signals based on the analysis of stock prices.

Classes:
    MomentumOscillators: A class to calculate and analyze momentum oscillators for financial data.

Methods:
    get_rsi(show=False): Calculate the Relative Strength Index (RSI) and determine buy/sell signals.
    get_stochastic_oscillator(show=False): Calculate the Stochastic Oscillator and determine buy/sell/hold signals.
    get_macd(show=False): Calculate the Moving Average Convergence Divergence (MACD) and determine buy/sell signals.
"""
import numpy as np
import pandas as pd
import talib as ta

from globals import GraphData, graph


class MomentumOscillators:
    """
    MomentumOscillators class provides methods to calculate various momentum oscillators and generate trading signals.

    Methods:
        __init__(data):
            Initializes the MomentumOscillators class with the provided stock data.

        get_rsi(show=False):
            Args:
                show (bool): If True, displays the RSI graph. Default is False.

        get_stochastic_oscillator(show=False):
            Args:
                show (bool): If True, displays the Stochastic Oscillator graph. Default is False.
                dict: A dictionary with keys 'buy', 'sell', and 'hold' indicating the trading signal.

        get_macd(show=False):
            Args:
                show (bool): If True, displays the MACD graph. Default is False.
                dict: A dictionary containing 'buy' and 'sell' signals.
    """

    def __init__(self, data):
        self._data = data

    # Relative Strength Index (RSI)
    def get_rsi(self, show=False):
        """
        Args:
            show (bool): If True, the RSI data will be printed. Default is False.

        Calculate the Relative Strength Index (RSI) and determine buy/sell signals.

        The function computes the RSI for the closing prices of the stock data over a 14-period window.
        It then determines the overbought and oversold thresholds based on the 85th and 15th percentiles
        of the RSI data, respectively.

        Returns:
            dict: A dictionary with 'buy' and 'sell' signals.
                'buy' is True if the RSI is below the oversold threshold, otherwise False.
                'sell' is True if the RSI is above the overbought threshold, otherwise False.
        """
        rsi_data = ta.RSI(self._data['close'],  # type: ignore
                          timeperiod=14).dropna()

        # pylint: disable=unused-variable
        def graph_this(rsi_data):
            # To Do: Fill this in
            print(rsi_data)
        if show:
            graph_this(rsi_data)

        if len(rsi_data) > 0:
            rsi = rsi_data.tolist()[-1]
            return {'buy': bool(rsi < np.percentile(rsi_data, 15)), 'sell': bool(rsi > np.percentile(rsi_data, 85))}
        return {'buy': False, 'sell': False}

    # Stochastic Oscillator
    def get_stochastic_oscillator(self, show=False):
        """
        Args:
            show (bool, optional): If True, a graph of the Stochastic Oscillator will be displayed. Defaults to False.

        Calculate the Stochastic Oscillator for the given data.

        The Stochastic Oscillator is a momentum indicator comparing a particular closing price of a security to a range of its prices
            over a certain period of time.

        Returns:
            dict: A dictionary with keys 'buy', 'sell', and 'hold' indicating the trading signal based on the Stochastic Oscillator.
                - 'buy' (bool): True if a buy signal is generated, otherwise False.
                - 'sell' (bool): True if a sell signal is generated, otherwise False.
                - 'hold' (bool): True if a hold signal is generated, otherwise False.
        """
        slowk, slowd = ta.STOCH(self._data['high'], self._data['low'], self._data['close'],  # type: ignore
                                fastk_period=5, slowk_period=3, slowk_matype=0,
                                slowd_period=3, slowd_matype=0)
        slowd = slowd.tolist()
        slowk = slowk.tolist()

        # pylint: disable=unused-variable
        def graph_this(slowd, slowk):
            # To Do: Fill this in
            print(slowd, slowk)
        if show:
            graph_this(slowd, slowk)

        buy = sell = hold = False
        if slowk[-1] > slowd[-1] and slowk[-2] <= slowd[-2]:
            buy = True
        elif slowk[-1] < slowd[-1] and slowk[-2] >= slowd[-2]:
            sell = True
        else:
            hold = True
        return {'buy': buy, 'sell': sell, 'hold': hold}

    # MACD (Moving Average Convergence Divergence)
    def get_macd(self, show=False):
        """
        Calculate the Moving Average Convergence Divergence (MACD) and generate buy/sell signals.
        The MACD is calculated using the closing prices of the data. The function also converts the MACD
        and signal line values to percentage arrays relative to the closing prices.

        Parameters:
        show (bool): If True, displays a graph of the MACD, signal line, and close prices. Default is False.

        Returns:
        dict: A dictionary with 'buy' and 'sell' keys indicating whether to buy or sell based on the MACD crossover.
              'buy' is True if the MACD line crosses above the signal line, and 'sell' is True if the MACD line crosses below the signal line.
        """

        macd, signal, _ = ta.MACD(  # type: ignore
            self._data['close'], fastperiod=12, slowperiod=26, signalperiod=9)
        macd_list = macd.tolist()
        signal_list = signal.tolist()

        # pylint: disable=unused-variable
        def graph_this(macd, signal):
            macd_list = (((macd / macd.max()) / 2) + 0.5).tolist()
            signal_list = (((signal / signal.max()) / 2) + 0.5).tolist()
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
        if show:
            graph_this(macd, signal)

        buy = macd_list[-1] > signal_list[-1] and macd_list[-2] <= signal_list[-2]
        sell = macd_list[-1] < signal_list[-1] and macd_list[-2] >= signal_list[-2]
        return {'buy': buy, 'sell': sell}
