"""
Module: predictor_aggregator
This module contains the PredictorAggregator class which is responsible for aggregating predictions from various predictors.

Classes:
    PredictorAggregator: Aggregates predictions from different predictors.

Usage example:
    data = {...}
    aggregator = PredictorAggregator(data)
    results = aggregator.aggregate()
"""

from predictors.average_drop import AverageDropPredictor


class PredictorAggregator:
    """
    A class used to aggregate predictions from various predictors.

    Attributes:
        _data (dict): A dictionary to store the data for predictions.

    Methods:
        __init__(self, data):
            Initializes the PredictorAggregator with the given data.
        
        update(self, data):
            Updates the internal data with the given data.
        
        aggregate(self, data=None):
            Aggregates predictions from various predictors and returns the results.
    """
    _data = {}

    def __init__(self, data):
        """
        Initializes the predictor aggregator with the given data.

        Args:
            data (any): The data to initialize the predictor aggregator with.
        """
        self.update(data)

    def update(self, data):
        """
        Updates the internal data with the provided data.

        Args:
            data: The new data to update.
        """
        self._data = data

    def aggregate(self, data = None):
        """
        Aggregates prediction results from various predictors.

        Parameters:
        data (optional): The data to be used for aggregation. If not provided, 
                 the existing data in the instance will be used.

        Returns:
        dict: A dictionary containing the aggregated results. The dictionary 
              includes the following keys:
              - 'adp': The result from the AverageDropPredictor.
              - 'drop': The 'drop' value extracted from the 'adp' result.
        """
        if data is not None:
            self._data = data

        results = {}

        results['adp'] = AverageDropPredictor(self._data).value

        results['drop'] = results['adp']['drop']

        return results
