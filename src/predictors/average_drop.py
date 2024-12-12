class AverageDropPredictor:
    def __init__(self, data):
        self.update(data)

    def update(self, data):
        self._data = data

    @property
    def value(self):
        deltas = []
        for i in range(len(self._data) - 1):
            if self._data['close'][i] != 0 and self._data['close'][i] != self._data['close'][i]:
                continue
            delta = round(float(self._data['low'][i + 1] - self._data['close'][i]),2)
            deltas.append(delta)

        if len(deltas) == 0:
            return {'drop': 0, 'next open': self._data["close"].to_list()[-1]}

        average_delta = round(sum(deltas) / len(deltas),2)
        next_open = self._data["close"].to_list()[-1] + average_delta

        return {'drop': average_delta, 'next open': next_open}
