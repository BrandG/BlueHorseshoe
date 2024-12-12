import talib as ta
import pandas as pd

from globals import GraphData, graph

class EMACrossover:
    def __init__(self, data):
        self.update(data)

    def update(self, data):
        self._data = data

        self._ema_5 = ta.EMA(self._data['close'], timeperiod=5) # type: ignore
        self._ema_20 = ta.EMA(self._data['close'], timeperiod=20) # type: ignore

    @property
    def value(self):
        buy_signal = bool(self._ema_5.iloc[-1] > self._ema_20.iloc[-1] and self._ema_5.iloc[-2] <= self._ema_20.iloc[-2])
        sell_signal = bool(self._ema_5.iloc[-1] < self._ema_20.iloc[-1] and self._ema_5.iloc[-2] >= self._ema_20.iloc[-2])

        return {'buy': buy_signal, 'sell': sell_signal}

    # pylint: disable=unused-variable
    def graph(self):
        ema_5_list = self._ema_5.tolist()
        ema_20_list = self._ema_20.tolist()

        buy_points = []
        sell_points = []
        for i in range(len(self._data['close'])):
            if ema_5_list[i] > ema_20_list[i] and ema_5_list[i-1] <= ema_20_list[i-1]:
                buy_points.append({'x': i, 'y': self._data['close'].iloc[i-1], 'color': 'green'})
            elif ema_5_list[i] < ema_20_list[i] and ema_5_list[i-1] >= ema_20_list[i-1]:
                sell_points.append({'x': i, 'y': self._data['close'].iloc[i-1], 'color': 'red'})
        points = buy_points + sell_points

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
