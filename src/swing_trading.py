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
from typing import Dict, Optional
from functools import lru_cache
import numpy as np
import pandas as pd
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
    def calculate_technical_score(yesterday: Dict) -> float:
        """Calculate technical score with vectorized operations."""
        if 'avg_volume_20' in yesterday and yesterday['avg_volume_20'] < MIN_VOLUME_THRESHOLD:
            return 0

        score = 0

        # Vectorized calculations
        score += np.select(
            [yesterday['adx'] > 35, yesterday['adx'] > 30, yesterday['adx'] > 25],
            [3, 2, 1], 0
        )

        ema_margin = (yesterday['close'] - yesterday['ema_20']) / yesterday['ema_20'] * 100
        score += np.select(
            [ema_margin > 3, ema_margin > 2, ema_margin > 1],
            [3, 2, 1], 0
        )

        macd_diff = yesterday['macd_line'] - yesterday['macd_signal']
        score += np.where(
            (macd_diff > 0) & (yesterday['macd_line'] > 0),
            np.where(macd_diff > yesterday['macd_signal'] * 0.15, 2, 1),
            0
        )

        if 'volume' in yesterday and 'avg_volume_20' in yesterday:
            vol_ratio = yesterday['volume'] / yesterday['avg_volume_20']
            score += np.select(
                [vol_ratio > 2, vol_ratio > 1.5],
                [2, 1], 0
            )

        score += np.select(
            [(yesterday['rsi_14'] > 45) & (yesterday['rsi_14'] < 65),
             (yesterday['rsi_14'] > 40) & (yesterday['rsi_14'] < 70)],
            [2, 1], 0
        )

        if 'roc_5' in yesterday:
            score += np.select(
                [yesterday['roc_5'] > 2, yesterday['roc_5'] > 1],
                [2, 1], 0
            )

        if 'dmi_p' in yesterday and 'dmi_n' in yesterday:
            score += np.where(yesterday['dmi_p'] > yesterday['dmi_n'], 1, 0)

        bb_position = (yesterday['close'] - yesterday['bb_lower']) / (yesterday['bb_upper'] - yesterday['bb_lower'])
        score += np.select(
            [(bb_position > 0.3) & (bb_position < 0.7),
             (bb_position > 0.1) & (bb_position < 0.3),
             bb_position > 0.85],
            [2, 3, -1], 0
        )

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
            ReportSingleton().write(f"Failed to load historical data for {symbol}.")
            return None

        df = pd.DataFrame(price_data['days'])
        yesterday = dict(df.iloc[-1])

        if yesterday['date'] != (pd.Timestamp.now().normalize() - pd.Timedelta(days=1)).strftime('%Y-%m-%d'):
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
            'score': self.technical_analyzer.calculate_technical_score(yesterday)
        }

    def swing_predict(self) -> None:
        """Main prediction function with parallel processing capability."""
        symbols = get_symbol_name_list()
        results = []

        # Process symbols
        for symbol in symbols:
            result = self.process_symbol(symbol)
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
