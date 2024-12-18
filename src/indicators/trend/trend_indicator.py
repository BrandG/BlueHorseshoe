from indicators.trend.aroon import AROON
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
    adxDirectionMultiplier = 1
    aroonDirectionMultiplier = 1
    aroonBuyMultiplier = 1
    aroonSellMultiplier = 1

    def __init__(self, data):
        self.update(data)

    def update(self, data):
        if 'emaBuyMultiplier' in data:
            self.emaBuyMultiplier = data['emaBuyMultiplier']
        if 'emaSellMultiplier' in data:
            self.emaSellMultiplier = data['emaSellMultiplier']
        if 'ichimokuBuyMultiplier' in data:
            self.ichimokuBuyMultiplier = data['ichimokuBuyMultiplier']
        if 'ichimokuSellMultiplier' in data:
            self.ichimokuSellMultiplier = data['ichimokuSellMultiplier']
        if 'cciBuyMultiplier' in data:
            self.cciBuyMultiplier = data['cciBuyMultiplier']
        if 'cciSellMultiplier' in data:
            self.cciSellMultiplier = data['cciSellMultiplier']
        if 'adxDirectionMultiplier' in data:
            self.adxDirectionMultiplier = data['adxDirectionMultiplier']
        if 'aroonDirectionMultiplier' in data:
            self.aroonDirectionMultiplier = data['aroonDirectionMultiplier']
        if 'aroonBuyMultiplier' in data:
            self.aroonBuyMultiplier = data['aroonBuyMultiplier']
        if 'aroonSellMultiplier' in data:
            self.aroonSellMultiplier = data['aroonSellMultiplier']
        self._data = data
        self._emas = EMACrossover(self._data).value
        self._ichimoku = Ichimoku(self._data).value
        self._cci = CCITrend(self._data).value
        self._adx = AverageDirectionalIndex(self._data).value
        self._aroon = AROON(self._data).value

    @property
    def value(self):
        buy = (
            (1 if self._emas['buy'] else 0) * self.emaBuyMultiplier +
             self._ichimoku['buy'] * self.ichimokuBuyMultiplier +
            (1 if self._cci['buy'] else 0) * self.cciBuyMultiplier +
            (1 if self._aroon['buy'] else 0) * self.aroonBuyMultiplier
        )
        
        sell = (
            (1 if self._emas['sell'] else 0) * self.emaSellMultiplier +
             self._ichimoku['sell'] * self.ichimokuSellMultiplier +
            (1 if self._cci['sell'] else 0) * self.cciSellMultiplier +
            (1 if self._aroon['sell'] else 0) * self.aroonSellMultiplier
        )
        
        direction = (
            (1 if self._adx['direction'] == 'up' else 0) * self.adxDirectionMultiplier +
            (1 if self._aroon['direction'] == 'up' else 0) * self.aroonDirectionMultiplier
        )

        strength = (
            self._ichimoku['strength'] +
            self._adx['strength']
        )
        
        return { 'buy': buy, 'sell': sell, 'direction': direction, 'strength': strength }

