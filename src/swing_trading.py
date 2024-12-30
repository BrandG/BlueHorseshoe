"""
swing_trading.py

This module provides classes and methods for performing technical analysis and swing trading predictions.
It includes functionality for calculating trends, technical scores, and entry prices for stocks based on historical data.

Classes:
    TechnicalAnalyzer: Handles technical analysis calculations with optimized methods.
    SwingTrader: Main class for swing trading analysis.

Constants:
    TREND_PERIOD: The period used for trend calculation.
    STRONG_R2_THRESHOLD: The R-squared threshold for a strong trend.
    WEAK_R2_THRESHOLD: The R-squared threshold for a weak trend.
    MIN_VOLUME_THRESHOLD: The minimum volume threshold for considering a stock.
    MIN_STOCK_PRICE: The minimum stock price for considering a stock.
    MAX_STOCK_PRICE: The maximum stock price for considering a stock.
    STOP_LOSS_FACTOR: The factor used to calculate the stop-loss price.
    TAKE_PROFIT_FACTOR: The factor used to calculate the take-profit price.
"""
import logging
from typing import Dict, Optional
from functools import lru_cache
import numpy as np
import pandas as pd
from ta.trend import PSARIndicator #pylint: disable=import-error
from globals import ReportSingleton, get_symbol_name_list
from historical_data import load_historical_data

# Constants to avoid magic numbers
TREND_PERIOD = 20
STRONG_R2_THRESHOLD = 0.7
WEAK_R2_THRESHOLD = 0.3
MIN_VOLUME_THRESHOLD = 10000
MIN_STOCK_PRICE = 1.0
MAX_STOCK_PRICE = 50.0
STOP_LOSS_FACTOR = 0.96
TAKE_PROFIT_FACTOR = 1.04
MACD_SIGNAL_MULTIPLIER = 0.15

ADX_MULTIPLIER = 1.0
EMA_MARGIN_MULTIPLIER = 1.0
MACD_MULTIPLIER = 1.0
VOLUME_MULTIPLIER = 1.0
RSI_MULTIPLIER = 1.0
ROC_MULTIPLIER = 1.0
BB_MULTIPLIER = 1.0
STOCHASTIC_MULTIPLIER = 1.0
ICHIMOKU_MULTIPLIER = 1.0
PSAR_MULTIPLIER = 1.0

