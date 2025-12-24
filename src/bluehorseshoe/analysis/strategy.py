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
import os
from typing import Dict, Optional
from functools import lru_cache
import concurrent.futures
import numpy as np
import pandas as pd
from bluehorseshoe.core.globals import GlobalData
from bluehorseshoe.reporting.report_generator import ReportSingleton
from bluehorseshoe.core.symbols import get_symbol_name_list
from bluehorseshoe.data.historical_data import load_historical_data
from bluehorseshoe.analysis.indicators.candlestick_indicators import CandlestickIndicator
from bluehorseshoe.analysis.indicators.limit_indicators import LimitIndicator
from bluehorseshoe.analysis.indicators.momentum_indicators import MomentumIndicator
from bluehorseshoe.analysis.indicators.moving_average_indicators import MovingAverageIndicator
from bluehorseshoe.analysis.indicators.trend_indicators import TrendIndicator
from bluehorseshoe.analysis.indicators.volume_indicators import VolumeIndicator

# Constants to avoid magic numbers
TREND_PERIOD = 20
STRONG_R2_THRESHOLD = 0.7
WEAK_R2_THRESHOLD = 0.3
MIN_VOLUME_THRESHOLD = 100000
MIN_STOCK_PRICE = 1.0
MAX_STOCK_PRICE = 50.0
STOP_LOSS_FACTOR = 0.96
TAKE_PROFIT_FACTOR = 1.04

EMA_MARGIN_MULTIPLIER = 1.0
VOLUME_MULTIPLIER = 1.0

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

        prices = df['close'].values[-TREND_PERIOD:]
        x = np.arange(TREND_PERIOD)
        slope, _ = np.polyfit(x, prices, 1)
        r2_value = cls._calculate_r2(tuple(prices))

        # Use dictionary for trend lookup
        trend_map = {
            (True, True): "Strong Uptrend",
            (True, False): "Weak Uptrend",
            (False, True): "Strong Downtrend",
            (False, False): "Weak Downtrend"
        }

        return trend_map.get((slope > 0, r2_value > STRONG_R2_THRESHOLD), "No Clear Trend")

    @staticmethod
    def calculate_technical_score(days: pd.DataFrame) -> float:
        """
        Calculate a technical score by analyzing multiple indicators from the given DataFrame:
        1. Volume threshold check
        2. DMI/ADX scoring (if dmi_p > dmi_n)
        3. MACD scoring
        4. Volume ratio scoring
        5. RSI scoring
        6. ROC scoring (adaptive via rolling std)
        7. Bollinger Band position scoring
        
        Returns a float representing the sum of all indicator contributions.
        """
        # 1) Early exit if average volume is too low
        if len(days) == 0 or days.iloc[-1].get('avg_volume_20', 0) < MIN_VOLUME_THRESHOLD:
            return 0.0

        total_score : float = 0
        for indicator in [TrendIndicator(days), VolumeIndicator(days), LimitIndicator(days), CandlestickIndicator(days),
                          MovingAverageIndicator(days), MomentumIndicator(days)]:
            total_score += indicator.get_score().buy

        return total_score

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
        if df.empty:
            logging.error("DataFrame is empty for %s.", symbol)
            return None
        yesterday = dict(df.iloc[-1])

        if not GlobalData.holiday:
            last_trading_day = pd.Timestamp.now().normalize() - pd.offsets.BDay(1)
            yesterday['date'] = pd.to_datetime(yesterday['date'])
            if yesterday['date'] != last_trading_day:
                logging.error("Data for %s on date '%s' is not '%s'.", symbol, yesterday['date'], last_trading_day)
                with open('src/error_symbols.txt', 'a', encoding='utf-8') as f:
                    f.write(f"{symbol}\n")
                return None

        entry_price = self.calculate_entry_price(df)
        if not MIN_STOCK_PRICE < entry_price < MAX_STOCK_PRICE:
            return None

        ret_val = {
            'symbol': symbol,
            'name': price_data['full_name'],
            'entry_price': entry_price,
            'stop_loss': entry_price * STOP_LOSS_FACTOR,
            'take_profit': entry_price * TAKE_PROFIT_FACTOR,
            'score': self.technical_analyzer.calculate_technical_score(df)
        }
        logging.info("Processed %s with result: %s", symbol, ret_val)
        return ret_val

    def swing_predict(self) -> None:
        """Main prediction function with parallel processing capability."""
        symbols = get_symbol_name_list()
        # Use ProcessPoolExecutor instead of ThreadPoolExecutor for CPU-bound tasks
        max_workers = min(32, (os.cpu_count() or 0) + 4, len(symbols))  # Optimal worker count
        chunk_size = len(symbols) // max_workers
        results = []

        ReportSingleton().write(f"Yesterday was {'not ' if not GlobalData.holiday else ''}a holiday.")

        logging.info("Processing %d symbols...", len(symbols))
        with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(self.process_symbol, symbols, chunksize=chunk_size))

        # Get frequency list based on results['score']
        score_frequency = {}
        for result in [result for result in results if result is not None]:
            score = result['score']
            if score in score_frequency:
                score_frequency[score] += 1
            else:
                score_frequency[score] = 1

        logging.info("Score frequency: %s", score_frequency)

        # Filter None results and sort in one pass
        sorted_results = sorted(
            (r for r in results if r is not None),
            key=lambda x: x['score'],
            reverse=True
        )
        ReportSingleton().write('Top 10 buy candidates:')
        for result_index in range(10):
            result = sorted_results[result_index]
            price_data = load_historical_data(result['symbol'])
            if price_data is None or not price_data['days']:
                logging.error("Failed to load historical data for %s.", result['symbol'])
                continue

            df = pd.DataFrame(price_data['days'])
            title = f'{result_index}-'+result['symbol']
            CandlestickIndicator(df.copy()).set_title(title).graph()
            LimitIndicator(df.copy()).set_title(title).graph()

            ReportSingleton().write(
                f"{result['symbol']} - Entry: {result['entry_price']:.2f} - "
                f"Stop-Loss: {result['stop_loss']:.2f} - Take-Profit: {result['take_profit']:.2f} - "
                f"Score: {result['score']:.2f} - Name: {result['name']}"
            )
