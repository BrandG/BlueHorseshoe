"""
This module provides the `VolumeIndicator` class for calculating a score based on various volume indicators.

Classes:
    VolumeIndicator: A class to calculate a score based on volume indicators.

Constants:
    OBV_MULTIPLIER (float): Multiplier for the On-Balance Volume (OBV) score.
    CMF_MULTIPLIER (float): Multiplier for the Chaikin Money Flow (CMF) score.
    ATR_BAND_MULTIPLIER (float): Multiplier for the Average True Range (ATR) band score.
    ATR_SPIKE_MULTIPLIER (float): Multiplier for the ATR spike score.
    DEFAULT_WINDOW (int): Default window size for calculations.

Methods:
    __init__(self, data: pd.DataFrame):
        Initializes the VolumeIndicator with the provided data.

    score_atr_spike(self, window: int = 14, spike_multiplier: float = 1.5) -> float:

    _score_atr_band(self, ma_window: int = 20, atr_multiplier: float = 2.0) -> float:
        Otherwise => 0.

    _calculate_cmf_with_ta(self, window: int = 20, threshold: float = 0.05) -> float:

    _score_obv_trend(self, window: int = 5) -> float:

    calculate_score(self) -> float:
"""
import numpy as np
import pandas as pd
from ta.volume import OnBalanceVolumeIndicator, ChaikinMoneyFlowIndicator #pylint: disable=import-error
from ta.volatility import AverageTrueRange #pylint: disable=import-error

OBV_MULTIPLIER = 1.0
CMF_MULTIPLIER = 1.0
ATR_BAND_MULTIPLIER = 1.0
ATR_SPIKE_MULTIPLIER = 1.0
DEFAULT_WINDOW = 14

class VolumeIndicator:
    """
    A class to calculate a score based on volume indicators.
    """

    def __init__(self, data: pd.DataFrame):
        required_cols = ['high', 'low', 'close', 'volume']
        self.data = data[required_cols].copy()

        if DEFAULT_WINDOW <= len(self.data):
            self.data['ATR'] = AverageTrueRange(
                high=self.data['high'],
                low=self.data['low'],
                close=self.data['close'],
                window=DEFAULT_WINDOW
            ).average_true_range()

    def score_atr_spike(self, window: int = 14, spike_multiplier: float = 1.5) -> float:
        """
        Checks if today's ATR is more than 'spike_multiplier' times the ATR from 'window' bars ago.
        If so, returns -2 (indicating high volatility => more risk).
        Otherwise returns 0.
        """

        df = self.data
        if 'ATR' not in df.columns or len(df) < window + 1:
            return 0.0  # Not enough data or ATR not computed

        atr_today = df.iloc[-1]['ATR']
        atr_past = df.iloc[-(window+1)]['ATR']

        if atr_past == 0 or pd.isna(atr_past):
            return 0.0

        # If today's ATR is 1.5x or more of what it was 'window' days ago => volatility spike
        if atr_today >= spike_multiplier * atr_past:
            return -2.0
        return 0.0

    def _score_atr_band(self,
                    ma_window: int = 20,
                    atr_multiplier: float = 2.0) -> float:
        """
        Checks if the last close is beyond (MA +/- ATR_multiplier * ATR).
        If close > MA + X * ATR => potentially overbought => -1
        If close < MA - X * ATR => potentially oversold => +1
        Otherwise => 0
        """
        df = self.data
        if 'ATR' not in df.columns or len(df) == 0:
            return 0.0

        # Compute the moving average of 'Close'
        df['MA'] = df['close'].rolling(window=ma_window, min_periods=1).mean()

        last_row = df.iloc[-1]
        if pd.isna(last_row['ATR']):
            return 0.0

        ma = last_row['MA']
        atr = last_row['ATR']
        close = last_row['close']

        upper_band = ma + atr_multiplier * atr
        lower_band = ma - atr_multiplier * atr

        if close > upper_band:
            return -1.0  # Overextended or overbought
        if close < lower_band:
            return +1.0  # Oversold

        return 0.0

    def _calculate_avg_volume(self, window: int = 20) -> float:
        """
        Calculates the average volume over the last 'window' days.
        """
        df = self.data
        if len(df) < window:
            return 0.0

        avg_volume = df['volume'].tail(window).mean()
        if avg_volume < 100000:
            return -1.0
        return 1.0

    def _calculate_cmf_with_ta(self, window: int = 20, threshold: float = 0.05) -> float:
        """
        Calculates Chaikin Money Flow (CMF) using the 'ta' library and
        adds a new column 'CMF' to df.

        Expects columns: 'high', 'low', 'close', 'volume'.
        The 'window' is typically 20.
        """
        df = self.data
        cmf = ChaikinMoneyFlowIndicator(
            high=df['high'],
            low=df['low'],
            close=df['close'],
            volume=df['volume'],
            window=window
        ).chaikin_money_flow()

        cmf_value = cmf.iloc[-1]
        return float(np.select(
            [ pd.isna(cmf_value), cmf_value > threshold, cmf_value > 0, cmf_value < -threshold ],
            [0.0, 2.0, 1.0, -2.0],
            default=-1.0)) * CMF_MULTIPLIER

    def _score_obv_trend(self, window: int = 5) -> float:
        """
        Returns a score based on whether OBV is rising or falling
        over the last 'window' days.
        """
        df = self.data
        df['OBV'] = OnBalanceVolumeIndicator( close=df['close'], volume=df['volume'] ).on_balance_volume()

        if len(df) < window + 1:
            return 0.0  # Not enough data to compute a slope

        # OBV difference over 'window' days
        obv_diff = df.iloc[-1]['OBV'] - df.iloc[-(window+1)]['OBV']

        return float(np.select([obv_diff > 0, obv_diff < 0], [0, 1], default=0)) * OBV_MULTIPLIER

    def calculate_score(self):
        """
        Returns a score based on the volume indicators.
        """
        score = 0

        score += self._score_obv_trend() * OBV_MULTIPLIER
        score += self._calculate_cmf_with_ta() * CMF_MULTIPLIER
        score += self._score_atr_band() * ATR_BAND_MULTIPLIER
        score += self.score_atr_spike() * ATR_SPIKE_MULTIPLIER
        score += self._calculate_avg_volume() # No multiplier

        return score
