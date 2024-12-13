
from predictors.average_drop import AverageDropPredictor


class PredictorAggregator:
    _data = {}

    def __init__(self, data):
        self.update(data)

    def update(self, data):
        self._data = data

    def aggregate(self, data = None):
        if data is not None:
            self._data = data

        results = {}

        results['adp'] = AverageDropPredictor(self._data).value

        results['drop'] = results['adp']['drop']

        return results
