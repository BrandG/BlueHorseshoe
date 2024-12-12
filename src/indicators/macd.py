import pandas as pd
from globals import GraphData, graph
import talib as ta

# MACD (Moving Average Convergence Divergence)
class MACD():
    _data = None
    def __init__(self, data):
        self.update(data)

    def update(self, data):
        self._data = data
        self.macd, self.signal, self.hist = ta.MACD(  # type: ignore
            self._data['close'], fastperiod=12, slowperiod=26, signalperiod=9)

    @property
    def value(self):
        macd_list = self.macd.tolist()
        signal_list = self.signal.tolist()
        buy = macd_list[-1] > signal_list[-1] and macd_list[-2] <= signal_list[-2]
        sell = macd_list[-1] < signal_list[-1] and macd_list[-2] >= signal_list[-2]
        return {'buy': buy, 'sell': sell}

    def __str__(self):
        return f"MACD: {self.macd:.2f}, Signal: {self.signal:.2f}, Hist: {self.hist:.2f}"
    
    # pylint: disable=unused-variable
    def graph(self):
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
