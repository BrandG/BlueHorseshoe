"""
Abstract base class for financial indicators.

This class provides a template for creating financial indicators that can
validate required columns in a DataFrame, calculate buy and sell scores, and
generate graphs. Subclasses should implement the `get_score` and `graph`
methods to provide specific functionality for different types of indicators.

Attributes:
    required_cols (list): A list of column names required in the input data.

Methods:
    __init__(data: pd.DataFrame):
        Initializes the Indicator with the provided data if it contains the
        required columns.

    _validate_columns(data: pd.DataFrame, columns: list[str]) -> bool:
        Validates that the provided data contains the required columns.

    get_score() -> IndicatorScore:
        Abstract method to calculate and return the buy and sell scores.
        Must be implemented by subclasses.

    graph() -> None:
        Abstract method to generate a graph for the indicator.
        Must be implemented by subclasses.
"""

from collections import namedtuple
from abc import ABC, abstractmethod
import pandas as pd

IndicatorScore = namedtuple('Score', ['buy', 'sell'])

class Indicator(ABC):
    """
    Abstract base class for financial indicators.

    This class provides a template for creating financial indicators that can
    validate required columns in a DataFrame, calculate buy and sell scores, and
    generate graphs. Subclasses should implement the `get_score` and `graph`
    methods to provide specific functionality for different types of indicators.

    Attributes:
        required_cols (list): A list of column names required in the input data.

    Methods:
        __init__(data: pd.DataFrame):
            Initializes the Indicator with the provided data if it contains the
            required columns.

        _validate_columns(data: pd.DataFrame, columns: list[str]) -> bool:
            Validates that the provided data contains the required columns.

        get_score() -> IndicatorScore:
            Abstract method to calculate and return the buy and sell scores.
            Must be implemented by subclasses.

        graph() -> None:
            Abstract method to generate a graph for the indicator.
            Must be implemented by subclasses.
    """

    required_cols = []

    def __init__(self, data: pd.DataFrame):
        if self._validate_columns(data, self.required_cols):
            self.days = data[self.required_cols].copy()
        else:
            self.days = pd.DataFrame()

    def _validate_columns(self, data: pd.DataFrame, columns: list[str] ) -> bool:
        for column in columns:
            if column not in data.columns:
                raise ValueError(f"Data is missing required columns: {columns}")
        return True

    @abstractmethod
    def get_score(self) -> IndicatorScore:
        """
        Calculate and return the buy and sell scores.

        Returns:
            tuple[float, float]: A tuple containing the buy score and the sell score.
        """
        return IndicatorScore(0.0, 0.0)

    @abstractmethod
    def graph(self) -> None:
        """
        Generates a graph for the indicator.

        This method is intended to be overridden by subclasses to provide
        specific graphing functionality for different types of indicators.

        Returns:
            None
        """
