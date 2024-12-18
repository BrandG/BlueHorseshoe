from indicators.volatility.average_true_range import AverageTrueRange
from indicators.volatility.bollinger_bands import BollingerBands
from indicators.volatility.standard_deviation import StandardDeviation


class VolatilityIndicators:
    atrBuyMultiplier = 1
    atrSellMultiplier = 1
    atrVolatilityMultiplier = 1
    bbVolatilityMultiplier = 1
    bbBuyMultiplier = 1
    bbSellMultiplier = 1
    stdevVolatilityMultiplier = 1
    atrStopLossLongMultiplier = 1
    atrStopLossShortMultiplier = 1
    stdevMultiplier = 1

    def __init__(self, data):
        self.update(data)

    def update(self, data):
        if 'atrBuyMultiplier' in data:
            self.atrBuyMultiplier = data['atrBuyMultiplier']
        if 'atrSellMultiplier' in data:
            self.atrSellMultiplier = data['atrSellMultiplier']
        if 'atrVolatilityMultiplier' in data:
            self.atrVolatilityMultiplier = data['atrVolatilityMultiplier']
        if 'bbBuyMultiplier' in data:
            self.bbBuyMultiplier = data['bbBuyMultiplier']
        if 'bbSellMultiplier' in data:
            self.bbSellMultiplier = data['bbSellMultiplier']
        if 'bbVolatilityMultiplier' in data:
            self.bbVolatilityMultiplier = data['bbVolatilityMultiplier']
        if 'stdevVolatilityMultiplier' in data:
            self.stdevVolatilityMultiplier = data['stdevVolatilityMultiplier']
        if 'atrStopLossLongMultiplier' in data:
            self.atrStopLossLongMultiplier = data['atrStopLossLongMultiplier']
        if 'atrStopLossShortMultiplier' in data:
            self.atrStopLossShortMultiplier = data['atrStopLossShortMultiplier']
        if 'stdevMultiplier' in data:
            self.stdevMultiplier = 1
        self._data = data
        self._atr = AverageTrueRange(self._data).value # returns {volatility, stop_loss_long, stop_loss_short, buy, sell}
        self._bollinger = BollingerBands(self._data).value # returns {buy, sell, volatility}
        self._stdev = StandardDeviation(self._data).value # returns {current_stdev, volatility}
        
    @property
    def value(self):
        buy = (
            (1 if self._atr['buy'] else 0) * self.atrBuyMultiplier + 
             (1 if self._bollinger['buy'] else 0) * self.bbBuyMultiplier
        )
        
        sell = (
            (1 if self._atr['sell'] else 0) * self.atrSellMultiplier +
            (1 if self._bollinger['sell'] else 0) * self.bbSellMultiplier
        )

        volatility = (
            (1 if self._atr['volatility'] == 'high' else 0) * self.atrVolatilityMultiplier +
            (1 if self._bollinger['volatility'] == 'high' else 0) * self.bbVolatilityMultiplier +
            (1 if self._stdev['volatility'] == 'high' else 0) * self.stdevVolatilityMultiplier
        )

        stop_loss_long = self._atr['stop_loss_long'] * self.atrStopLossLongMultiplier

        stop_loss_short = self._atr['stop_loss_short'] * self.atrStopLossShortMultiplier                

        std_dev = self._stdev['current_stdev'] * self.stdevMultiplier

        return { 'buy': buy, 'sell': sell, 'volatility': volatility, 'stop_loss_long': stop_loss_long, 'stop_loss_short': stop_loss_short, 'stdev': std_dev }

