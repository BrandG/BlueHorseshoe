"""
This module contains the implementation of the Relative Strength Index (RSI) indicator.
The RSI is a momentum oscillator that measures the speed and change of price movements.

Classes:
    RelativeStrengthIndex: A class to calculate and update the RSI based on provided data.
"""
import talib as ta
from globals import ReportSingleton
from indicators.indicator import Indicator


class RelativeStrengthIndex(Indicator):
    """
    A class to calculate and update the Relative Strength Index (RSI) based on provided data.

    Attributes:
        _data (pandas.DataFrame): The input data containing 'close' prices.
        rsi_data (numpy.ndarray): The calculated RSI values.

    Methods:
        __init__(data): Initializes the RSI with the provided data.
        update(data): Updates the RSI with new data.
        __str__(): Returns a string representation of the latest RSI value.
        graph(): Placeholder method to graph the RSI values.
        value(): Returns a dictionary indicating buy/sell signals based on the RSI value.
    """

    def __init__(self, data):
        """
        Initializes the RelativeStrengthIndex instance with the provided data.

        Args:
            data (list or pandas.Series): The input data for calculating the RSI.
        """
        self.update(data)

    def update(self, data):
        """
        Updates the RSI (Relative Strength Index) data with the provided market data.

        Args:
            data (pd.DataFrame): A DataFrame containing market data with at least a 'close' column.

        Returns:
            None
        """
        self._data = data
        self.rsi_data = ta.RSI(self._data['close'],  # type: ignore
                            timeperiod=14)

    def __str__(self):
        """
        Returns a string representation of the Relative Strength Index (RSI) object.

        The string representation includes the most recent RSI value formatted to two decimal places.

        Returns:
            str: A string in the format 'RSI: <most_recent_rsi_value>'.
        """
        return f'RSI: {self.rsi_data.tolist()[-1]:.2f}'

    # pylint: disable=unused-variable
    def graph(self):
        """
        Generates a graph for the Relative Strength Index (RSI) data and writes the latest RSI value to the report.

        This method is currently a placeholder and needs to be implemented to generate the actual graph.

        To Do:
            - Implement the graph generation logic for RSI data.
            - Ensure the graph is properly displayed or saved.
            - Write the latest RSI value to the report using the ReportSingleton.

        """
        # To Do: Fill this in
        ReportSingleton().write(self.rsi_data.tolist()[-1])

    @property
    def value(self):
        """
        Determine buy or sell signals based on the latest RSI value.

        Returns:
            dict: A dictionary with 'buy' and 'sell' keys. 
              'buy' is True if the latest RSI value is less than 15, otherwise False.
              'sell' is True if the latest RSI value is greater than 85, otherwise False.
              If there is no RSI data, both 'buy' and 'sell' are False.
        """
        if len(self.rsi_data) > 0:
            rsi = self.rsi_data.tolist()[-1]
            return {'buy': bool(rsi < 15), 'sell': bool(rsi > 85)}
        return {'buy': False, 'sell': False}
