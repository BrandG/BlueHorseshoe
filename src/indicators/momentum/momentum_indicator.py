from indicators.momentum.macd import MACD
from indicators.momentum.relative_strength_index import RelativeStrengthIndex
from indicators.momentum.stochastic_oscillator import StochasticOscillator


class MomentumIndicator():

    _macdBuyMultiplier = 1
    _macdSellMultiplier = 1
    _rsiBuyMultiplier = 1
    _rsiSellMultiplier = 1
    _stochBuyMultiplier = 1
    _stochSellMultiplier = 1

    def __init__(self, data):
        self.update(data)

    def update(self, data):
        if 'macdBuyMultiplier' in data:
            self._macdBuyMultiplier = data['macdBuyMultiplier']
        if 'macdSellMultiplier' in data:
            self._macdSellMultiplier = data['macdSellMultiplier']
        if 'rsiBuyMultiplier' in data:
            self._rsiBuyMultiplier = data['rsiBuyMultiplier']
        if 'rsiSellMultiplier' in data:
            self._rsiSellMultiplier = data['rsiSellMultiplier']
        if 'stochBuyMultiplier' in data:
            self._stochBuyMultiplier = data['stochBuyMultiplier']
        if 'stochSellMultiplier' in data:
            self._stochSellMultiplier = data['stochSellMultiplier']
        self._data = data

        self._macd = MACD(self._data).value
        self._rsi = RelativeStrengthIndex(self._data).value
        self._stochastic_oscillator = StochasticOscillator(self._data).value

    @property
    def value(self):
        buy = (1 if self._macd['buy'] else 0) * self._macdBuyMultiplier + \
            (1 if self._rsi['buy'] else 0) * self._rsiBuyMultiplier + \
            (1 if self._stochastic_oscillator['buy'] else 0) * self._stochBuyMultiplier
        sell = (1 if self._macd['sell'] else 0) * self._macdSellMultiplier + \
            (1 if self._rsi['sell'] else 0) * self._rsiSellMultiplier + \
            (1 if self._stochastic_oscillator['sell'] else 0) * self._stochSellMultiplier
        hold = 1 if self._stochastic_oscillator['hold'] else 0
        return { 'buy': buy, 'sell': sell, 'hold': hold }
