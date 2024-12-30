import numpy as np
import pandas as pd
from ta.trend import PSARIndicator #pylint: disable=import-error

STOCHASTIC_MULTIPLIER = 1.0
ICHIMOKU_MULTIPLIER = 1.0
PSAR_MULTIPLIER = 1.0
HEIKEN_ASHI_MULTIPLIER = 1.0
REQUIRED_COLUMNS = {'high', 'low', 'close', 'open', 'stoch_k', 'stoch_d'}

class TrendIndicator:
    def __init__(self):
        self.validated = False

    def _validate_columns(self, df):
        if not self.validated:
            missing = REQUIRED_COLUMNS - set(df.columns)
            if missing:
                raise ValueError(f"Missing required columns: {missing}")
            self.validated = True

    @staticmethod
    def _calculate_psar_score(df: pd.DataFrame, step: float = 0.02, max_step: float = 0.2) -> float:
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
        if len(df) < 2:
            return 0.0

        # 1) Compute Parabolic SAR using the 'ta' library
        psar_indicator = PSARIndicator(
            high=df['high'],
            low=df['low'],
            close=df['close'],
            step=step,
            max_step=max_step
        )

        # The library provides the psar values for each row
        df['psar'] = psar_indicator.psar()

        # 2) Identify if there's a flip from yesterday to today
        #    We'll see if SAR was above price vs. below price, day-to-day.

        # Today's values
        psar_today = df.iloc[-1]['psar']
        close_today = df.iloc[-1]['close']
        psar_above_today = psar_today > close_today

        # Yesterday's values
        psar_yesterday = df.iloc[-2]['psar']
        close_yesterday = df.iloc[-2]['close']
        psar_above_yesterday = psar_yesterday > close_yesterday

        # 3) Determine the flip and assign a score
        score = 0.0

        # If Parabolic SAR was above price yesterday but is now below => bullish flip
        if psar_above_yesterday and not psar_above_today:
            # e.g. +2 points for a bullish flip
            score += 2.0

        # If Parabolic SAR was below price yesterday but is now above => bearish flip
        elif not psar_above_yesterday and psar_above_today:
            # e.g. -2 points for a bearish flip
            score -= 2.0

        return score

    @staticmethod
    def _calculate_ichimoku(df):
        """
        Calculate Ichimoku indicator lines and add them to df.
        Expects columns: 'high', 'low', 'close'.
        Returns df with new columns:
        'tenkan', 'kijun', 'spanA', 'spanB', 'chikou'
        """
        # Tenkan-sen (Conversion Line) - 9 period
        high_9 = df['high'].rolling(window=9).max()
        low_9 = df['low'].rolling(window=9).min()
        df['tenkan'] = (high_9 + low_9) / 2

        # Kijun-sen (Base Line) - 26 period
        high_26 = df['high'].rolling(window=26).max()
        low_26 = df['low'].rolling(window=26).min()
        df['kijun'] = (high_26 + low_26) / 2

        # Senkou Span A (Leading Span A) = (tenkan + kijun) / 2, shifted forward 26
        df['spanA'] = ((df['tenkan'] + df['kijun']) / 2).shift(26)

        # Senkou Span B (Leading Span B) - 52 period, also shifted forward 26
        high_52 = df['high'].rolling(window=52).max()
        low_52 = df['low'].rolling(window=52).min()
        df['spanB'] = ((high_52 + low_52) / 2).shift(26)

        # Chikou Span (Lagging Span) - Close shifted back 26 periods
        df['chikou'] = df['close'].shift(-26)

        return df

    def _calculate_ichimoku_score(self, days: pd.DataFrame) -> float:
        """
        Calculate your existing technical score, plus Ichimoku-based signals.
        df is your DataFrame with Ichimoku columns: 'tenkan', 'kijun', 'spanA', 'spanB', 'Close'.
        Returns a float score.
        """
        days = self._calculate_ichimoku(days)

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

    def _calculate_heiken_ashi(self, days) -> float:
        """
        Computes Heiken Ashi candles for the given DataFrame (df),
        which should have columns: ['open', 'High', 'Low', 'Close'].

        Returns a new DataFrame with columns:
        'HA_open', 'HA_High', 'HA_Low', 'HA_Close'
        """

        # Make a copy so we don't mutate the original DataFrame
        required_cols = ['open', 'high', 'low', 'close']
        ha_df = days[required_cols].copy()

        ha_df['HA_close'] = (ha_df['open'] + ha_df['high'] + ha_df['low'] + ha_df['close']) / 4.0
        ha_df['HA_open'] = (ha_df['open'].shift(1) + ha_df['close'].shift(1)) / 2.0
        ha_df['HA_high'] = ha_df[['high', 'HA_open', 'HA_close']].max(axis=1)
        ha_df['HA_low'] = ha_df[['low', 'HA_open', 'HA_close']].min(axis=1)

        last_row = ha_df.iloc[-1]
        ha_open  = last_row['HA_open']
        ha_close = last_row['HA_close']

        score = 0.0

        # For example, count the last n candles if they're all bullish:
        n = 3
        last_n_rows = ha_df.iloc[-n:]
        bullish_count = (last_n_rows['HA_close'].values > last_n_rows['HA_open'].values).sum()

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

    def calculate_score(self, days):
        score = 0

        self._validate_columns(days)

        # Shifted columns to detect crossovers from previous day:
        k_prev = days['stoch_k'].shift(1)
        d_prev = days['stoch_d'].shift(1)

        # Conditions:
        crossover_up = ((days['stoch_k'] > days['stoch_d']) & (k_prev <= d_prev)).iloc[-1]  # cross up
        crossover_down = ((days['stoch_k'] < days['stoch_d']) & (k_prev >= d_prev)).iloc[-1]  # cross down
        oversold = (days['stoch_k'] < 20).iloc[-1]
        overbought = (days['stoch_k'] > 80).iloc[-1]

        score += np.select( [ crossover_up, crossover_down, oversold, overbought ] , [ 2, -2, 1, -1 ], default=0) * STOCHASTIC_MULTIPLIER

        score += self._calculate_ichimoku_score(days) * ICHIMOKU_MULTIPLIER

        score += self._calculate_psar_score(days) * PSAR_MULTIPLIER

        score += self._calculate_heiken_ashi(days) * HEIKEN_ASHI_MULTIPLIER

        return score
