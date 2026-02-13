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
    self.weights['ADX_MULTIPLIER'] (float): Multiplier for the ADX score.
    self.weights['DONCHIAN_MULTIPLIER'] (float): Multiplier for the Donchian Channel score.
    self.weights['SUPERTREND_MULTIPLIER'] (float): Multiplier for the SuperTrend score.
    REQUIRED_COLUMNS (set): Set of required columns in the input DataFrame.
Methods:
    __init__(self, data: pd.DataFrame): Initializes the TrendIndicator with the given data.
    validate_columns(self, df): Validates that the DataFrame has the required columns.
    calculate_psar_score(df: pd.DataFrame, step: float = 0.02, max_step: float = 0.2) -> float: Calculates a Parabolic SAR flip-based score.
    calculate_ichimoku(df): Calculates Ichimoku indicator lines and adds them to the DataFrame.
    calculate_ichimoku_score(self, days: pd.DataFrame) -> float: Calculates the Ichimoku-based score.
    calculate_heiken_ashi(self, days) -> float: Computes Heiken Ashi candles and calculates the score.
    calculate_donchian(self, window: int = 20) -> float: Calculates the Donchian Channel score.
    calculate_supertrend(self, period: int = 10, multiplier: float = 3.0) -> float: Calculates the SuperTrend score.
    calculate_score(self): Calculates the overall trend score based on all indicators.
