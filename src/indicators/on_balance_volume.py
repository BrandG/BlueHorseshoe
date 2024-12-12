
from globals import ReportSingleton

import talib as ta

class OnBalanceVolume:
    def __init__(self, data):
        self.update(data)

    def update(self, data):
        self._data = data

        self._obv = ta.OBV(self._data['close'], self._data['volume'])  # type: ignore

    @property
    def value(self):
        if len(self._obv) < 2:
            return {'direction': 'error'}
        return {'direction': 'up' if self._obv.iloc[-1] > self._obv.iloc[-2] else 'down'}

    # pylint: disable=unused-variable
    def graph(self):
        # To Do: Fill this in
        ReportSingleton().write(self._obv)