class TechnicalAnalyzer:
    """Handles technical analysis calculations with optimized methods."""

    @staticmethod
    @lru_cache(maxsize=128)
    def _calculate_r2(prices: tuple) -> float:
        """Calculate R-squared value with caching for repeated calculations."""
        prices_array = np.array(prices)
        x = np.arange(len(prices_array))
        slope, intercept = np.polyfit(x, prices_array, 1)
        y_pred = slope * x + intercept
        ss_res = np.sum((prices_array - y_pred) ** 2)
        ss_tot = np.sum((prices_array - np.mean(prices_array)) ** 2)
        return (1 - (ss_res / ss_tot)) if ss_tot != 0 else 0

    @staticmethod
    def _rolling_window(a: np.ndarray, window: int) -> np.ndarray:
        """Create a rolling window view of the array."""
        shape = a.shape[:-1] + (a.shape[-1] - window + 1, window)
        strides = a.strides + (a.strides[-1],)
        return np.lib.stride_tricks.as_strided(a, shape=shape, strides=strides, writeable=False)

    @classmethod
    def calculate_trend(cls, df: pd.DataFrame) -> str:
        """Calculate trend with vectorized operations."""
        if len(df) < TREND_PERIOD:
            return "Insufficient data"

        # Vectorized calculations for better performance
        prices = np.array(df['close'].values)
        # Use rolling window implementation
        windows = cls._rolling_window(prices, TREND_PERIOD)

        # Calculate slope and R2 for the last window
        x = np.arange(TREND_PERIOD)
        last_window = windows[-1]
        slope, _ = np.polyfit(x, last_window, 1)
        r2_value = cls._calculate_r2(tuple(last_window))

        # Determine trend based on slope and R2
        if slope > 0 :
            trend = "Strong Uptrend" if r2_value > STRONG_R2_THRESHOLD else "Weak Uptrend"
        elif slope < 0 :
            trend = "Strong Downtrend" if r2_value > STRONG_R2_THRESHOLD else "Weak Downtrend"
        else:
            trend = "No Clear Trend"

        return trend

    @staticmethod
    def calculate_psar_score(df: pd.DataFrame, step: float = 0.02, max_step: float = 0.2) -> float:
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
    def calculate_ichimoku(df):
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

    @staticmethod
    def _calculate_ichimoku_score(days: pd.DataFrame) -> float:
        """
        Calculate your existing technical score, plus Ichimoku-based signals.
        df is your DataFrame with Ichimoku columns: 'tenkan', 'kijun', 'spanA', 'spanB', 'Close'.
        Returns a float score.
        """
        days = TechnicalAnalyzer().calculate_ichimoku(days)

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

    @staticmethod
    def calculate_technical_score(days: pd.DataFrame) -> float:
        """
        Calculate a technical score by analyzing multiple indicators from the given DataFrame:
        1. Volume threshold check
        2. DMI/ADX scoring (if dmi_p > dmi_n)
        3. EMA margin scoring
        4. MACD scoring
        5. Volume ratio scoring
        6. RSI scoring
        7. ROC scoring (adaptive via rolling std)
        8. Bollinger Band position scoring
        
        Returns a float representing the sum of all indicator contributions.
        """
        yesterday = dict(days.iloc[-1])

        # 1) Early exit if average volume is too low
        if 'avg_volume_20' in yesterday and yesterday['avg_volume_20'] < MIN_VOLUME_THRESHOLD:
            return 0.0

        score = 0

        # 2) DMI/ADX
        if 'dmi_p' in yesterday and 'dmi_n' in yesterday and 'adx' in yesterday:
            if yesterday['dmi_p'] > yesterday['dmi_n']:
                # Score ADX levels: above 35 => +3, above 30 => +2, above 25 => +1
                score += np.select(
                    [yesterday['adx'] > 35, yesterday['adx'] > 30, yesterday['adx'] > 25],
                    [3, 2, 1],
                    0
                ) * ADX_MULTIPLIER

        # 3) EMA margin
        if 'close' in yesterday and 'ema_20' in yesterday and yesterday['ema_20'] != 0:
            ema_margin = (yesterday['close'] - yesterday['ema_20']) / yesterday['ema_20'] * 100
            score += np.select(
                [ema_margin > 20, ema_margin > 10, ema_margin > 5],
                [3, 2, 1],
                0
            ) * EMA_MARGIN_MULTIPLIER

        # 4) MACD
        if 'macd_line' in yesterday and 'macd_signal' in yesterday:
            macd_diff = yesterday['macd_line'] - yesterday['macd_signal']
            # If MACD diff and line are positive, score 1 or 2 depending on how large the diff is
            if (macd_diff > 0) and (yesterday['macd_line'] > 0):
                score += np.select(
                    [macd_diff > yesterday['macd_signal'] * MACD_SIGNAL_MULTIPLIER, macd_diff > yesterday['macd_signal']],
                    [2, 1],
                    0
                ) * MACD_MULTIPLIER

        # 5) Volume ratio
        if 'volume' in yesterday and 'avg_volume_20' in yesterday and yesterday['avg_volume_20'] != 0:
            vol_ratio = yesterday['volume'] / yesterday['avg_volume_20']
            score += np.select(
                [vol_ratio > 2, vol_ratio > 1.5, vol_ratio < 0.5],
                [2, 1, -1],
                default=0
            ) * VOLUME_MULTIPLIER

        # 6) RSI scoring
        if 'rsi_14' in yesterday:
            score += np.select(
                [
                    (yesterday['rsi_14'] >= 45) & (yesterday['rsi_14'] <= 65),
                    (yesterday['rsi_14'] >= 40) & (yesterday['rsi_14'] <= 70)
                ],
                [2, 1],
                0
            ) * RSI_MULTIPLIER

        # 7) ROC scoring (adaptive)
        if 'roc_5' in yesterday:
            # Rolling std over entire dataset
            roc_5_std = days['roc_5'].rolling(window=20).std().iloc[-1]  # last entry

            if pd.notna(roc_5_std):
                score += np.select(
                    [(yesterday['roc_5'] > 2 * roc_5_std), (yesterday['roc_5'] > 1 * roc_5_std)],
                    [2, 1],
                    default=0
                ) * ROC_MULTIPLIER

        # 8) Bollinger Band position
        bb_position = 0.0
        if ('bb_lower' in yesterday and 'bb_upper' in yesterday and
                (yesterday['bb_upper'] > yesterday['bb_lower'])):
            band_range = yesterday['bb_upper'] - yesterday['bb_lower']
            bb_position = (yesterday['close'] - yesterday['bb_lower']) / band_range

            score += np.select(
                [
                    (bb_position >= 0.3) & (bb_position < 0.7),
                    (bb_position >= 0.1) & (bb_position < 0.3),
                    bb_position >= 0.85
                ],
                [2, 3, -1],
                default=0
            ) * BB_MULTIPLIER

        # 9) Stochastic Oscillator
        if not {'stoch_k', 'stoch_d'}.issubset(days.columns):
            raise ValueError("DataFrame must have 'stoch_k' and 'stoch_d' columns.")

        # Shifted columns to detect crossovers from previous day:
        k_prev = days['stoch_k'].shift(1)
        d_prev = days['stoch_d'].shift(1)

        # Conditions:
        crossover_up = ((days['stoch_k'] > days['stoch_d']) & (k_prev <= d_prev)).iloc[-1]  # cross up
        crossover_down = ((days['stoch_k'] < days['stoch_d']) & (k_prev >= d_prev)).iloc[-1]  # cross down
        oversold = (days['stoch_k'] < 20).iloc[-1]
        overbought = (days['stoch_k'] > 80).iloc[-1]

        score += np.select( [ crossover_up, crossover_down, oversold, overbought ] , [ 2, -2, 1, -1 ], default=0) * STOCHASTIC_MULTIPLIER

        # 10) Ichimoku Cloud
        score += TechnicalAnalyzer._calculate_ichimoku_score(days) * ICHIMOKU_MULTIPLIER

        # 11) Parabolic SAR
        score += TechnicalAnalyzer().calculate_psar_score(days) * PSAR_MULTIPLIER

        return float(score)

