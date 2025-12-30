"""
trend_indicators.py
This module provides a class `TrendIndicator` to calculate a trend score based on multiple technical indicators.
The indicators used include:
The `TrendIndicator` class validates the input DataFrame to ensure it contains the required columns and provides methods to calculate scores based
on each indicator. The final trend score is a combination of these individual scores.

Classes:
    TrendIndicator: A class to calculate a trend score based on various technical indicators.
Constants:
    self.weights['STOCHASTIC_MULTIPLIER'] (float): Multiplier for the Stochastic Oscillator score.
    self.weights['ICHIMOKU_MULTIPLIER'] (float): Multiplier for the Ichimoku Cloud score.
    self.weights['PSAR_MULTIPLIER'] (float): Multiplier for the Parabolic SAR score.
    self.weights['HEIKEN_ASHI_MULTIPLIER'] (float): Multiplier for the Heiken Ashi score.
    REQUIRED_COLUMNS (set): Set of required columns in the input DataFrame.
Methods:
    __init__(self, data: pd.DataFrame): Initializes the TrendIndicator with the given data.
    validate_columns(self, df): Validates that the DataFrame has the required columns.
    calculate_psar_score(df: pd.DataFrame, step: float = 0.02, max_step: float = 0.2) -> float: Calculates a Parabolic SAR flip-based score.
    calculate_ichimoku(df): Calculates Ichimoku indicator lines and adds them to the DataFrame.
    calculate_ichimoku_score(self, days: pd.DataFrame) -> float: Calculates the Ichimoku-based score.
    calculate_heiken_ashi(self, days) -> float: Computes Heiken Ashi candles and calculates the score.
    calculate_score(self): Calculates the overall trend score based on all indicators.
"""

import numpy as np
import pandas as pd
from ta.trend import PSARIndicator # pylint: disable=import-error

from bluehorseshoe.analysis.indicators.indicator import Indicator, IndicatorScore
from bluehorseshoe.core.config import weights_config







