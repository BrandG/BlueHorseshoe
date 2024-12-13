"""
Module: money_flow_index
This module contains the MoneyFlowIndex class which calculates the Money Flow Index (MFI) for given financial data.
The MFI is a momentum indicator that measures the inflow and outflow of money into a security over a specific period.

Classes:
    MoneyFlowIndex: A class to calculate and update the Money Flow Index (MFI) for given financial data.
"""

import numpy as np
import talib as ta

from globals import ReportSingleton


class MoneyFlowIndex:
    """
    A class to calculate and update the Money Flow Index (MFI) for given financial data.

    Attributes:
        _data (dict): A dictionary containing financial data with keys 'high', 'low', 'close', and 'volume'.
        _mfi_data (list): A list containing the calculated MFI values.

    Methods:
        __init__(data): Initializes the MoneyFlowIndex with the given financial data.
        update(data): Updates the MFI values with the given financial data.
        value: Returns a dictionary indicating buy or sell signals based on the MFI values.
        graph_this(): Placeholder method to graph the MFI values.
    """

    def __init__(self, data):
        """
        Initializes the MoneyFlowIndex instance with the provided data.

        Args:
            data (pandas.DataFrame): The input data required to calculate the Money Flow Index.
        """
        self.update(data)

    def update(self, data):
        """
        Update the Money Flow Index (MFI) data with new market data.

        Parameters:
        data (dict): A dictionary containing market data with keys 'high', 'low', 'close', and 'volume'.
                 Each key should map to a list or array of corresponding values.

        Returns:
        None
        """
        self._data = data

        self._mfi_data = ta.MFI(self._data['high'], self._data['low'], self._data['close'],  # type: ignore
                          self._data['volume'], timeperiod=14).tolist()

    @property
    def value(self):
        """
        Calculate the Money Flow Index (MFI) value and determine buy/sell signals.

        The function returns a dictionary with 'buy' and 'sell' signals based on the 
        MFI value. A 'buy' signal is generated if the MFI is below the 15th percentile 
        of the historical MFI data, and a 'sell' signal is generated if the MFI is 
        above the 85th percentile of the historical MFI data.

        Returns:
            dict: A dictionary with 'buy' and 'sell' keys, where the values are 
              booleans indicating whether to buy or sell.
        """
        mfi = self._mfi_data[-1]
        return {'buy': bool(mfi < np.percentile(self._mfi_data, 15)), 'sell': bool(mfi > np.percentile(self._mfi_data, 85))}

    # pylint: disable=unused-variable
    def graph_this(self):
        """
        Generates a graph for the Money Flow Index (MFI) data and writes it to the report.

        This method retrieves the MFI data stored in the instance and writes it to the report
        using the ReportSingleton instance. The actual graph generation logic needs to be implemented.

        To Do:
            - Implement the logic to generate the graph for the MFI data.

        """
        # To Do: Fill this in
        ReportSingleton().write(self._mfi_data)
