
import pandas as pd
from globals import GraphData, graph
import talib as ta


class BollingerBands:

    def __init__(self, data):
        self.update(data)

    @property
    def value(self):
        buy = bool(self._data['close'].iloc[-1] < self._lower_band.iloc[-1])
        sell = bool(self._data['close'].iloc[-1] > self._upper_band.iloc[-1])

        return {'buy': buy, 'sell': sell, 'volatility': 'high' if (buy or sell) else 'low'}

    def update(self, data, window=20, num_std=2, show = False):
        self._data = data
        self._upper_band, _, self._lower_band = ta.BBANDS(self._data['close'], timeperiod=window, nbdevup=num_std, nbdevdn=num_std, matype=0) # type: ignore

    
    # pylint: disable=unused-variable
    def graph(self):
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