class TrendIndicator(Indicator):
    """
    Class to calculate a trend score based on the following indicators:
    - Stochastic Oscillator
    - Ichimoku Cloud
    - Parabolic SAR
    - Heiken Ashi
    - ADX (Directional Movement Index)
    """

    def __init__(self, data: pd.DataFrame):
        self.weights = weights_config.get_weights('trend')
        self.required_cols = ['high', 'low', 'close', 'open', 'stoch_k', 'stoch_d']
        super().__init__(data)

    def calculate_dmi_adx(self) -> float:
        """
        Calculates a numerical score for the ADX (Average Directional Index) based on the previous day's
        DMI (Directional Movement Index) positive and negative components. If the positive DMI is higher
        than the negative DMI, this function returns an integer score corresponding to the ADX value:
            • Returns 3 if ADX is above 35.
            • Returns 2 if ADX is above 30 (but 35 or below).
            • Returns 1 if ADX is above 25 (but 30 or below).
            • Returns 0 otherwise.

        Returns:
            float: An integer-converted float representing the ADX-related score based on DMI.
        """
        yesterday = self.days.iloc[-1]
        if {'dmi_p', 'dmi_n', 'adx'}.issubset(self.days.columns) and yesterday['dmi_p'] > yesterday['dmi_n']:
            # Score ADX levels: above 35 => +3, above 30 => +2, above 25 => +1
            return np.select([yesterday['adx'] > 35, yesterday['adx'] > 30, yesterday['adx'] > 25],
                             [3, 2, 1], 0).item() if yesterday['dmi_p'] > yesterday['dmi_n'] else 0
        return 0.0

    def calculate_psar_score(self, step: float = 0.02, max_step: float = 0.2) -> float:
        """
        Calculates a Parabolic SAR flip-based score for the latest row in 'df'.
        
        Parabolic SAR flips if it moves from above price to below price (bullish) 
        or from below price to above price (bearish).
        
        :param df:       DataFrame with columns ['High', 'Low', 'Close'].
        :param step:     The AF (acceleration factor) initial step, commonly 0.02.
        :param max_step: The maximum step for AF, commonly 0.2.
        :return:         A float representing the SAR-based score for the latest row.
        """

        # Ensure we have enough data for at least 2 rows (to detect a flip)
        if len(self.days) < 2:
            return 0.0

        # 1) Compute Parabolic SAR using the 'ta' library
        psar_indicator = PSARIndicator(
            high=self.days['high'],
            low=self.days['low'],
            close=self.days['close'],
            step=step,
            max_step=max_step,
            fillna=True
        )

        # The library provides the psar values for each row
        self.days['psar'] = psar_indicator.psar().astype(float)

        # 2) Identify if there's a flip from yesterday to today
        #    We'll see if SAR was above price vs. below price, day-to-day.

        # Today's values
        psar_above_today = self.days.iloc[-1]['psar'] > self.days.iloc[-1]['close']

        # Yesterday's values
        psar_above_yesterday = self.days.iloc[-2]['psar'] > self.days.iloc[-2]['close']

        # If Parabolic SAR was above price yesterday but is now below => bullish flip
        if psar_above_yesterday and not psar_above_today:
            # e.g. +2 points for a bullish flip
            return 2.0

        # If Parabolic SAR was below price yesterday but is now above => bearish flip
        return -2.0 if not psar_above_yesterday and psar_above_today else 0.0

    def calculate_ichimoku(self):
        """
        Calculate Ichimoku indicator lines and add them to df.
        Expects columns: 'high', 'low', 'close'.
        Returns df with new columns:
        'tenkan', 'kijun', 'spanA', 'spanB', 'chikou'
        """
        # Tenkan-sen (Conversion Line) - 9 period
        high_9 = self.days['high'].rolling(window=9).max()
        low_9 = self.days['low'].rolling(window=9).min()
        self.days['tenkan'] = (high_9 + low_9) / 2

        # Kijun-sen (Base Line) - 26 period
        high_26 = self.days['high'].rolling(window=26).max()
        low_26 = self.days['low'].rolling(window=26).min()
        self.days['kijun'] = (high_26 + low_26) / 2

        # Senkou Span A (Leading Span A) = (tenkan + kijun) / 2, shifted forward 26
        self.days['spanA'] = ((self.days['tenkan'] + self.days['kijun']) / 2).shift(26)

        # Senkou Span B (Leading Span B) - 52 period, also shifted forward 26
        high_52 = self.days['high'].rolling(window=52).max()
        low_52 = self.days['low'].rolling(window=52).min()
        self.days['spanB'] = ((high_52 + low_52) / 2).shift(26)

        # Chikou Span (Lagging Span) - Close shifted back 26 periods
        self.days['chikou'] = self.days['close'].shift(-26)

        return self.days

    def calculate_ichimoku_score(self) -> float:
        """
        Calculate your existing technical score, plus Ichimoku-based signals.
        self.days is your DataFrame with Ichimoku columns: 'tenkan', 'kijun', 'spanA', 'spanB', 'Close'.
        Returns a float score.
        """
        days = self.calculate_ichimoku()

        # 1) Suppose you already have your existing score from RSI, MACD, etc.
        score = 0

        # 2) Extract the last row's data as a dictionary or Series
        last_row = days.iloc[-1]

        # 3) Price vs. Cloud check
        #    Need to ensure we don't have NaN for 'spanA'/'spanB' due to the forward shift
        span_a = last_row['spanA']
        span_b = last_row['spanB']
        close = last_row['close']

        # Handle if spanA or spanB is NaN (which can happen near the latest 26 days)
        if pd.notna(span_a) and pd.notna(span_b):
            top_of_cloud = max(span_a, span_b)
            bottom_of_cloud = min(span_a, span_b)

            if close > top_of_cloud:
                # Price is above the cloud => bullish
                score += 2
            elif close < bottom_of_cloud:
                # Price is below the cloud => bearish
                score -= 2
            else:
                # Price in the cloud => neutral
                score += 0  # or +1 or -1, up to you

        # 4) Tenkan vs. Kijun cross
        # We'll compare today's tenkan & kijun with yesterday's to detect crossovers
        if len(days) > 1:
            tenkan_now = last_row['tenkan']
            kijun_now = last_row['kijun']
            tenkan_prev = days.iloc[-2]['tenkan']
            kijun_prev = days.iloc[-2]['kijun']

            if pd.notna(tenkan_now) and pd.notna(kijun_now) and pd.notna(tenkan_prev) and pd.notna(kijun_prev):
                # Bullish cross
                if (tenkan_now > kijun_now) and (tenkan_prev <= kijun_prev):
                    score += 2  # or +1
                # Bearish cross
                elif (tenkan_now < kijun_now) and (tenkan_prev >= kijun_prev):
                    score -= 2  # or -1

        # 5) Span A vs. Span B color
        if pd.notna(span_a) and pd.notna(span_b):
            if span_a > span_b:
                # "Green" cloud => bullish environment
                score += 1
            else:
                # "Red" cloud => bearish environment
                score -= 1

        return float(score)

    def calculate_heiken_ashi(self) -> float:
        """
        Computes Heiken Ashi candles for the given DataFrame (df),
        which should have columns: ['open', 'High', 'Low', 'Close'].

        Returns a new DataFrame with columns:
        'HA_open', 'HA_High', 'HA_Low', 'HA_Close'
        """

        self.days['HA_close'] = (self.days['open'] + self.days['high'] + self.days['low'] + self.days['close']) / 4.0
        self.days['HA_open'] = (self.days['open'].shift(1) + self.days['close'].shift(1)) / 2.0
        self.days['HA_high'] = self.days[['high', 'HA_open', 'HA_close']].max(axis=1)
        self.days['HA_low'] = self.days[['low', 'HA_open', 'HA_close']].min(axis=1)

        last_row = self.days.iloc[-1]
        ha_open  = last_row['HA_open']
        ha_close = last_row['HA_close']

        score = 0.0

        # For example, count the last n candles if they're all bullish:
        last_n_rows = self.days.iloc[-3:]
        bullish_count = last_n_rows[last_n_rows['HA_close'] > last_n_rows['HA_open']].shape[0]

        # If all 3 are bullish => +2, if 2 are bullish => +1, etc.
        if bullish_count == 3:
            score += 3
        elif bullish_count == 2:
            score += 2
        elif bullish_count == 1:
            score += 1.0
        elif ha_close < ha_open:
            # Subtract points for bearish
            score -= 1.0
        else:
            # If they're equal or we have some odd scenario, 0 => no effect
            pass

        return score

    def get_score(self) -> IndicatorScore:
        """
        Calculate the trend score based on the following indicators:
        - Stochastic Oscillator
        - Ichimoku Cloud
        - Parabolic SAR
        - Heiken Ashi

        Returns a float score.
        """

        buy_score = 0.0

        # Shifted columns to detect crossovers from previous day:
        k_prev = self.days['stoch_k'].shift(1)
        d_prev = self.days['stoch_d'].shift(1)

        # Conditions:
        crossover_up = ((self.days['stoch_k'] > self.days['stoch_d']) & (k_prev <= d_prev)).iloc[-1]  # cross up
        crossover_down = ((self.days['stoch_k'] < self.days['stoch_d']) & (k_prev >= d_prev)).iloc[-1]  # cross down
        oversold = (self.days['stoch_k'] < 20).iloc[-1]
        overbought = (self.days['stoch_k'] > 80).iloc[-1]

        buy_score += np.select( [ crossover_up, crossover_down, oversold, overbought ] , [ 2, -2, 1, -1 ], default=0).sum() * self.weights['STOCHASTIC_MULTIPLIER']
        buy_score += self.calculate_ichimoku_score() * self.weights['ICHIMOKU_MULTIPLIER']
        buy_score += self.calculate_psar_score() * self.weights['PSAR_MULTIPLIER']
        buy_score += self.calculate_heiken_ashi() * self.weights['HEIKEN_ASHI_MULTIPLIER']
        buy_score += self.calculate_dmi_adx() * self.weights['ADX_MULTIPLIER']
        sell_score = 0.0

        return IndicatorScore(buy=buy_score, sell=sell_score)

    def graph(self) -> None:
        pass
