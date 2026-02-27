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
from numpy.lib.stride_tricks import sliding_window_view
import pandas as pd
from ta.volatility import DonchianChannel # pylint: disable=import-error

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

    def __init__(self, data: pd.DataFrame, weight_category: str = None):
        self.weights = weights_config.get_weights(weight_category or 'trend')
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
        Calculates a Parabolic SAR flip-based score using pure numpy.

        :param step:     The AF (acceleration factor) initial step, commonly 0.02.
        :param max_step: The maximum step for AF, commonly 0.2.
        :return:         A float representing the SAR-based score for the latest row.
        """
        if len(self.days) < 2:
            return 0.0

        high = self.days['high'].values
        low = self.days['low'].values
        close = self.days['close'].values
        n = len(high)

        # Initialize PSAR arrays
        psar = np.empty(n)
        bull = True
        af = step
        ep = high[0]
        psar[0] = low[0]

        for i in range(1, n):
            if bull:
                psar[i] = psar[i - 1] + af * (ep - psar[i - 1])
                psar[i] = min(psar[i], low[i - 1])
                if i >= 2:
                    psar[i] = min(psar[i], low[i - 2])
                if low[i] < psar[i]:
                    bull = False
                    psar[i] = ep
                    ep = low[i]
                    af = step
                else:
                    if high[i] > ep:
                        ep = high[i]
                        af = min(af + step, max_step)
            else:
                psar[i] = psar[i - 1] + af * (ep - psar[i - 1])
                psar[i] = max(psar[i], high[i - 1])
                if i >= 2:
                    psar[i] = max(psar[i], high[i - 2])
                if high[i] > psar[i]:
                    bull = True
                    psar[i] = ep
                    ep = high[i]
                    af = step
                else:
                    if low[i] < ep:
                        ep = low[i]
                        af = min(af + step, max_step)

        # Flip detection on last two bars
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
        Calculate SuperTrend score using numpy arrays for speed.

        Returns:
        • 2 if Bullish Crossover (Trend flipped to Green today)
        • 1 if Bullish (Green)
        • -2 if Bearish Crossover (Trend flipped to Red today)
        • -1 if Bearish (Red)
        """
        n = len(self.days)
        if n < period + 1:
            return 0.0

        high = self.days['high'].values
        low = self.days['low'].values
        close = self.days['close'].values

        # Calculate ATR using numpy
        tr = np.empty(n)
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        # Wilder's smoothed ATR
        atr = np.empty(n)
        atr[:period] = 0.0
        atr[period - 1] = np.mean(tr[:period])
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        hl2 = (high + low) * 0.5
        basic_upper = hl2 + multiplier * atr
        basic_lower = hl2 - multiplier * atr

        final_upper = np.zeros(n)
        final_lower = np.zeros(n)
        trend = np.zeros(n, dtype=np.int8)

        for i in range(1, n):
            # Final Upper
            if basic_upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]:
                final_upper[i] = basic_upper[i]
            else:
                final_upper[i] = final_upper[i - 1]

            # Final Lower
            if basic_lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]:
                final_lower[i] = basic_lower[i]
            else:
                final_lower[i] = final_lower[i - 1]

            # Trend
            curr_trend = trend[i - 1]
            if curr_trend == 0:
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
        if curr == -1 and prev == 1:
            return -2.0
        if curr == 1:
            return 1.0
        if curr == -1:
            return -1.0

        return 0.0

    def calculate_ttm_squeeze(self, bb_length: int = 20, bb_std: float = 2.0,
                              kc_length: int = 20, kc_atr_mult: float = 1.5) -> float:
        """
        Calculate TTM Squeeze score using numpy/pandas (no ta library).

        Scoring:
        • +2.0 if squeeze just released with bullish momentum
        • +1.5 if in squeeze with price rising (coiling for breakout)
        • +0.5 if in squeeze with price flat
        • -1.0 if in squeeze with price falling
        • -2.0 if squeeze released with bearish momentum
        • 0.0 if no squeeze (normal volatility)
        """
        n = len(self.days)
        if n < max(bb_length, kc_length) + 5:
            return 0.0

        close = self.days['close'].values
        high = self.days['high'].values
        low = self.days['low'].values

        # Bollinger Bands via sliding_window_view
        close_windows = sliding_window_view(close, bb_length)
        bb_mid = np.mean(close_windows, axis=1)
        bb_std_arr = np.std(close_windows, axis=1, ddof=1)
        offset = bb_length - 1
        bb_upper = bb_mid + bb_std * bb_std_arr
        bb_lower = bb_mid - bb_std * bb_std_arr
        bb_width = bb_upper - bb_lower

        # Keltner Channel: EMA + ATR
        kc_ema = self.days['close'].ewm(span=kc_length, adjust=False).mean().values

        # True Range
        tr = np.empty(n)
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))

        # EMA of True Range (ATR)
        kc_atr = pd.Series(tr).ewm(span=kc_length, adjust=False).mean().values

        # KC bands (aligned to bb_width offset)
        kc_upper = kc_ema[offset:] + kc_atr_mult * kc_atr[offset:]
        kc_lower = kc_ema[offset:] - kc_atr_mult * kc_atr[offset:]
        kc_width = kc_upper - kc_lower

        # Squeeze condition: BB inside KC
        squeeze = bb_width < kc_width

        in_squeeze_now = squeeze[-1]
        in_squeeze_prev = squeeze[-2] if len(squeeze) > 1 else False

        # Momentum
        momentum = close[-1] - close[-5] if n >= 5 else 0

        if not in_squeeze_now and in_squeeze_prev:
            return 2.0 if momentum > 0 else -2.0

        if in_squeeze_now:
            if momentum > 0:
                return 1.5
            if abs(momentum) < close[-1] * 0.01:
                return 0.5
            return -1.0

        return 0.0

    def calculate_aroon_numpy(self, window: int = 25):
        """Calculate Aroon Up/Down using numpy sliding_window_view (vectorized)."""
        high = self.days['high'].values
        low = self.days['low'].values
        n = len(high)
        win = window + 1  # window+1 elements to look back 'window' periods

        aroon_up = np.full(n, np.nan)
        aroon_down = np.full(n, np.nan)

        if n < win:
            return aroon_up, aroon_down

        high_windows = sliding_window_view(high, win)
        low_windows = sliding_window_view(low, win)

        # argmax/argmin give position of highest/lowest in each window
        days_since_high = window - np.argmax(high_windows, axis=1)
        days_since_low = window - np.argmin(low_windows, axis=1)

        offset = win - 1  # results start at index (win-1)
        aroon_up[offset:] = ((window - days_since_high) / window) * 100
        aroon_down[offset:] = ((window - days_since_low) / window) * 100

        return aroon_up, aroon_down

    def calculate_aroon(self, window: int = 25) -> float:
        """
        Calculate Aroon Indicator score using vectorized numpy.

        Scoring:
        • +2.0 if Aroon Up > 70 and Aroon Down < 30 (strong uptrend)
        • +1.5 if Aroon Up crossed above Aroon Down recently (new uptrend)
        • +1.0 if Aroon Up > 50 and rising
        • -2.0 if Aroon Down > 70 and Aroon Up < 30 (strong downtrend)
        • -1.0 if Aroon Down > Aroon Up
        • 0.0 otherwise
        """
        if len(self.days) < window + 5:
            return 0.0

        aroon_up, aroon_down = self.calculate_aroon_numpy(window)

        up_now = aroon_up[-1]
        down_now = aroon_down[-1]
        up_prev = aroon_up[-2] if len(aroon_up) > 1 else 0
        down_prev = aroon_down[-2] if len(aroon_down) > 1 else 0

        # Check for recent crossover (last 3 days)
        if len(aroon_up) >= 3 and not np.isnan(aroon_up[-3]):
            up_3 = aroon_up[-3]
            down_3 = aroon_down[-3]
            recent_bullish_cross = (up_now > down_now and up_3 <= down_3)
        else:
            recent_bullish_cross = False

        if np.isnan(up_now) or np.isnan(down_now):
            return 0.0

        if up_now > 70 and down_now < 30:
            return 2.0
        if recent_bullish_cross:
            return 1.5
        if up_now > 50 and (up_now > up_prev):
            return 1.0
        if down_now > 70 and up_now < 30:
            return -2.0
        if down_now > up_now:
            return -1.0
        return 0.0

    def calculate_keltner(self, window: int = 20, atr_mult: float = 2.0) -> float:
        """
        Calculate Keltner Channel score using numpy/pandas (no ta library).

        Scoring:
        • +2.0 if price breaking above upper band
        • +1.0 if price > upper band
        • +0.5 if price > middle line
        • -2.0 if price breaking below lower band
        • -1.0 if price < lower band
        • -0.5 if price < middle line
        • 0.0 if price at middle line
        """
        n = len(self.days)
        if n < window + 5:
            return 0.0

        close = self.days['close'].values
        high = self.days['high'].values
        low = self.days['low'].values

        # EMA of close
        middle = self.days['close'].ewm(span=window, adjust=False).mean().values

        # True Range → EMA for ATR
        tr = np.empty(n)
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        atr = pd.Series(tr).ewm(span=window, adjust=False).mean().values

        upper = middle + atr_mult * atr
        lower = middle - atr_mult * atr

        price_now = close[-1]
        price_prev = close[-2] if n > 1 else price_now

        upper_now = upper[-1]
        lower_now = lower[-1]
        middle_now = middle[-1]
        upper_prev = upper[-2] if n > 1 else upper_now
        lower_prev = lower[-2] if n > 1 else lower_now

        breaking_above = (price_now > upper_now and price_prev <= upper_prev)
        breaking_below = (price_now < lower_now and price_prev >= lower_prev)

        if breaking_above:
            return 2.0
        if price_now > upper_now:
            return 1.0
        if price_now > middle_now:
            return 0.5
        if breaking_below:
            return -2.0
        if price_now < lower_now:
            return -1.0
        if price_now < middle_now:
            return -0.5
        return 0.0

    def calculate_stochastic(self) -> float:
        """Calculate Stochastic Oscillator score based on crossovers and levels."""
        k_prev = self.days['stoch_k'].shift(1)
        d_prev = self.days['stoch_d'].shift(1)
        crossover_up = ((self.days['stoch_k'] > self.days['stoch_d']) & (k_prev <= d_prev)).iloc[-1]
        crossover_down = ((self.days['stoch_k'] < self.days['stoch_d']) & (k_prev >= d_prev)).iloc[-1]
        oversold = (self.days['stoch_k'] < 20).iloc[-1]
        overbought = (self.days['stoch_k'] > 80).iloc[-1]
        return float(np.select([crossover_up, crossover_down, oversold, overbought], [2, -2, 1, -1], default=0).sum())

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

        sub_map = {
            'stochastic': (self.calculate_stochastic, 'STOCHASTIC_MULTIPLIER'),
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
