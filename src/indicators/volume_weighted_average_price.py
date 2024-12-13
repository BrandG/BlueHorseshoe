"""
Module: volume_weighted_average_price
This module contains the VolumeWeightedAveragePrice class which calculates the Volume Weighted Average Price (VWAP) for a given set of stock data.
"""
class VolumeWeightedAveragePrice:
    """
    A class used to calculate the Volume Weighted Average Price (VWAP) for a given set of stock data.

    Attributes
    ----------
    _data : pandas.DataFrame
        A DataFrame containing stock data with 'close' and 'volume' columns.
    _vwap : pandas.Series
        A Series containing the calculated VWAP values.

    Methods
    -------
    __init__(data)
        Initializes the VolumeWeightedAveragePrice with the given data.
    update(data)
        Updates the VWAP calculation with new data.
    value()
        Returns the direction of the stock price relative to the VWAP.
    """

    def __init__(self, data):
        """
        Initializes the instance with the provided data.

        Args:
            data (any): The data to initialize the instance with.
        """
        self.update(data)

    def update(self, data):
        """
        Update the Volume Weighted Average Price (VWAP) with new data.

        Parameters:
        data (pd.DataFrame): A pandas DataFrame containing 'close' and 'volume' columns.

        The method calculates the VWAP by taking the cumulative sum of the product of 
        'close' prices and 'volume', and dividing it by the cumulative sum of 'volume'.
        """
        self._data = data

        self._vwap = (self._data['close'] * self._data['volume']).cumsum() / self._data['volume'].cumsum()

    @property
    def value(self):
        """
        Determines the direction of the price relative to the Volume Weighted Average Price (VWAP).

        Returns:
            dict: A dictionary with the key 'direction' and value 'up' if the latest closing price is greater than the latest VWAP, otherwise 'down'.
        """
        return {'direction': 'up' if self._data['close'].tolist()[-1] > self._vwap.tolist()[-1] else 'down'}
