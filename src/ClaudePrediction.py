import pandas as pd
import numpy as np
import talib as ta
import matplotlib.pyplot as plt

from Globals import graph

class ClaudePrediction:
    def __init__(self, data):
        self._data = data

    def get_mfi(self):
        mfi_data = ta.MFI(self._data['high'], self._data['low'], self._data['close'], self._data['volume'], timeperiod=14).dropna().tolist()
        mfi = mfi_data[-1]

        overbought_threshold = np.percentile(mfi_data, 85)
        oversold_threshold = np.percentile(mfi_data, 15)

        return {'buy': 'true' if mfi < oversold_threshold else 'false', 'sell': 'true' if mfi > overbought_threshold else 'false'}

    # On-Balance Volume (OBV)
    def get_obv(self):
        obv = ta.OBV(self._data['close'], self._data['volume'])
        return {'direction': 'up' if obv[0] > obv[1] else 'down'}

    # Volume Weighted Average Price (VWAP)
    def volume_weighted_average_price(self):
        vwap = (self._data['close'] * self._data['volume']).cumsum() / self._data['volume'].cumsum()
        return {'direction': 'up' if self._data['close'].tolist()[-1] > vwap.tolist()[-1] else 'down'}
