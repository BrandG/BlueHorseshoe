class VolumeWeightedAveragePrice:

    def __init__(self, data):
        self.update(data)

    def update(self, data):
        self._data = data

        self._vwap = (self._data['close'] * self._data['volume']).cumsum() / self._data['volume'].cumsum()
        
    @property
    def value(self):
        return {'direction': 'up' if self._data['close'].tolist()[-1] > self._vwap.tolist()[-1] else 'down'}
