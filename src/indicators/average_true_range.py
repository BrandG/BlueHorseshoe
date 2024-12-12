import numpy as np
import pandas as pd
from globals import GraphData, graph
import talib as ta


class AverageTrueRange:

    def __init__(self, data):
        self.update(data)

    @property
    def value(self):
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
