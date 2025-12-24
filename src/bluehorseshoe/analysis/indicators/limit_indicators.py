"""
A class to calculate and analyze pivot points for financial data.
This class provides methods to calculate Classic Pivot Points (P, R1, R2, S1, S2)
based on historical high, low, and close prices, and to score the behavior of
prices relative to these pivot levels.
"""

import numpy as np
import pandas as pd
from bluehorseshoe.reporting.report_generator import GraphData, graph
from bluehorseshoe.analysis.indicators.indicator import Indicator, IndicatorScore

PIVOT_MULTIPLIER = 1.0
FIFTY_TWO_WEEK_MULTIPLIER = 1.0

class LimitIndicator(Indicator):
    """
    A class to calculate and analyze pivot points for financial data.
    This class provides methods to calculate Classic Pivot Points (P, R1, R2, S1, S2)
    based on historical high, low, and close prices, and to score the behavior of 
    prices relative to these pivot levels.
    Attributes:
        data (pd.DataFrame): A DataFrame containing the financial data with required columns 'close', 'high', and 'low'.
    Methods:
        calculate_pivot_points() -> pd.DataFrame:
            Calculates Classic Pivot Points for each row based on the previous row's data.
        _score_pivot_levels(proximity_pct: float = 0.5) -> float:
            Scores how price behaves near or beyond pivot levels.
        calculate_score() -> int:
            Calculates the score based on pivot levels and a predefined multiplier.
    """

    def __init__(self, data: pd.DataFrame):
        self.symbol = 'NONAME'
        self.required_cols = ['close', 'high', 'low']
        super().__init__(data)
        self.days = self.calculate_pivot_points()

    def set_title(self, symbol: str) :
        """
        Sets the title for the provided symbol by appending an underscore.

        Args:
            symbol (str): The base symbol to modify.

        Returns:
            self: The current instance for chaining.
        """
        self.symbol = symbol+'_'
        return self

    def calculate_pivot_points(self) -> pd.DataFrame:
        """
        Calculates Classic Pivot Points (P, R1, R2, S1, S2) for each row
        based on the previous row's High, Low, and Close.
        
        Returns df with additional columns: 'Pivot', 'R1', 'R2', 'S1', 'S2'.
        """
        # Shift by 1 so we use "yesterday's" data for today's pivots
        high_prev = self.days['high'].shift(1)
        low_prev = self.days['low'].shift(1)
        close_prev = self.days['close'].shift(1)

        # Classic Pivot
        pivot = (high_prev + low_prev + close_prev) / 3.0

        # R1, S1, R2, S2
        r1 = 2 * pivot - low_prev
        s1 = 2 * pivot - high_prev
        r2 = pivot + (r1 - s1)
        s2 = pivot - (r1 - s1)

        # Attach columns
        self.days['Pivot'] = pivot
        self.days['R1'] = r1
        self.days['R2'] = r2
        self.days['S1'] = s1
        self.days['S2'] = s2

        return self.days

    def score_pivot_levels(self, proximity_pct: float = 0.5) -> float:
        """
        Scores how price behaves near or beyond pivot levels:
        - If Close is above R2 => +2
        - Else if Close is above R1 => +1
        - If Close is below S2 => -2
        - Else if Close is below S1 => -1
        - If today's Low is close to Pivot => +1 (small bounce signal)
        
        :param df: DataFrame with columns: 'Pivot', 'R1', 'R2', 'S1', 'S2', 'Close', 'Low'
        :param proximity_pct: if Low is within this % of Pivot, consider it a bounce
        :return: a float score
        """
        if len(self.days) == 0:
            return 0.0

        last = self.days.iloc[-1]
        if pd.isna(last['Pivot']):
            return 0.0  # pivot is NaN for first row or missing data

        score = 0.0

        close_price = last['close']
        pivot = last['Pivot']
        r1 = last['R1']
        r2 = last['R2']
        s1 = last['S1']
        s2 = last['S2']

        # 1) Check strong bullish or bearish levels
        if close_price > r2:
            score += 2
        elif close_price > r1:
            score += 1
        elif close_price < s2:
            score -= 2
        elif close_price < s1:
            score -= 1

        # 2) Check for "bounce near pivot"
        #    i.e., today's low is within (pivot +/- proximity%)
        #    If pivot=100, proximity_pct=0.5 => 0.5% => 100 * 0.005 = 0.5 points
        #    You can also do % of pivot range or absolute difference—up to you.
        daily_low = last['low']
        pivot_proximity = pivot * (proximity_pct / 100.0)  # 0.5% of pivot
        if abs(pivot - daily_low) <= pivot_proximity:
            # We can say that we "bounced" off pivot => +1
            score += 1

        return score

    def score_52_week_range(self, window: int = 252) -> float:
        """
        Scores if the Close price is at a 52-week high.
        If Close is at a 52-week high => +1
        Otherwise => 0
        
        :param window: lookback window for the 52-week high
        :return: a float score
        """
        if len(self.days) < window:
            return 0.0

        last = self.days.iloc[-1]
        close_price = last['close']

        # Compute the 52-week high
        high_52_week = self.days['high'].rolling(window=window, min_periods=1).max().iloc[-1]
        low_52_week = self.days['low'].rolling(window=window, min_periods=1).min().iloc[-1]

        position = (close_price - low_52_week) / (high_52_week - low_52_week) * 100

        return 1.0 if position >= 90 else -1.0 if position <= 10 else 0.0

    def get_score(self) -> IndicatorScore:
        """
        Calculate the score based on pivot levels and a multiplier.

        This method calculates the score by summing the product of the pivot levels score
        and a predefined multiplier.

        Returns:
            int: The calculated score.
        """
        buy_score = 0.0

        buy_score += self.score_pivot_levels() * PIVOT_MULTIPLIER
        buy_score += self.score_52_week_range() * FIFTY_TWO_WEEK_MULTIPLIER
        sell_score = 0.0

        return IndicatorScore(buy_score, sell_score)

    def graph(self):
        graph_data = GraphData(
            labels={'x_label':'Date', 'y_label':'Price', 'title':self.symbol+'Limit_Indicators'},
            curves=[],
        )
        price_list = self.days['close'].tolist()[-60:]
        graph_data.curves.append({"curve": price_list, "color": "k", "label": "Price"})
        found_one = False
        if self.score_pivot_levels() != 0:
            found_one = True
            graph_data.lines.append({'y': self.days['Pivot'].tolist()[-1], 'color': 'b', 'label': 'Pivot'})
            graph_data.lines.append({'y': self.days['R1'].tolist()[-1], 'color': 'g', 'label': 'R1'})
            graph_data.lines.append({'y': self.days['R2'].tolist()[-1], 'color': 'y', 'label': 'R2'})
            graph_data.lines.append({'y': self.days['S1'].tolist()[-1], 'color': 'r', 'label': 'S1'})
            graph_data.lines.append({'y': self.days['S2'].tolist()[-1], 'color': 'c', 'label': 'S2'})
        if self.score_52_week_range() != 0:
            found_one = True
            high_52_week = self.days['high'].rolling(window=252, min_periods=1).max().iloc[-1]
            low_52_week = self.days['low'].rolling(window=252, min_periods=1).min().iloc[-1]
            graph_data.lines.append({'line': high_52_week, 'color': 'm', 'label': '52 week high'})
            graph_data.lines.append({'line': low_52_week, 'color': 'm', 'label': '52 week low'})

        if found_one:
            graph(graph_data)
