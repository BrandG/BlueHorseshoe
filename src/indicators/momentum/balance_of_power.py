"""
BOP(open, high, low, close)
    BOP(open, high, low, close)
    
	Zero-Line Crossover upwards is bullish
	Zero-Line Crossover downwards is bearish
    
    Inputs:
        prices: ['open', 'high', 'low', 'close']
    Outputs:
        real

"""
from indicators.indicator import Indicator
import talib as ta

class BalanceOfPower(Indicator):
    _data = None

    def __init__(self, data):
        self.update(data)

    def update(self, data):
        self._data = data

        self._data = self._data.sort_values(by='date').reset_index(drop=True)

        # Calculate APO
        self._bop = ta.BOP(     # type: ignore
            self._data['open'],
            self._data['high'],
            self._data['low'],
            self._data['close']
        )

    @property
    def value(self):
        if len(self._bop) <= 2:
            return {'direction': 'error', 'buy': False, 'sell': False}
        
        boplist = self._bop.tolist()
        if boplist[-1] > 0 and boplist[-2] <= 0:
            buy = True
            sell = False
        elif boplist[-1] < 0 and boplist[-2] >= 0:
            buy = False
            sell = True
        smoothed_bop = ta.EMA(self._bop, timeperiod=9) # type: ignore
        smoothed_bop_list = smoothed_bop.tolist()
        buy = smoothed_bop.rolling(window=10).mean().iloc[-1] > 0
        sell = smoothed_bop.rolling(window=10).mean().iloc[-1] < 0
        if smoothed_bop_list[-1] > 0.5:
            direction = 'up'
        elif smoothed_bop_list[-1] < -0.5:
            direction = 'down'
        else:
            direction = 'sideways'
        return {
            'buy': buy,
            'sell': sell,
            'direction': direction,
        }

    # pylint: disable=unused-variable
    def graph(self):
        pass
