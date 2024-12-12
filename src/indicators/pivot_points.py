import pandas as pd
from globals import GraphData, graph


class PivotPoints:
    def __init__(self, data):
        self.update(data)

    def update(self, data):
        self._data = data

        pivot_points = pd.DataFrame(index=self._data.index)
        pivot_points['P'] = (self._data['high'] + self._data['low'] + self._data['close']) / 3
        pivot_points['R1'] = 2 * pivot_points['P'] - self._data['low']
        pivot_points['S1'] = 2 * pivot_points['P'] - self._data['high']
        pivot_points['R2'] = pivot_points['P'] + (self._data['high'] - self._data['low'])
        pivot_points['S2'] = pivot_points['P'] - (self._data['high'] - self._data['low'])
        pivot_points['R3'] = self._data['high'] + 2 * (pivot_points['P'] - self._data['low'])
        pivot_points['S3'] = self._data['low'] - 2 * (self._data['high'] - pivot_points['P'])
        self._pivot_points = pivot_points

    @property
    def value(self):
        last_close = self._data['close'].tolist()[-1]
        last_pivot_point = self._pivot_points['P'].tolist()[-1]

        return {'buy':bool(last_close < last_pivot_point), 'sell':bool(last_close > last_pivot_point)}

    def graph(self):
        buy_points = []
        sell_points = []
        for i in range(len(self._data['close'])):
            if self._data['close'][i] > self._pivot_points['P'][i] and self._data['close'][i-1] <= self._pivot_points['P'][i-1]:
                buy_points.append({'x': i, 'y': self._data['close'].iloc[i-1], 'color': 'green'})
            elif self._data['close'][i] < self._pivot_points['P'][i] and self._data['close'][i-1] >= self._pivot_points['P'][i-1]:
                sell_points.append({'x': i, 'y': self._data['close'].iloc[i-1], 'color': 'red'})
        points = buy_points + sell_points
        x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
        graph(GraphData(x_label='Date',
            y_label='Price',
            title='Pivot Points',
            x_values=x_values,
            curves=[
                {'curve': self._data['close'].tolist(),'label': 'Close', 'color': 'blue'},
                {'curve': self._pivot_points['P'],'label': 'P', 'color': 'green'},
                ], points=points))
