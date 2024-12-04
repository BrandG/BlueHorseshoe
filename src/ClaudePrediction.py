import numpy as np
import talib as ta

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

    # Relative Strength Index (RSI)
    def get_rsi(self):
        rsi_data = ta.RSI(self._data['close'], timeperiod=14).dropna()
        
        rsi = rsi_data.tolist()[-1]

        overbought_threshold = np.percentile(rsi_data, 85)
        oversold_threshold = np.percentile(rsi_data, 15)

        return {'buy': 'true' if rsi < oversold_threshold else 'false', 'sell': 'true' if rsi > overbought_threshold else 'false'}

    # Stochastic Oscillator
    def get_stochastic_oscillator(self):
        slowk, slowd = ta.STOCH(self._data['high'], self._data['low'], self._data['close'], fastk_period=5, slowk_period=3, slowk_matype=0, slowd_period=3, slowd_matype=0)
        slowd = slowd.tolist()
        slowk = slowk.tolist()

        buy = sell = hold = False
        if slowk[-1] > slowd[-1] and slowk[-2] <= slowd[-2]:
            buy = True
        elif slowk[-1] < slowd[-1] and slowk[-2] >= slowd[-2]:
            sell = True
        else:
            hold = True
        return {'buy': buy, 'sell': sell, 'hold': hold}

    # MACD (Moving Average Convergence Divergence)
    def get_macd(self):
        macd, signal, _ = ta.MACD(self._data['close'], fastperiod=12, slowperiod=26, signalperiod=9)
        macd_list = macd.tolist()
        signal_list = signal.tolist()

        # convert macd and signal to percentage arrays
        macd = macd / self._data['close']
        signal = signal / self._data['close']

        buy = macd_list[-1] > signal_list[-1] and macd_list[-2] <= signal_list[-2]
        sell = macd_list[-1] < signal_list[-1] and macd_list[-2] >= signal_list[-2]
        return {'buy': buy, 'sell': sell}