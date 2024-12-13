"""
Module: average_drop

This module contains the AverageDropPredictor class, which calculates the average drop in stock prices based on historical data.
"""

class AverageDropPredictor:
    """
    A predictor class that calculates the average drop in stock prices and predicts the next opening price.

    Attributes:
        _data (DataFrame): The historical stock data.

    Methods:
        __init__(data):
            Initializes the predictor with the given data.
        
        update(data):
            Updates the predictor with new data.
        
        value:
            Calculates and returns the average drop and the predicted next opening price.
    """

    def __init__(self, data):
        """
        Initializes the predictor with the given data.

        Args:
            data (iterable): The data to initialize the predictor with.
        """
        self.update(data)

    def update(self, data):
        """
        Updates the internal data with the provided data.

        Args:
            data: The new data to be stored.
        """
        self._data = data

    @property
    def value(self):
        """
        Calculate the average drop in the 'low' price compared to the 'close' price for each day in the dataset,
        and predict the next 'open' price based on this average drop.

        Returns:
            dict: A dictionary with two keys:
            'drop' (float): The average drop in price.
            'next open' (float): The predicted next 'open' price based on the average drop.
        """
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
