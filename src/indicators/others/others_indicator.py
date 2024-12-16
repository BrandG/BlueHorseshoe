from indicators.others.fibonacci_retracement import FibonacciRetracement
from indicators.others.pivot_points import PivotPoints


class OtherIndicators():

    _fibBuyMultiplier = 1
    _fibSellMultiplier = 1
    _pivotBuyMultiplier = 1
    _pivotSellMultiplier = 1

    def __init__(self, data):
        self.update(data)

    def update(self, data):
        if data['fibBuyMultiplier']:
            self._fibBuyMultiplier = data['fibBuyMultiplier']
        if data['fibSellMultiplier']:
            self._fibSellMultiplier = data['fibSellMultiplier']
        if data['pivotBuyMultiplier']:
            self._pivotBuyMultiplier = data['pivotBuyMultiplier']
        if data['pivotSellMultiplier']:
            self._pivotSellMultiplier = data['pivotSellMultiplier']
        self._data = data
        self._fib = FibonacciRetracement(self._data).value
        self._pivot = PivotPoints(self._data).value

    @property
    def value(self):
        buy = (1 if self._fib['buy'] else 0) * self._fibBuyMultiplier + \
            (1 if self._pivot['buy'] else 0) * self._pivotBuyMultiplier
        sell = (1 if self._fib['sell'] else 0) * self._fibSellMultiplier + \
            (1 if self._pivot['sell'] else 0) * self._pivotSellMultiplier
        return { 'fib_levels': self._fib['fib_levels'], 'retracement': self._fib['retracement'], 'price': self._fib['price'],
                'swing_high': self._fib['swing_high'], 'swing_low': self._fib['swing_low'], 'buy': buy, 'sell': sell }
        