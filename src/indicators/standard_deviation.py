import pandas as pd
import talib as ta

from globals import GraphData, graph


class StandardDeviation:
    def __init__(self, data):
        self.update(data)

    def update(self, data, period=20): 
        self._data = data

        self._std_deviation = ta.STDDEV(self._data['close'], timeperiod=period) # type: ignore

    @property
    def value(self):
        current_volatility = float(self._std_deviation.iloc[-1])
        volatility_level = 'high' if current_volatility > self._std_deviation.mean() else 'low'

        return {'current_stdev': current_volatility, 'volatility': volatility_level}

    # pylint: disable=unused-variable
    def graph(self):
        price_data = (self._data['close'] / self._data['close'].max()).tolist()
        stdev_list = (self._std_deviation / self._std_deviation.max()).tolist()
        x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
        graph(GraphData(x_label='Date', y_label='Percentage', title='Standard Deviation',
                            x_values=x_values, curves=[{'curve': stdev_list, 'label': 'stDev', 'color':'orange'},
                                                        {'curve': price_data, 'label': 'Close', 'color': 'green'}
                                                        ]))
