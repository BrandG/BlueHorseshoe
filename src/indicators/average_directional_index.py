import pandas as pd
import talib as ta
from globals import GraphData, graph

class AverageDirectionalIndex:

    def __init__(self, data):
        self.update(data)

    def update(self, data):
        self._data = data

        self._adx={}
        self._adx['DMP_14'] = ta.PLUS_DI(self._data['high'],self._data['low'],self._data['close'],timeperiod=14).to_list() # type: ignore
        self._adx['DMN_14'] = ta.MINUS_DI(self._data['high'],self._data['low'],self._data['close'],timeperiod=14).to_list() # type: ignore
        self._adx['ADX_14'] = ta.ADX(self._data['high'],self._data['low'],self._data['close'],timeperiod=14).to_list() # type: ignore

        self._adx_strength = 0
        adx_float = round(float(self._adx['ADX_14'][-1]), 2)
        if float(adx_float) > 50:
            self._adx_strength = 'very strong'
        elif adx_float > 25:
            self._adx_strength = 'strong'
        elif adx_float > 20:
            self._adx_strength = 'threshold'
        else:
            self._adx_strength = 'weak'

    @property
    def value(self):
        return {'direction':'up' if self._adx['DMP_14'][-1] > self._adx['DMN_14'][-1] else 'down', 'strength':self._adx_strength}

    def graph(self):
        points = []
        for i in range(len(self._data['close'])):
            if self._adx['ADX_14'][i] > 25:
                if self._adx['DMP_14'][i] > self._adx['DMN_14'][i]:
                    points.append({'x': i, 'y': self._data['close'].iloc[i-1]*100/self._data['close'].max(), 'color': 'green'})
                elif self._adx['DMN_14'][i] > self._adx['DMP_14'][i]:
                    points.append({'x': i, 'y': self._data['close'].iloc[i-1]*100/self._data['close'].max(), 'color': 'red'})
        x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
        graph(GraphData(x_label='Date',
            y_label='Price',
            title='ADX',
            x_values=x_values,
            curves=[
                {'curve': self._adx['DMP_14'],'label': 'Positive', 'color': 'blue'},
                {'curve': self._adx['DMN_14'],'label': 'Negative', 'color': 'red'},
                {'curve': self._adx['ADX_14'],'label': 'ADX', 'color': 'yellow'},
                {'curve': self._data['close']*100/self._data['close'].max(),'label': 'Price', 'color': 'black'},
                ], points=points))
