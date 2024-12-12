import numpy as np

import talib as ta

from globals import ReportSingleton


class MoneyFlowIndex:
    def __init__(self, data):
        self.update(data)

    def update(self, data):
        self._data = data

        self._mfi_data = ta.MFI(self._data['high'], self._data['low'], self._data['close'],  # type: ignore
                          self._data['volume'], timeperiod=14).tolist()

    @property
    def value(self):
        mfi = self._mfi_data[-1]
        return {'buy': bool(mfi < np.percentile(self._mfi_data, 15)), 'sell': bool(mfi > np.percentile(self._mfi_data, 85))}

    # pylint: disable=unused-variable
    def graph_this(self):
        # To Do: Fill this in
        ReportSingleton().write(self._mfi_data)
