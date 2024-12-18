"""
Module: indicators.indicator
This module contains the abstract base class `Indicator` for financial indicators.
The `Indicator` class defines the interface for financial indicators, which includes methods
for updating the indicator with new data, calculating the value of the indicator, and graphing
the indicator data. Subclasses should implement these methods to provide specific functionality
for different types of indicators.
Classes:
    Indicator: Abstract base class for financial indicators.
Usage example:
    class MovingAverage(Indicator):
            super().__init__(data)
            return sum(self.data) / len(self.data)
            import matplotlib.pyplot as plt
            plt.plot(self.data)
            plt.show()
"""

from abc import abstractmethod

class Indicator:
    """
    Abstract base class for financial indicators.

    This class defines the interface for financial indicators, which includes methods
    for updating the indicator with new data, calculating the value of the indicator,
    and graphing the indicator data. Subclasses should implement these methods to
    provide specific functionality for different types of indicators.

    Methods:
        __init__(data): Initializes the indicator with the given data.
        update(data): Updates the indicator with new data.
        value: Calculates the value of the indicator.
        graph(): Graphs the indicator data.
    """
    @abstractmethod
    def __init__(self, data):
        self.update(data)

    @abstractmethod
    def update(self, data):
        """
        Updates the indicator with new data.

        Parameters:
        data (any): The new data to update the indicator with.
        """
        self.data = data

    @property
    @abstractmethod
    def value(self):
        """
        Calculate the value of the indicator.

        This method should be implemented by subclasses to provide the specific
        calculation logic for the indicator.

        Raises:
            NotImplementedError: If the method is not implemented by a subclass.
        """
        raise NotImplementedError("Subclasses should implement this method")

    @abstractmethod
    def graph(self):
        """
        Graph the indicator data.

        This method should be implemented by subclasses to provide the specific
        graphing functionality for the indicator. It raises a NotImplementedError
        if not overridden in a subclass.

        Raises:
            NotImplementedError: If the method is not implemented in a subclass.
        """
        raise NotImplementedError("Subclasses should implement this method")
    