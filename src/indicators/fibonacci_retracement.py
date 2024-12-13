"""
A module to calculate and plot Fibonacci retracement levels for a given price data.

Classes:
    FibonacciRetracement: A class to calculate and plot Fibonacci retracement levels.
"""
import numpy as np
import pandas as pd
import talib as ta

from globals import GraphData, graph

class FibonacciRetracement:
    """
    A class to calculate and plot Fibonacci retracement levels for a given price data.

    Attributes:
        _data (pd.DataFrame): The price data containing 'date', 'close', 'high', and 'low' columns.

    Methods:
        graph(fib):
        get_results(close_range=0.01, show=False):
    """

    _fib = {}
    _fib_levels = ['swing_high', 'swing_low', '0%', '23%', '38%', '50%', '61%', '78%', '100%']

    def __init__(self, data):
        """
        Initializes the FibonacciRetracement instance with the provided data.

        Args:
            data (list or pandas.DataFrame): The data to be used for calculating Fibonacci retracement levels.
        """
        self.update(data)

    def update(self, data, close_range = 0.01):
        """
        Update the Fibonacci retracement levels based on the provided data.

        Parameters:
        data (pd.DataFrame): A DataFrame containing 'high', 'low', and 'close' price data.
        close_range (float, optional): The range within which the final price is considered close to a Fibonacci level. Default is 0.01.

        This method performs the following steps:
        1. Identifies the swing high and swing low over a specified lookback period.
        2. Calculates the Fibonacci retracement levels based on the swing high and swing low.
        3. Updates the internal Fibonacci levels dictionary with the calculated levels.
        4. Determines if the final closing price is within the specified range of any Fibonacci level.
        5. Updates the internal retracement list with the levels that are within the specified range.

        The method updates the following internal attributes:
        - self._fib: A dictionary containing the swing high, swing low, and Fibonacci levels.
        - self._retracement: A list of Fibonacci levels that are within the specified range of the final closing price.
        """
        self._data = data
        # Identify Swing High and Swing Low
        period = 10  # Lookback period to find highs and lows
        swing_high = pd.Series(ta.MAX(self._data['high'], timeperiod=period)).iloc[-1] # type: ignore
        swing_low = pd.Series(ta.MIN(self._data['low'], timeperiod=period)).iloc[-1] # type: ignore

        # Calculate Fibonacci levels
        fib_ratios = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]
        fib_levels = {f"{int(ratio * 100)}%": swing_high - (swing_high - swing_low) * ratio for ratio in fib_ratios}

        self._fib['swing_high'] = swing_high
        self._fib['swing_low'] = swing_low
        for level, price in fib_levels.items():
            self._fib[level] = price if np.isnan(price) else round(float(price), 2)

        final_price = self._data['close'].iloc[-1]
        self._retracement = []
        for level, price in fib_levels.items():
            if final_price != 0:
                self._retracement.append(abs(final_price - price) / final_price <= close_range)
            else:
                self._retracement.append(False)
        self._fib['retracement'] = True in self._retracement
        self._retracement = [str(level) for level, is_retracement in zip(self._fib.keys(), self._retracement) if is_retracement]

    @property
    def value(self):
        """
        Calculate and return the Fibonacci retracement levels and trading signals.

        This method evaluates the current closing price against predefined Fibonacci
        retracement levels to determine buy and sell signals. It also provides additional
        information about the swing high, swing low, and retracement status.

        Returns:
            dict: A dictionary containing the following keys:
                - 'buy' (bool): True if the current closing price is below the 78% Fibonacci level.
                - 'sell' (bool): True if the current closing price is above the 23% Fibonacci level.
                - 'swing_high' (float): The swing high price.
                - 'swing_low' (float): The swing low price.
                - 'fib_levels' (list): A list of dictionaries with Fibonacci levels and their corresponding prices.
                - 'retracement' (bool): True if there is a retracement.
                - 'price' (float): The current closing price.
        """
        buy = self._data['close'].iloc[-1] < self._fib['78%']
        sell = self._data['close'].iloc[-1] > self._fib['23%']

        prices = [{'level': level, 'price': self._fib[level]} for level in self._fib_levels]

        return {'buy':buy, 'sell':sell,'swing_high': self._fib['swing_high'], 'swing_low': self._fib['swing_low'],
                'fib_levels': prices, 'retracement': True in self._retracement, 'price': self._data['close'].iloc[-1]}

    def graph(self, fib):
        """
        Plots a graph of the Fibonacci Retracement levels along with the price data.

        Args:
            fib (dict): A dictionary containing the Fibonacci retracement levels with keys 
                        'swing_high', 'swing_low', '0%', '23%', '38%', '50%', '61%', '78%', and '100%'.
                        Each key corresponds to a specific retracement level value.

        Returns:
            None
        """
        x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
        graph(GraphData(x_label='Date',
            y_label='Price',
            title='Fibonacci Retracement',
            x_values=x_values,
            curves=[{'curve': self._data['close'][-20:],'label': 'Price', 'color': 'black'}],
                lines=[{'y': fib['swing_high'],'label': 'Swing High', 'color': 'blue'},
                       {'y': fib['swing_low'],'label': 'Swing Low', 'color': 'blue'},
                    {'y': fib['0%'],'label': '0%', 'color': '#00FF00'},
                    {'y': fib['23%'],'label': '23%', 'color': '#66FF00'},
                    {'y': fib['38%'],'label': '38%', 'color': '#CCFF00'},
                    {'y': fib['50%'],'label': '50%', 'color': '#FFCC00'},
                    {'y': fib['61%'],'label': '61%', 'color': '#FF6600'},
                    {'y': fib['78%'],'label': '78%', 'color': '#FF3300'},
                    {'y': fib['100%'],'label': '100%', 'color': '#FF0000'}
                    ]
                    ))
