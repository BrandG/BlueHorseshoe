from indicators.volume.money_flow_index import MoneyFlowIndex
from indicators.volume.on_balance_volume import OnBalanceVolume
from indicators.volume.volume_weighted_average_price import VolumeWeightedAveragePrice


class VolumeIndicators:
    mfiBuyMultiplier = 1
    mfiSellMultiplier = 1
    obvDirectionMultiplier = 1
    vwapDirectionMultiplier = 1

    def __init__(self, data):
        self.update(data)

    def update(self, data):
        if 'mfiBuyMultiplier' in data:
            self.mfiBuyMultiplier = data['mfiBuyMultiplier']
        if 'mfiSellMultiplier' in data:
            self.mfiSellMultiplier = data['mfiSellMultiplier']
        if 'obvDirectionMultiplier' in data:
            self.obvDirectionMultiplier = data['obvDirectionMultiplier']
        if 'vwapDirectionMultiplier' in data:
            self.vwapDirectionMultiplier = data['vwapDirectionMultiplier']

        self._data = data
        self._mfi = MoneyFlowIndex(self._data).value # returns {buy, sell}
        self._obv = OnBalanceVolume(self._data).value # returns {direction}
        self._vwap = VolumeWeightedAveragePrice(self._data).value # returns {direction}
        
    @property
    def value(self):
        buy = (1 if self._mfi['buy'] else 0) * self.mfiBuyMultiplier
        
        sell = (1 if self._mfi['sell'] else 0) * self.mfiSellMultiplier

        direction = (
            (1 if self._vwap['direction'] == 'up' else 0) * self.vwapDirectionMultiplier +
            (1 if self._obv['direction'] == 'up' else 0) * self.obvDirectionMultiplier
        )

        return { 'buy': buy, 'sell': sell, 'direction': direction }