"""

from typing import Optional
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from ta.trend import AroonIndicator # pylint: disable=import-error
from ta.volatility import DonchianChannel, AverageTrueRange # pylint: disable=import-error

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
    - Donchian Channels
    - SuperTrend
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
        Calculates a Parabolic SAR flip-based score using numpy arrays (no pandas iloc).

        Parabolic SAR flips if it moves from above price to below price (bullish)
        or from below price to above price (bearish).

        :param step:     The AF (acceleration factor) initial step, commonly 0.02.
        :param max_step: The maximum step for AF, commonly 0.2.
        :return:         A float representing the SAR-based score for the latest row.
        """
        n = len(self.days)
        if n < 2:
            return 0.0

        high = self.days['high'].values
        low = self.days['low'].values
        close = self.days['close'].values

        # Compute PSAR using numpy arrays
        psar = close.copy()
        up_trend = True
        af = step
        up_trend_high = high[0]
        down_trend_low = low[0]

        for i in range(2, n):
            reversal = False
            max_high = high[i]
            min_low = low[i]

            if up_trend:
                psar[i] = psar[i - 1] + af * (up_trend_high - psar[i - 1])

                if min_low < psar[i]:
                    reversal = True
                    psar[i] = up_trend_high
                    down_trend_low = min_low
                    af = step
                else:
                    if max_high > up_trend_high:
                        up_trend_high = max_high
                        af = min(af + step, max_step)

                    if low[i - 2] < psar[i]:
                        psar[i] = low[i - 2]
                    elif low[i - 1] < psar[i]:
                        psar[i] = low[i - 1]
            else:
                psar[i] = psar[i - 1] - af * (psar[i - 1] - down_trend_low)

                if max_high > psar[i]:
                    reversal = True
                    psar[i] = down_trend_low
                    up_trend_high = max_high
                    af = step
                else:
                    if min_low < down_trend_low:
                        down_trend_low = min_low
                        af = min(af + step, max_step)

                    if high[i - 2] > psar[i]:
                        psar[i] = high[i - 2]
                    elif high[i - 1] > psar[i]:
                        psar[i] = high[i - 1]

            up_trend = up_trend != reversal  # XOR

        # Detect flip between last two days
        psar_above_today = psar[-1] > close[-1]
        psar_above_yesterday = psar[-2] > close[-2]

        if psar_above_yesterday and not psar_above_today:
            return 2.0
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

    def calculate_donchian(self, window: int = 20) -> float:
        """
        Calculate Donchian Channel score.
        Upper Channel = Max High over window.
        Lower Channel = Min Low over window.
        
        Using shifted bands to detect breakout from previous N-day range.
        
        Returns:
            float:
            • 2 if Close > Upper Band (Shifted) - Breakout
            • 1 if Close > Middle Band (Shifted) - Uptrend
            • -2 if Close < Lower Band (Shifted) - Breakdown
            • -1 if Close < Middle Band (Shifted) - Downtrend
            • 0 otherwise
        """
        if len(self.days) < window:
             return 0.0
             
        dc = DonchianChannel(
            high=self.days['high'],
            low=self.days['low'],
            close=self.days['close'],
            window=window
        )
        
        # We shift by 1 to compare today's Close with the Channel of the PREVIOUS window
        # If we didn't shift, Upper Band would always be >= Close (since it's Max(High)).
        upper = dc.donchian_channel_hband().shift(1).iloc[-1]
        lower = dc.donchian_channel_lband().shift(1).iloc[-1]
        middle = dc.donchian_channel_mband().shift(1).iloc[-1]
        close = self.days['close'].iloc[-1]
        
        if pd.isna(upper) or pd.isna(lower):
            return 0.0
            
        if close > upper:
            return 2.0
        elif close < lower:
            return -2.0
        elif close > middle:
            return 1.0
        elif close < middle:
            return -1.0
            
        return 0.0

    def calculate_supertrend(self, period: int = 10, multiplier: float = 3.0) -> float:
        """
        Calculate SuperTrend score (OPTIMIZED VERSION).

        SuperTrend is an ATR-based trailing stop indicator.

        Returns:
        • 2 if Bullish Crossover (Trend flipped to Green today)
        • 1 if Bullish (Green)
        • -2 if Bearish Crossover (Trend flipped to Red today)
        • -1 if Bearish (Red)
        """
        if len(self.days) < period + 1:
             return 0.0

        # Convert to numpy arrays once (avoid repeated .iloc[] calls)
        high = self.days['high'].values
        low = self.days['low'].values
        close = self.days['close'].values

        # Calculate ATR using numpy
        atr_indicator = AverageTrueRange(
            self.days['high'],
            self.days['low'],
            self.days['close'],
            window=period
        )
        atr = atr_indicator.average_true_range().values

        # Vectorized calculations
        hl2 = (high + low) / 2
        basic_upper = hl2 + (multiplier * atr)
        basic_lower = hl2 - (multiplier * atr)

        # Initialize result arrays
        n = len(self.days)
        final_upper = np.zeros(n)
        final_lower = np.zeros(n)
        trend = np.zeros(n, dtype=np.int8)  # Use int8 for memory efficiency

        # Optimized iterative calculation using numpy arrays (no .iloc[])
        for i in range(1, n):
            # Final Upper
            if basic_upper[i] < final_upper[i-1] or close[i-1] > final_upper[i-1]:
                final_upper[i] = basic_upper[i]
            else:
                final_upper[i] = final_upper[i-1]

            # Final Lower
            if basic_lower[i] > final_lower[i-1] or close[i-1] < final_lower[i-1]:
                final_lower[i] = basic_lower[i]
            else:
                final_lower[i] = final_lower[i-1]

            # Trend
            curr_trend = trend[i-1]
            if curr_trend == 0:  # Initialization
                curr_trend = 1 if close[i] > final_upper[i] else -1

            if curr_trend == 1:
                if close[i] < final_lower[i]:
                    curr_trend = -1
            else:
                if close[i] > final_upper[i]:
                    curr_trend = 1

            trend[i] = curr_trend

        # Scoring
        curr = trend[-1]
        prev = trend[-2]

        if curr == 1 and prev == -1:
            return 2.0
        elif curr == -1 and prev == 1:
            return -2.0
        elif curr == 1:
            return 1.0
        elif curr == -1:
            return -1.0

        return 0.0

    def calculate_ttm_squeeze(self, bb_length: int = 20, bb_std: float = 2.0,
                              kc_length: int = 20, kc_atr_mult: float = 1.5) -> float:
        """
        Calculate TTM Squeeze score (OPTIMIZED).

        The squeeze occurs when Bollinger Bands compress inside Keltner Channels,
        indicating low volatility that often precedes explosive moves.

        Scoring:
        • +2.0 if squeeze just released with bullish momentum
        • +1.5 if in squeeze with price rising (coiling for breakout)
        • +0.5 if in squeeze with price flat
        • -1.0 if in squeeze with price falling
        • -2.0 if squeeze released with bearish momentum
        • 0.0 if no squeeze (normal volatility)

        Args:
            bb_length: Bollinger Bands period (default: 20)
            bb_std: Bollinger Bands standard deviation multiplier (default: 2.0)
            kc_length: Keltner Channel period (default: 20)
            kc_atr_mult: Keltner Channel ATR multiplier (default: 1.5)

        Returns:
            float: Score from -2.0 to +2.0 based on squeeze state
        """
        n = len(self.days)
        if n < max(bb_length, kc_length) + 5:
            return 0.0

        close = self.days['close'].values
        high = self.days['high'].values
        low = self.days['low'].values

        # 1. Bollinger Bands (NumPy)
        # sliding_window_view for SMA and Std
        # Shape: (n - bb_length + 1, bb_length)
        windows = sliding_window_view(close, window_shape=bb_length)
        
        # Mean and Std along axis 1
        # Pandas default ddof=1 (sample std), numpy default ddof=0
        bb_mean = np.mean(windows, axis=1)
        bb_std_val = np.std(windows, axis=1, ddof=1)
        
        bb_upper = bb_mean + (bb_std * bb_std_val)
        bb_lower = bb_mean - (bb_std * bb_std_val)
        bb_width = bb_upper - bb_lower
        
        # Pad BB width to match original length
        pad_len = bb_length - 1
        pad = np.zeros(pad_len)
        bb_width_padded = np.concatenate((pad, bb_width))

        # 2. Keltner Channels (Pandas for EMA/ATR)
        # EMA of Close (Middle Line)
        close_series = self.days['close']
        kc_mean = close_series.ewm(span=kc_length, adjust=False).mean().values
        
        # ATR Calculation (NumPy for TR, Pandas for EMA)
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0] # Handle first element
        
        tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
        
        # ATR uses EMA smoothing (Wilder's: alpha=1/n)
        tr_series = pd.Series(tr)
        atr = tr_series.ewm(alpha=1.0/kc_length, adjust=False).mean().values
        
        kc_upper = kc_mean + (kc_atr_mult * atr)
        kc_lower = kc_mean - (kc_atr_mult * atr)
        kc_width = kc_upper - kc_lower

        # Squeeze condition: BB inside KC (BB width < KC width)
        squeeze = bb_width_padded < kc_width

        # Current and previous squeeze state
        in_squeeze_now = squeeze[-1]
        in_squeeze_prev = squeeze[-2]

        # Momentum (simplified: close vs 5-day ago)
        if n >= 6:
            momentum = close[-1] - close[-6]
        else:
            momentum = 0.0

        # Scoring
        if not in_squeeze_now and in_squeeze_prev:
            # Squeeze just released
            if momentum > 0:
                return 2.0  # Bullish release
            else:
                return -2.0  # Bearish release

        elif in_squeeze_now:
            # In squeeze - check price action
            if momentum > 0:
                return 1.5  # Coiling with bullish momentum
            elif abs(momentum) < close[-1] * 0.01:
                return 0.5  # Coiling flat
            else:
                return -1.0  # Coiling with bearish momentum

        else:
            # Not in squeeze - normal volatility
            return 0.0

    def calculate_aroon_numpy(self, high_array: np.ndarray, low_array: np.ndarray, window: int = 25):
        """
        Calculate Aroon Up/Down using numpy vectorization.
        Returns tuple of (aroon_up, aroon_down) arrays.
        """
        n = len(high_array)
        if n < window:
            return np.zeros(n), np.zeros(n)

        # sliding_window_view creates a view without copying (efficient)
        high_windows = sliding_window_view(high_array, window_shape=window)
        low_windows = sliding_window_view(low_array, window_shape=window)

        # argmax/argmin along axis 1 (the window axis)
        # Numpy argmax finds the FIRST occurrence.
        up_periods = np.argmax(high_windows, axis=1)
        down_periods = np.argmin(low_windows, axis=1)

        # Calculate Aroon values
        # Formula: ((index + 1) / window) * 100
        aroon_up = (up_periods + 1) / window * 100
        aroon_down = (down_periods + 1) / window * 100

        # Pad with 0s to match original length (consistent with ta fillna=0 logic)
        pad = np.zeros(window - 1)
        final_up = np.concatenate((pad, aroon_up))
        final_down = np.concatenate((pad, aroon_down))

        return final_up, final_down

    def calculate_aroon(self, window: int = 25) -> float:
        """
        Calculate Aroon Indicator score (OPTIMIZED).

        Aroon measures time since highest high / lowest low over a period.
        Early detector of trend changes based on time, not price.

        Formula:
            Aroon Up = ((Period - Days Since High) / Period) * 100
            Aroon Down = ((Period - Days Since Low) / Period) * 100

        Scoring:
        • +2.0 if Aroon Up > 70 and Aroon Down < 30 (strong uptrend)
        • +1.5 if Aroon Up crossed above Aroon Down recently (new uptrend)
        • +1.0 if Aroon Up > 50 and rising
        • -2.0 if Aroon Down > 70 and Aroon Up < 30 (strong downtrend)
        • -1.0 if Aroon Down > Aroon Up
        • 0.0 otherwise

        Args:
            window: Lookback period (default: 25 days)

        Returns:
            float: Score from -2.0 to +2.0 based on Aroon state
        """
        if len(self.days) < window + 5:
            return 0.0

        high = self.days['high'].values
        low = self.days['low'].values
        
        aroon_up, aroon_down = self.calculate_aroon_numpy(high, low, window)

        # Current values
        up_now = aroon_up[-1]
        down_now = aroon_down[-1]

        # Previous values (for crossover detection)
        up_prev = aroon_up[-2]
        down_prev = aroon_down[-2]

        # Check for recent crossover (last 3 days)
        # Using indices -1, -2, -3 directly from numpy array
        if len(aroon_up) >= 3:
            up_3 = aroon_up[-3]
            down_3 = aroon_down[-3]
            recent_bullish_cross = (up_now > down_now and up_3 <= down_3)
        else:
            recent_bullish_cross = False

        # Scoring
        if up_now > 70 and down_now < 30:
            return 2.0  # Strong uptrend
        elif recent_bullish_cross:
            return 1.5  # New uptrend forming
        elif up_now > 50 and (up_now > up_prev):
            return 1.0  # Uptrend strengthening
        elif down_now > 70 and up_now < 30:
            return -2.0  # Strong downtrend
        elif down_now > up_now:
            return -1.0  # Downtrend
        else:
            return 0.0  # Neutral

    def calculate_keltner(self, window: int = 20, atr_mult: float = 2.0) -> float:
        """
        Calculate Keltner Channel score (OPTIMIZED).

        Keltner Channels use ATR instead of standard deviation (vs Bollinger Bands).
        More stable and reliable for breakout detection.

        Formula:
            Middle Line = EMA(Close, window)
            Upper Band = Middle + (ATR * multiplier)
            Lower Band = Middle - (ATR * multiplier)

        Scoring:
        • +2.0 if price breaking above upper band
        • +1.0 if price > upper band
        • +0.5 if price > middle line
        • -2.0 if price breaking below lower band
        • -1.0 if price < lower band
        • -0.5 if price < middle line
        • 0.0 if price at middle line

        Args:
            window: EMA and ATR period (default: 20)
            atr_mult: ATR multiplier for bands (default: 2.0)

        Returns:
            float: Score from -2.0 to +2.0 based on price position vs Keltner
        """
        if len(self.days) < window + 5:
            return 0.0

        close = self.days['close'].values
        high = self.days['high'].values
        low = self.days['low'].values

        # EMA Middle Line
        # Matches 'ta' KeltnerChannel which uses EMA
        close_series = self.days['close']
        kc_mean = close_series.ewm(span=window, adjust=False).mean().values

        # ATR Calculation (NumPy for TR, Pandas for EMA)
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]
        
        tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
        tr_series = pd.Series(tr)
        # ATR uses Wilder's Smoothing (alpha=1/n)
        atr = tr_series.ewm(alpha=1.0/window, adjust=False).mean().values

        upper = kc_mean + (atr_mult * atr)
        lower = kc_mean - (atr_mult * atr)
        middle = kc_mean

        # Current and previous price positions
        price_now = close[-1]
        price_prev = close[-2]

        upper_now = upper[-1]
        lower_now = lower[-1]
        middle_now = middle[-1]

        upper_prev = upper[-2]
        lower_prev = lower[-2]

        # Check for breakouts (crossing bands)
        breaking_above = (price_now > upper_now and price_prev <= upper_prev)
        breaking_below = (price_now < lower_now and price_prev >= lower_prev)

        # Scoring
        if breaking_above:
            return 2.0  # Breakout above
        elif price_now > upper_now:
            return 1.0  # Above upper band
        elif price_now > middle_now:
            return 0.5  # Above middle
        elif breaking_below:
            return -2.0  # Breakdown below
        elif price_now < lower_now:
            return -1.0  # Below lower band
        elif price_now < middle_now:
            return -0.5  # Below middle
        else:
            return 0.0  # At middle line

    def get_score(self, enabled_sub_indicators: Optional[list[str]] = None, aggregation: str = "sum") -> IndicatorScore:
        """
        Calculate the trend score based on the following indicators:
        - Stochastic Oscillator (stochastic)
        - Ichimoku Cloud (ichimoku)
        - Parabolic SAR (psar)
        - Heiken Ashi (heiken_ashi)
        - ADX/DMI (adx)
        - Donchian Channels (donchian)
        - SuperTrend (supertrend)

        Returns a float score.
        """
        buy_score = 1.0 if aggregation == "product" else 0.0
        active_count = 0

        # Sub-indicator mapping
        def calc_stochastic():
            k_prev = self.days['stoch_k'].shift(1)
            d_prev = self.days['stoch_d'].shift(1)
            crossover_up = ((self.days['stoch_k'] > self.days['stoch_d']) & (k_prev <= d_prev)).iloc[-1]
            crossover_down = ((self.days['stoch_k'] < self.days['stoch_d']) & (k_prev >= d_prev)).iloc[-1]
            oversold = (self.days['stoch_k'] < 20).iloc[-1]
            overbought = (self.days['stoch_k'] > 80).iloc[-1]
            return np.select([crossover_up, crossover_down, oversold, overbought], [2, -2, 1, -1], default=0).sum()

        sub_map = {
            'stochastic': (calc_stochastic, 'STOCHASTIC_MULTIPLIER'),
            'ichimoku': (self.calculate_ichimoku_score, 'ICHIMOKU_MULTIPLIER'),
            'psar': (self.calculate_psar_score, 'PSAR_MULTIPLIER'),
            'heiken_ashi': (self.calculate_heiken_ashi, 'HEIKEN_ASHI_MULTIPLIER'),
            'adx': (self.calculate_dmi_adx, 'ADX_MULTIPLIER'),
            'donchian': (self.calculate_donchian, 'DONCHIAN_MULTIPLIER'),
            'supertrend': (self.calculate_supertrend, 'SUPERTREND_MULTIPLIER'),
            'ttm_squeeze': (self.calculate_ttm_squeeze, 'TTM_SQUEEZE_MULTIPLIER'),
            'aroon': (self.calculate_aroon, 'AROON_MULTIPLIER'),
            'keltner': (self.calculate_keltner, 'KELTNER_MULTIPLIER')
        }

        for name, (func, weight_key) in sub_map.items():
            if enabled_sub_indicators is None or name in enabled_sub_indicators:
                multiplier = self.weights[weight_key]
                if multiplier == 0.0:
                    continue  # Skip calculation if multiplier is zero
                score = func() * multiplier
                if aggregation == "product":
                    buy_score *= score
                else:
                    buy_score += score
                active_count += 1

        if active_count == 0 or (aggregation == "product" and buy_score == 0):
            buy_score = 0.0

        sell_score = 0.0
        return IndicatorScore(buy=buy_score, sell=sell_score)

    def graph(self) -> None:
        pass
