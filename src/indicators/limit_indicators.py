"""
A class to calculate and analyze pivot points for financial data.
This class provides methods to calculate Classic Pivot Points (P, R1, R2, S1, S2)
based on historical high, low, and close prices, and to score the behavior of
prices relative to these pivot levels.
"""

import pandas as pd

PIVOT_MULTIPLIER = 1.0
FIFTY_TWO_WEEK_MULTIPLIER = 1.0

class LimitIndicator:
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
        required_cols = ['close', 'high', 'low']
        self.data = data[required_cols].copy()
        self.data = self.calculate_pivot_points()

    def calculate_pivot_points(self) -> pd.DataFrame:
        """
        Calculates Classic Pivot Points (P, R1, R2, S1, S2) for each row
        based on the previous row's High, Low, and Close.
        
        Returns df with additional columns: 'Pivot', 'R1', 'R2', 'S1', 'S2'.
        """
        df = self.data

        # Shift by 1 so we use "yesterday's" data for today's pivots
        high_prev = df['high'].shift(1)
        low_prev = df['low'].shift(1)
        close_prev = df['close'].shift(1)

        # Classic Pivot
        pivot = (high_prev + low_prev + close_prev) / 3.0

        # R1, S1, R2, S2
        r1 = 2 * pivot - low_prev
        s1 = 2 * pivot - high_prev
        r2 = pivot + (r1 - s1)
        s2 = pivot - (r1 - s1)

        # Attach columns
        df['Pivot'] = pivot
        df['R1'] = r1
        df['R2'] = r2
        df['S1'] = s1
        df['S2'] = s2

        return df

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
        df = self.data
        if len(df) == 0:
            return 0.0

        last = df.iloc[-1]
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
        df = self.data
        if len(df) < window:
            return 0.0

        last = df.iloc[-1]
        close_price = last['close']

        # Compute the 52-week high
        high_52_week = df['high'].rolling(window=window, min_periods=1).max().iloc[-1]
        low_52_week = df['low'].rolling(window=window, min_periods=1).min().iloc[-1]

        position = (close_price - low_52_week) / (high_52_week - low_52_week) * 100

        return 1.0 if position >= 90 else -1.0 if position <= 10 else 0.0

    def calculate_score(self):
        """
        Calculate the score based on pivot levels and a multiplier.

        This method calculates the score by summing the product of the pivot levels score
        and a predefined multiplier.

        Returns:
            int: The calculated score.
        """
        score = 0

        score += self.score_pivot_levels() * PIVOT_MULTIPLIER
        score += self.score_52_week_range() * FIFTY_TWO_WEEK_MULTIPLIER

        return score
