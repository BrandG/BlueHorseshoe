from collections import namedtuple
import pandas as pd
from abc import ABC, abstractmethod

IndicatorScore = namedtuple('Score', ['buy', 'sell'])

class Indicator(ABC):

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
        pass

    @abstractmethod
    def graph(self) -> None:
        pass