class SwingTrader:
    """Main class for swing trading analysis."""

    def __init__(self):
        self.technical_analyzer = TechnicalAnalyzer()

    def calculate_entry_price(self, df: pd.DataFrame) -> float:
        """Calculate entry price based on trend."""
        entry_price = df.iloc[-1]['close']
        trend = self.technical_analyzer.calculate_trend(df)

        trend_adjustments = {
            "Strong Uptrend": 1.05,
            "Weak Uptrend": 1.01,
            "Strong Downtrend": 0.95,
            "Weak Downtrend": 0.99
        }

        return entry_price * trend_adjustments.get(trend, 1.0)

    def process_symbol(self, symbol: str) -> Optional[Dict]:
        """Process a single symbol and return its trading data."""
        price_data = load_historical_data(symbol)
        if price_data is None or not price_data['days']:
            logging.error("Failed to load historical data for %s.", symbol)
            return None

        df = pd.DataFrame(price_data['days'])
        yesterday = dict(df.iloc[-1])

        last_trading_day = pd.Timestamp.now().normalize() - pd.offsets.BDay(1)
        last_day_string = last_trading_day.strftime('%Y-%m-%d')
        if yesterday['date'] != last_day_string:
            logging.error("Data for %s on date %s is not %s.", symbol, yesterday['date'], last_day_string)
            with open('src/error_symbols.txt', 'a', encoding='utf-8') as f:
                f.write(f"{symbol}\n")
            return None

        entry_price = self.calculate_entry_price(df)
        if not MIN_STOCK_PRICE < entry_price < MAX_STOCK_PRICE:
            return None

        return {
            'symbol': symbol,
            'name': price_data['full_name'],
            'entry_price': entry_price,
            'stop_loss': entry_price * STOP_LOSS_FACTOR,
            'take_profit': entry_price * TAKE_PROFIT_FACTOR,
            'score': self.technical_analyzer.calculate_technical_score(df)
        }

    def swing_predict(self) -> None:
        """Main prediction function with parallel processing capability."""
        symbols = get_symbol_name_list()
        results = []

        logging.info("Processing %d symbols...", len(symbols))
        # Process symbols
        for symbol in symbols:
            result = self.process_symbol(symbol)
            logging.info("Processed %s with result: %s", symbol, result)
            if result:
                results.append(result)

        # Sort and display results
        sorted_results = sorted(results, key=lambda x: x['score'], reverse=True)
        ReportSingleton().write('Top 10 buy candidates:')
        for result in sorted_results[:10]:
            ReportSingleton().write(
                f"{result['symbol']} - Entry: {result['entry_price']:.2f} - "
                f"Stop-Loss: {result['stop_loss']:.2f} - Take-Profit: {result['take_profit']:.2f} - "
                f"Score: {result['score']:.2f} - Name: {result['name']}"
            )
