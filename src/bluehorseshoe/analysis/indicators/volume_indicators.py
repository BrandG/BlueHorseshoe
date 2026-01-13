"""
This module provides the `VolumeIndicator` class for calculating a score based on various volume indicators.

Classes:
    VolumeIndicator: A class to calculate a score based on volume indicators.

Constants:
    self.weights['OBV_MULTIPLIER'] (float): Multiplier for the On-Balance Volume (OBV) score.
    self.weights['CMF_MULTIPLIER'] (float): Multiplier for the Chaikin Money Flow (CMF) score.
    self.weights['ATR_BAND_MULTIPLIER'] (float): Multiplier for the Average True Range (ATR) band score.
    self.weights['ATR_SPIKE_MULTIPLIER'] (float): Multiplier for the ATR spike score.
    DEFAULT_WINDOW (int): Default window size for calculations.

Methods:
    __init__(self, data: pd.DataFrame):
        Initializes the VolumeIndicator with the provided data.

    score_atr_spike(self, window: int = 14, spike_multiplier: float = 1.5) -> float:

    score_atr_band(self, ma_window: int = 20, atr_multiplier: float = 2.0) -> float:
        Otherwise => 0.

    calculate_cmf_with_ta(self, window: int = 20, threshold: float = 0.05) -> float:

    score_obv_trend(self, window: int = 5) -> float:

    calculate_score(self) -> float:
"""
from typing import Optional
import numpy as np
import pandas as pd
from ta.volume import OnBalanceVolumeIndicator, ChaikinMoneyFlowIndicator #pylint: disable=import-error
from ta.volatility import AverageTrueRange # pylint: disable=import-error

from bluehorseshoe.analysis.indicators.indicator import Indicator, IndicatorScore
from bluehorseshoe.core.config import weights_config





DEFAULT_WINDOW = 14

class VolumeIndicator(Indicator):
    """
    A class to calculate a score based on volume indicators.
    """

    def __init__(self, data: pd.DataFrame):
        self.weights = weights_config.get_weights('volume')
        self.required_cols = ['high', 'low', 'close', 'volume']
        super().__init__(data)

        if DEFAULT_WINDOW <= len(self.days):
            self.days['ATR'] = AverageTrueRange(
                high=self.days['high'],
                low=self.days['low'],
                close=self.days['close'],
                window=DEFAULT_WINDOW
            ).average_true_range()

    def score_atr_spike(self, window: int = 14, spike_multiplier: float = 1.5) -> float:
        """
        Checks if today's ATR is more than 'spike_multiplier' times the ATR from 'window' bars ago.
        If so, returns -2 (indicating high volatility => more risk).
        Otherwise returns 0.
        """

        if 'ATR' not in self.days.columns or len(self.days) < window + 1:
            return 0.0  # Not enough data or ATR not computed

        atr_today = self.days.iloc[-1]['ATR']
        atr_past = self.days.iloc[-(window+1)]['ATR']

        if atr_past == 0 or pd.isna(atr_past):
            return 0.0

        # If today's ATR is 1.5x or more of what it was 'window' days ago => volatility spike
        if atr_today >= spike_multiplier * atr_past:
            return -2.0
        return 0.0

    def score_atr_band(self,
                    ma_window: int = 20,
                    atr_multiplier: float = 2.0) -> float:
        """
        Checks if the last close is beyond (MA +/- ATR_multiplier * ATR).
        If close > MA + X * ATR => potentially overbought => -1
        If close < MA - X * ATR => potentially oversold => +1
        Otherwise => 0
        """
        if 'ATR' not in self.days.columns or len(self.days) == 0:
            return 0.0

        # Compute the moving average of 'Close'
        self.days['MA'] = self.days['close'].rolling(window=ma_window, min_periods=1).mean()

        last_row = self.days.iloc[-1]
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

    def calculate_avg_volume(self, window: int = 20) -> float:
        """
        Calculates the average volume over the last 'window' days.
        """
        if len(self.days) < window:
            return 0.0

        avg_volume = self.days['volume'].tail(window).mean()
        if avg_volume < 100000:
            return -1.0
        return 1.0

    def calculate_cmf_with_ta(self, window: int = 20, threshold: float = 0.05) -> float:
        """
        Calculates Chaikin Money Flow (CMF) using the 'ta' library and
        adds a new column 'CMF' to self.days.

        Expects columns: 'high', 'low', 'close', 'volume'.
        The 'window' is typically 20.
        """
        cmf = ChaikinMoneyFlowIndicator(
            high=self.days['high'],
            low=self.days['low'],
            close=self.days['close'],
            volume=self.days['volume'],
            window=window
        ).chaikin_money_flow()

        cmf_value = cmf.iloc[-1]
        return float(np.select(
            [ pd.isna(cmf_value), cmf_value > threshold, cmf_value > 0, cmf_value < -threshold ],
            [0.0, 2.0, 1.0, -2.0],
            default=-1.0))

    def score_obv_trend(self, window: int = 5) -> float:
        """
        Returns a score based on whether OBV is rising or falling
        over the last 'window' days.
        """
        self.days['OBV'] = OnBalanceVolumeIndicator( close=self.days['close'], volume=self.days['volume'] ).on_balance_volume()

        if len(self.days) < window + 1:
            return 0.0  # Not enough data to compute a slope

        # OBV difference over 'window' days
        obv_diff = self.days.iloc[-1]['OBV'] - self.days.iloc[-(window+1)]['OBV']

        return float(np.select([obv_diff > 0, obv_diff < 0], [1, -1], default=0))

    def get_score(self, enabled_sub_indicators: Optional[list[str]] = None, aggregation: str = "sum") -> IndicatorScore:
        """
        Returns a score based on the volume indicators.
        """
        buy_score = 1.0 if aggregation == "product" else 0.0
        active_count = 0

        sub_map = {
            'obv': (self.score_obv_trend, 'OBV_MULTIPLIER'),
            'cmf': (self.calculate_cmf_with_ta, 'CMF_MULTIPLIER'),
            'atr_band': (self.score_atr_band, 'ATR_BAND_MULTIPLIER'),
            'atr_spike': (self.score_atr_spike, 'ATR_SPIKE_MULTIPLIER'),
            'avg_volume': (self.calculate_avg_volume, None)
        }

        for name, (func, weight_key) in sub_map.items():
            if enabled_sub_indicators is None or name in enabled_sub_indicators:
                multiplier = self.weights[weight_key] if weight_key else 1.0
                score = func() * multiplier  # pylint: disable=not-callable
                if aggregation == "product":
                    buy_score *= score
                else:
                    buy_score += score
                active_count += 1

        if active_count == 0 or (aggregation == "product" and buy_score == 0):
            buy_score = 0.0

        sell_score = 0.0
        return IndicatorScore(buy_score, sell_score)

    def graph(self) -> None:
        pass
