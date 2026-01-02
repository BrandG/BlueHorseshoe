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
from functools import partial
import concurrent.futures
import pandas as pd
from bluehorseshoe.core.globals import GlobalData
from bluehorseshoe.reporting.report_generator import ReportSingleton
from bluehorseshoe.core.symbols import get_symbol_name_list
from bluehorseshoe.data.historical_data import load_historical_data
from bluehorseshoe.analysis.indicators.candlestick_indicators import CandlestickIndicator
from bluehorseshoe.analysis.indicators.limit_indicators import LimitIndicator
from ta.volatility import AverageTrueRange
from bluehorseshoe.core.scores import score_manager
from bluehorseshoe.analysis.constants import (
    MIN_VOLUME_THRESHOLD, MIN_STOCK_PRICE, MAX_STOCK_PRICE,
    STOP_LOSS_FACTOR, TAKE_PROFIT_FACTOR, ATR_WINDOW, ATR_MULTIPLIER_UPTREND, ATR_MULTIPLIER_DOWNTREND
)
from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer

class SwingTrader:
    """Main class for swing trading analysis."""

    def __init__(self):
        self.technical_analyzer = TechnicalAnalyzer()

    def calculate_entry_price(self, df: pd.DataFrame) -> float:
        """
        Calculate entry price using Average True Range (ATR) for volatility-adjusted 
        entry discounts. This replaces fixed percentage adjustments.
        """
        last_close = df.iloc[-1]['close']
        trend = self.technical_analyzer.calculate_trend(df)
        
        # Ensure ATR is available
        if 'ATR' not in df.columns:
            df['ATR'] = AverageTrueRange(
                high=df['high'], 
                low=df['low'], 
                close=df['close'], 
                window=ATR_WINDOW
            ).average_true_range()
            
        atr = df.iloc[-1]['ATR']
        if pd.isna(atr):
            atr = 0

        # Optimization: In uptrends, we want to buy 'dips' relative to volatility.
        # In downtrends, we want a larger margin of safety.
        if 'Uptrend' in trend:
            # Entry = Close - (0.5 * ATR)
            return last_close - (ATR_MULTIPLIER_UPTREND * atr)
        elif 'Downtrend' in trend:
            # Entry = Close - (1.0 * ATR)
            return last_close - (ATR_MULTIPLIER_DOWNTREND * atr)
            
        return last_close

    def process_symbol(self, symbol: str, target_date: Optional[str] = None, enabled_indicators: Optional[list[str]] = None, aggregation: str = "sum") -> Optional[Dict]:
        """Process a single symbol and return its trading data."""
        price_data = load_historical_data(symbol)
        if price_data is None or not price_data['days']:
            logging.error("Failed to load historical data for %s.", symbol)
            return None

        df = pd.DataFrame(price_data['days'])
        if df.empty:
            logging.error("DataFrame is empty for %s.", symbol)
            return None

        if target_date:
            df['date'] = pd.to_datetime(df['date'])
            target_ts = pd.to_datetime(target_date)
            df = df[df['date'] <= target_ts]
            if df.empty:
                return None
            
            # Staleness check: If the last available data is more than 7 days older than the target_date,
            # it means the symbol was likely delisted or has a massive data gap.
            last_date = pd.to_datetime(df.iloc[-1]['date'])
            if (target_ts - last_date).days > 7:
                logging.info("Symbol %s data is too stale for target date %s (Last date: %s). Skipping.", 
                             symbol, target_date, last_date.strftime('%Y-%m-%d'))
                return None
            
        if len(df) < 30:
            logging.info("Symbol %s has insufficient data (%d days) for target date. Skipping.", symbol, len(df))
            return None

        yesterday = dict(df.iloc[-1])

        if not target_date:
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

        score_components_baseline = self.technical_analyzer.calculate_baseline_score(df, enabled_indicators=enabled_indicators, aggregation=aggregation)
        total_score_baseline = score_components_baseline.pop("total", 0.0)

        score_components_mr = self.technical_analyzer.calculate_technical_score(df, strategy="mean_reversion", enabled_indicators=enabled_indicators, aggregation=aggregation)
        total_score_mr = score_components_mr.pop("total", 0.0)

        ret_val = {
            'symbol': symbol,
            'name': price_data.get('full_name', symbol),
            'date': str(yesterday['date']),
            'entry_price': entry_price,
            'stop_loss': entry_price * STOP_LOSS_FACTOR,
            'take_profit': entry_price * TAKE_PROFIT_FACTOR,
            'baseline_score': total_score_baseline,
            'baseline_components': score_components_baseline,
            'mr_score': total_score_mr,
            'mr_components': score_components_mr
        }
        logging.info("Processed %s with result: %s", symbol, ret_val)
        return ret_val

    def swing_predict(self, target_date: Optional[str] = None, enabled_indicators: Optional[list[str]] = None, aggregation: str = "sum") -> None:
        """Main prediction function with parallel processing capability."""
        symbols = get_symbol_name_list()
        # Reduce max_workers to avoid pegging CPU, and use as_completed for progress logging
        max_workers = min(8, os.cpu_count() or 4)
        results = []

        ReportSingleton().write(f"Yesterday was {'not ' if not GlobalData.holiday else ''}a holiday.")
        if target_date:
            ReportSingleton().write(f"Predicting for historical date: {target_date}")

        logging.info("Processing %d symbols with %d workers...", len(symbols), max_workers)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            process_func = partial(self.process_symbol, target_date=target_date, enabled_indicators=enabled_indicators, aggregation=aggregation)
            future_to_symbol = {executor.submit(process_func, sym): sym for sym in symbols}
            
            processed_count = 0
            total_symbols = len(symbols)
            for future in concurrent.futures.as_completed(future_to_symbol):
                processed_count += 1
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    symbol = future_to_symbol[future]
                    logging.error("%s generated an exception: %s", symbol, e)
                
                if processed_count % 100 == 0 or processed_count == total_symbols:
                    logging.info("Progress: %d/%d symbols processed (%.1f%%)", 
                                 processed_count, total_symbols, (processed_count/total_symbols)*100)

        # Filter None results
        valid_results = [r for r in results if r is not None]
        
        # 1. Handle Baseline (Trend) Results
        baseline_sorted = sorted(valid_results, key=lambda x: x['baseline_score'], reverse=True)
        ReportSingleton().write('\n--- Top 5 Baseline (Trend) Candidates ---')
        for i in range(min(5, len(baseline_sorted))):
            res = baseline_sorted[i]
            ReportSingleton().write(
                f"{res['symbol']} - Entry: {res['entry_price']:.2f} - "
                f"Score: {res['baseline_score']:.2f} - Name: {res['name']}"
            )

        # 2. Handle Mean Reversion (Dip) Results
        mr_sorted = sorted(valid_results, key=lambda x: x['mr_score'], reverse=True)
        ReportSingleton().write('\n--- Top 5 Mean Reversion (Dip) Candidates ---')
        for i in range(min(5, len(mr_sorted))):
            res = mr_sorted[i]
            ReportSingleton().write(
                f"{res['symbol']} - Entry: {res['entry_price']:.2f} - "
                f"Score: {res['mr_score']:.2f} - Name: {res['name']}"
            )

        # Save results to the trade_scores collection
        if valid_results:
            score_data = []
            for r in valid_results:
                # Add Baseline score
                score_data.append({
                    "symbol": r["symbol"],
                    "date": r["date"][:10],
                    "score": r["baseline_score"],
                    "strategy": "baseline",
                    "version": "1.5",
                    "metadata": {
                        "entry_price": r["entry_price"],
                        "stop_loss": r["stop_loss"],
                        "take_profit": r["take_profit"],
                        "components": r["baseline_components"]
                    }
                })
                # Add Mean Reversion score
                score_data.append({
                    "symbol": r["symbol"],
                    "date": r["date"][:10],
                    "score": r["mr_score"],
                    "strategy": "mean_reversion",
                    "version": "1.5",
                    "metadata": {
                        "entry_price": r["entry_price"],
                        "stop_loss": r["stop_loss"],
                        "take_profit": r["take_profit"],
                        "components": r["mr_components"]
                    }
                })
            
            score_manager.save_scores(score_data)
            logging.info("Saved %d scores (Baseline & Mean Reversion) to trade_scores", len(score_data))

