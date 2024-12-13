"""
This module contains the implementation of the OnBalanceVolume class, which calculates the On-Balance Volume (OBV) indicator
using the TA-Lib library. The OBV is a technical analysis indicator that relates price and volume to measure buying and selling pressure.
"""

import talib as ta
from globals import ReportSingleton

class OnBalanceVolume:
    """
    A class used to calculate the On-Balance Volume (OBV) indicator.

    Attributes
    ----------
    _data : pandas.DataFrame
        The input data containing 'close' prices and 'volume'.
    _obv : pandas.Series
        The calculated OBV values.

    Methods
    -------
    __init__(data)
        Initializes the OnBalanceVolume instance with the provided data.
    update(data)
        Updates the internal data and recalculates the OBV values.
    value()
        Returns the direction of the OBV as 'up' or 'down'.
    graph()
        Placeholder method to graph the OBV values.
    """

    def __init__(self, data):
        """
        Initializes the OnBalanceVolume indicator with the provided data.

        Args:
            data (list or pandas.Series): The input data for the indicator.
        """
        self.update(data)

    def update(self, data):
        """
        Update the internal data and calculate the On-Balance Volume (OBV).

        Parameters:
        data (pandas.DataFrame): A DataFrame containing 'close' and 'volume' columns.

        Returns:
        None
        """
        self._data = data

        self._obv = ta.OBV(self._data['close'], self._data['volume'])  # type: ignore

    @property
    def value(self):
        """
        Calculate the direction of the On-Balance Volume (OBV).

        Returns:
            dict: A dictionary with the key 'direction' indicating the direction of OBV.
                  Possible values are:
                  - 'up': if the latest OBV value is greater than the previous one.
                  - 'down': if the latest OBV value is less than or equal to the previous one.
                  - 'error': if there are fewer than 2 OBV values.
        """
        if len(self._obv) < 2:
            return {'direction': 'error'}
        return {'direction': 'up' if self._obv.iloc[-1] > self._obv.iloc[-2] else 'down'}

    # pylint: disable=unused-variable
    def graph(self):
        """
        Generates a graph for the On-Balance Volume (OBV) indicator and writes it to the report.

        This method is responsible for creating a visual representation of the OBV indicator
        and saving it using the ReportSingleton instance.

        To Do:
            - Implement the logic to generate the OBV graph.

        """
        # To Do: Fill this in
        ReportSingleton().write(self._obv)
