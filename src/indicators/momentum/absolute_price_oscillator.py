"""
APO(real, fastperiod=-2147483648, slowperiod=-2147483648, matype=0)
    APO(real[, fastperiod=?, slowperiod=?, matype=?])
    
    Absolute Price Oscillator (Momentum Indicators)
	when the APO crosses above zero, it suggests that the price is gaining bullish momentum and sending a buy signal.
    
    Inputs:
        real: (any ndarray)
    Parameters:
        fastperiod: 12
        slowperiod: 26
        matype: 0 (Simple Moving Average)
    Outputs:
        real

"""
from indicators.indicator import Indicator
import talib as ta

class AbsolutePriceOscillator(Indicator):
    _data = None

    def __init__(self, data):
        self.update(data)

    def update(self, data):
        self._data = data

        self._data = self._data.sort_values(by='Date').reset_index(drop=True)

        # Calculate APO
        self._apo = ta.APO(     # type: ignore
            self._data['Close'],
            fastperiod=12,
            slowperiod=26,
            matype=0  # Simple MA
        )

        self._apo_signal = ta.EMA(self._data['APO'], timeperiod=9) # type: ignore

    @property
    def value(self):
        if len(self._apo) <= 2 or len(self._apo_signal) <= 2:
            return {'direction': 'error', 'buy': False, 'sell': False}
        
        apo_last = self._apo.iloc[-1]
        apo_prev = self._apo.iloc[-2]
        apo_signal_last = self._apo_signal.iloc[-1]
        apo_signal_prev = self._apo_signal.iloc[-2]

        signal = 0
        if (apo_last > apo_signal_last) and (apo_prev <= apo_signal_prev):
            signal = 1  # Bullish crossover
        elif (apo_last < apo_signal_last) and (apo_prev >= apo_signal_prev):
            signal = -1  # Bearish crossover

        return {
            'buy': signal == 1,
            'sell': signal == -1,
            'direction': 'up' if signal == 1 else 'down' if signal == -1 else 'sideways',
        }

    # pylint: disable=unused-variable
    def graph(self):
        pass
