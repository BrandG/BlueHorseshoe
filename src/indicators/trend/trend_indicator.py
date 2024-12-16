from indicators.trend.ichimoku import Ichimoku
from indicators.trend.average_directional_index import AverageDirectionalIndex
from indicators.trend.commodity_channel_index import CCITrend
from indicators.trend.ema_crossover import EMACrossover


class TrendIndicators:
    emaBuyMultiplier = 1
    emaSellMultiplier = 1
    ichimokuBuyMultiplier = 1
    ichimokuSellMultiplier = 1
    cciBuyMultiplier = 1
    cciSellMultiplier = 1
    adxBuyMultiplier = 1
    adxSellMultiplier = 1
    adxUpMultiplier = 1
    adxDownMultiplier = 1

    def __init__(self, data):
        self.update(data)

    def update(self, data):
        self._data = data
        self._emas = EMACrossover(self._data).value
        self._ichimoku = Ichimoku(self._data).value
        self._cci = CCITrend(self._data).value
        self._adx = AverageDirectionalIndex(self._data).value

    @property
    def value(self):
        buy = (1 if self._emas['buy'] else 0) * self.emaBuyMultiplier + \
             (1 if self._ichimoku['buy'] else 0) * self.ichimokuBuyMultiplier + \
            (1 if self._cci['buy'] else 0) * self.cciBuyMultiplier
        
        sell = (1 if self._emas['sell'] else 0) * self.emaSellMultiplier + \
             (1 if self._ichimoku['sell'] else 0) * self.ichimokuSellMultiplier + \
            (1 if self._cci['sell'] else 0) * self.cciSellMultiplier
        
        up = (1 if self._adx['up'] else 0) * self.adxUpMultiplier

        down = (1 if self._adx['down'] else 0) * self.adxDownMultiplier

        strength = self._ichimoku['strength'] + self._adx['strength']
        
        return { 'buy': buy, 'sell': sell, 'up': up, 'down': down, 'strength': strength }

