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
        graph_this(fib):
        get_results(close_range=0.01, show=False):
    """

    def __init__(self, data):
        self._data = data

    def graph_this(self, fib):
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

    def get_results(self, close_range = 0.01, show = False):
        """
        Calculate Fibonacci retracement levels and determine buy/sell signals.

        Parameters:
        close_range (float): The range within which the current price is considered close to a Fibonacci level. Default is 0.01.
        show (bool): If True, the Fibonacci levels will be graphed. Default is False.

        Returns:
        dict: A dictionary containing:
            - 'buy' (bool): True if the current price is below the 78% Fibonacci level, indicating a buy signal.
            - 'sell' (bool): True if the current price is above the 23% Fibonacci level, indicating a sell signal.
            - 'swing_high' (float): The highest price in the lookback period.
            - 'swing_low' (float): The lowest price in the lookback period.
            - 'fib_levels' (dict): A dictionary of Fibonacci levels and their corresponding prices.
            - 'retracement' (bool): True if the current price is within the close_range of any Fibonacci level.
            - 'price' (float): The current closing price.
        """
        # Identify Swing High and Swing Low
        period = 10  # Lookback period to find highs and lows
        swing_high = pd.Series(ta.MAX(self._data['high'], timeperiod=period)).iloc[-1] # type: ignore
        swing_low = pd.Series(ta.MIN(self._data['low'], timeperiod=period)).iloc[-1] # type: ignore

        # Calculate Fibonacci levels
        fib_ratios = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]
        fib_levels = {f"{int(ratio * 100)}%": swing_high - (swing_high - swing_low) * ratio for ratio in fib_ratios}

        fib={}
        fib['swing_high'] = swing_high
        fib['swing_low'] = swing_low
        for level, price in fib_levels.items():
            fib[level] = price if np.isnan(price) else round(float(price), 2)

        if show:
            self.graph_this(fib)

        final_price = self._data['close'].iloc[-1]
        retracement = []
        for level, price in fib_levels.items():
            retracement.append(abs(final_price - price) / final_price <= close_range)
        fib['retracement'] = True in retracement
        retracement = [str(level) for level, is_retracement in zip(fib.keys(), retracement) if is_retracement]

        buy = self._data['close'].iloc[-1] < fib['78%']
        sell = self._data['close'].iloc[-1] > fib['23%']

        return {'buy':buy, 'sell':sell,'swing_high': fib['swing_high'], 'swing_low': fib['swing_low'],
                'fib_levels': fib_levels, 'retracement': True in retracement, 'price': self._data['close'].iloc[-1]}
