"""
momentum_indicators.py
This module contains the MomentumIndicator class, which is used to calculate multiple
momentum-based technical indicators using a given dataset of daily stock data. The class
provides methods to compute RSI, Rate of Change (ROC), MACD, Bollinger Band Position, and
aggregates their scores into a final buy and sell indicator.
Classes:
    MomentumIndicator: A class to calculate various momentum-based technical indicators.
Constants:
    RSI_MULTIPLIER (float): Multiplier for the RSI score.
    ROC_MULTIPLIER (float): Multiplier for the ROC score.
    MACD_MULTIPLIER (float): Multiplier for the MACD score.
    MACD_SIGNAL_MULTIPLIER (float): Multiplier for the MACD signal score.
    BB_MULTIPLIER (float): Multiplier for the Bollinger Bands position score.
Methods:
    __init__(data: pd.DataFrame):
    calculate_rsi() -> float:
    calculate_roc() -> float:
    calculate_macd() -> float:
    calculate_bb_position() -> float:
    get_score() -> IndicatorScore:
    graph():
"""

import numpy as np
import pandas as pd

from bluehorseshoe.analysis.indicators.indicator import Indicator, IndicatorScore

RSI_MULTIPLIER = 1.0
ROC_MULTIPLIER = 1.0
MACD_MULTIPLIER = 1.0
MACD_SIGNAL_MULTIPLIER = 0.15
BB_MULTIPLIER = 1.0

class MomentumIndicator(Indicator):
    """
    MomentumIndicator
    A class to calculate multiple momentum-based technical indicators using a given
    dataset of daily stock data, typically containing columns such as 'close', 'high',
    and 'low'. This class provides methods to compute RSI, Rate of Change (ROC), MACD,
    Bollinger Band Position, and aggregates their scores into a final buy and sell indicator.
        Initialize the MomentumIndicator with daily stock data.
        Parameters
        ----------
        data : pd.DataFrame
            The daily stock data. Must contain 'close', 'high', and 'low' columns,
            and may include additional columns required by other indicator calculations.
        Calculate a label based on the most recent 5-day rate of change (roc_5) in the dataset.
        int
            A label indicating the significance of the most recent 5-day rate of change (0, 1, or 2).
            The MACD score for the most recent day.
        Calculate the position of the most recent closing price within the Bollinger Bands.
            A numeric indicator of the Bollinger Bands position based on these rules:
    def get_score(self) -> 'IndicatorScore':
        Compute the overall buy and sell scores derived from various momentum indicators.
        This method calculates partial scores from MACD, ROC, RSI, and the position within
        Bollinger Bands, combining them into a single buy score. A sell score is currently
        set to 0. Returns an IndicatorScore dataclass containing the buy_score and sell_score.
        IndicatorScore
            An object containing the aggregated buy and sell scores based on momentum indicators.
        Reserved for visualizing indicators.
        This method can be implemented in the future to plot or otherwise display
        the relevant technical indicator data for analysis.
        """

    def __init__(self, data: pd.DataFrame):
        self.required_cols = ['close', 'high', 'low']
        super().__init__(data)

    def calculate_rsi(self) -> float:
        """
        Calculate an RSI-based score for the last recorded day.

        This method checks the 'rsi_14' value in the most recent row of data (yesterday).
        It returns:
        • 2 if the RSI is between 45 and 65 (inclusive),
        • 1 if the RSI is between 40 and 70 (inclusive),
        • 0 otherwise.

        If 'rsi_14' is not present in the latest row, the score defaults to 0.

        Returns
        -------
        float
            A numeric rating based on the RSI value in the last row of self.days.
        """
        yesterday = self.days.iloc[-1]
        if 'rsi_14' in yesterday:
            return np.select(
                [
                    (yesterday['rsi_14'] >= 45) & (yesterday['rsi_14'] <= 65),
                    (yesterday['rsi_14'] >= 40) & (yesterday['rsi_14'] <= 70)
                ],
                [2, 1],
                0
            ).item()
        return 0

    def calculate_roc(self) -> float:
        """
        Calculates a label based on the most recent 5-day rate of change (roc_5) in the dataset.

        This function compares the current roc_5 value against the 20-day rolling standard
        deviation of roc_5. If the current roc_5 is greater than twice the rolling standard
        deviation, the function returns 2. If it is greater than once the rolling standard
        deviation, the function returns 1. Otherwise, it returns 0.

        Returns:
            int: A label indicating the significance of the most recent 5-day rate of change
            (0, 1, or 2).
        """
        yesterday = self.days.iloc[-1]
        if 'roc_5' in yesterday:
            # Rolling std over entire dataset
            roc_5_std = self.days['roc_5'].rolling(window=20).std().iloc[-1]
            if pd.notna(roc_5_std):
                return np.select(
                    [(yesterday['roc_5'] > 2 * roc_5_std), (yesterday['roc_5'] > 1 * roc_5_std)],
                    [2, 1],
                    default=0
                ).item()
        return 0

    def calculate_macd(self) -> float:
        """
        Calculate a MACD-based score for the most recent day of data.

        Examines the 'macd_line' and 'macd_signal' values from the last row in the 
        data frame to determine whether the MACD difference is positive. Returns an 
        integer score based on the relative difference between 'macd_line' and 
        'macd_signal' compared to a predefined multiplier. If the necessary columns 
        are missing or conditions are not met, returns 0.

        Returns:
            float: The MACD score for the most recent day.
        """
        yesterday = self.days.iloc[-1]
        if {'macd_line', 'macd_signal'}.issubset(yesterday):
            macd_diff = yesterday['macd_line'] - yesterday['macd_signal']
            # If MACD diff and line are positive, score 1 or 2 depending on how large the diff is
            if (macd_diff > 0) and (yesterday['macd_line'] > 0):
                return np.select(
                    [macd_diff > yesterday['macd_signal'] * MACD_SIGNAL_MULTIPLIER, macd_diff > yesterday['macd_signal']],
                    [2, 1],
                    0
                ).item()
        return 0

    def calculate_bb_position(self) -> float:
        """
        Calculates the position of the most recent closing price within the Bollinger Bands.

        This method uses the lower and upper Bollinger Bands to determine the ratio of the
        latest closing price within that band range. Depending on the position (calculated
        as a fraction of the distance between the lower and upper bands), it returns an
        integer value representing different market conditions.

        Returns:
            float: A numeric indicator of the Bollinger Bands position based on these rules:
                • 2 if the position is between 0.3 and 0.7 (inclusive of 0.3, exclusive of 0.7)
                • 3 if the position is between 0.1 and 0.3 (inclusive of 0.1, exclusive of 0.3)
                • -1 if the position is greater than or equal to 0.85
                • 0 otherwise
        """
        yesterday = self.days.iloc[-1]
        bb_position = 0.0
        if ('bb_lower' in yesterday and 'bb_upper' in yesterday and (yesterday['bb_upper'] > yesterday['bb_lower'])):
            band_range = yesterday['bb_upper'] - yesterday['bb_lower']
            bb_position = (yesterday['close'] - yesterday['bb_lower']) / band_range

            return np.select(
                [
                    (bb_position >= 0.3) & (bb_position < 0.7),
                    (bb_position >= 0.1) & (bb_position < 0.3),
                    bb_position >= 0.85
                ],
                [2, 3, -1],
                default=0
            ).item()
        return 0

    def get_score(self) -> IndicatorScore:
        buy_score = 0.0

        buy_score += self.calculate_macd() * MACD_MULTIPLIER
        buy_score += self.calculate_roc() * ROC_MULTIPLIER
        buy_score += self.calculate_rsi() * RSI_MULTIPLIER
        buy_score += self.calculate_bb_position() * BB_MULTIPLIER
        sell_score = 0.0

        return IndicatorScore(buy_score, sell_score)

    def graph(self):
        pass
