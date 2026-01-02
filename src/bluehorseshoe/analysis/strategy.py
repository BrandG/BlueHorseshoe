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
    STOP_LOSS_FACTOR, TAKE_PROFIT_FACTOR, ATR_WINDOW, ATR_MULTIPLIER_UPTREND, ATR_MULTIPLIER_DOWNTREND,
    MIN_RR_RATIO, MIN_REL_VOLUME, REQUIRE_WEEKLY_UPTREND
)
from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer
from bluehorseshoe.analysis.market_regime import MarketRegime

class SwingTrader:
    """Main class for swing trading analysis."""

    def __init__(self):
        self.technical_analyzer = TechnicalAnalyzer()

    def is_weekly_uptrend(self, df: pd.DataFrame) -> bool:
        """
        Resamples daily data to weekly and checks for a primary uptrend using 
        Stage Analysis (10-week EMA > 30-week EMA).
        """
        # Create a copy to avoid modifying the original during resampling
        w_df = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(w_df['date']):
            w_df['date'] = pd.to_datetime(w_df['date'])
        
        # Resample to weekly (Sunday as the end of week)
        weekly = w_df.resample('W', on='date').agg({
            'close': 'last'
        })
        
        if len(weekly) < 12:
            return True # Insufficient history (need at least 3 months), don't penalize
            
        ema10 = weekly['close'].ewm(span=10).mean()
        ema30 = weekly['close'].ewm(span=30).mean()
        
        last_ema10 = ema10.iloc[-1]
        last_ema30 = ema30.iloc[-1]
        
        return last_ema10 > last_ema30

    def calculate_structural_setup(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Calculate structural prices based on the requested strategy:
        Entry = Pullback to EMA + Bullish candle close
        Stop = Below recent swing low
        Target = Prior high or measured move
        """
        last_row = df.iloc[-1]
        last_close = last_row['close']
        
        # 1. EMAs for support
        ema9 = df['close'].ewm(span=9).mean().iloc[-1]
        
        # 2. Bullish Confirmation (Last candle closed green)
        is_bullish = last_close > last_row['open']
        
        # 3. Volume Confirmation (Above average volume)
        avg_volume = last_row.get('avg_volume_20', 1)
        vol_ratio = last_row['volume'] / avg_volume if avg_volume > 0 else 0
        has_volume_support = vol_ratio >= MIN_REL_VOLUME
        
        # 4. Structural levels
        # Recent swing low (5-day)
        swing_low_5 = df['low'].rolling(window=5).min().iloc[-1]
        # Recent swing high (20-day) for target
        swing_high_20 = df['high'].rolling(window=20).max().iloc[-1]
        
        # Entry Logic:
        # If already bullish, has volume support, and near EMA 9 (within 1.5%), buy at current close.
        # This ensures we don't set "unrealistically" low entries for strong runners.
        if is_bullish and has_volume_support and (last_close < ema9 * 1.015):
            entry_price = last_close
        else:
            # Otherwise, wait for a pullback to EMA 9 (support)
            entry_price = ema9
            
        # Stop Loss: Below the 5-day low, but capped at 3% from entry for tighter risk control
        # if the swing low is too far away, or below entry if swing low is above us.
        stop_loss = min(swing_low_5 * 0.99, entry_price * 0.97)
        
        # Take Profit: Prior 20-day high, or at least a 5% gain (Measured Move)
        take_profit = max(swing_high_20, entry_price * 1.05)
        
        # 5. Calculate Reward-to-Risk (R:R)
        reward = take_profit - entry_price
        risk = entry_price - stop_loss
        rr_ratio = reward / risk if risk > 0 else 0
        
        return {
            'entry_price': float(entry_price),
            'stop_loss': float(stop_loss),
            'take_profit': float(take_profit),
            'rr_ratio': float(rr_ratio),
            'vol_ratio': float(vol_ratio)
        }

    def calculate_relative_strength(self, df: pd.DataFrame, benchmark_df: pd.DataFrame, lookback: int = 63) -> float:
        """
        Calculates Relative Strength (RS) ratio of the stock vs the benchmark.
        A value > 1.0 means the stock is outperforming the benchmark over the lookback period.
        Default lookback is 63 trading days (~3 months).
        """
        if len(df) < lookback or len(benchmark_df) < lookback:
            return 1.0
            
        stock_perf = df['close'].iloc[-1] / df['close'].iloc[-lookback]
        bench_perf = benchmark_df['close'].iloc[-1] / benchmark_df['close'].iloc[-lookback]
        
        return stock_perf / bench_perf if bench_perf > 0 else 1.0

    def process_symbol(self, symbol: str, target_date: Optional[str] = None, enabled_indicators: Optional[list[str]] = None, aggregation: str = "sum", benchmark_df: Optional[pd.DataFrame] = None) -> Optional[Dict]:
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
            
            # Staleness check
            last_date = pd.to_datetime(df.iloc[-1]['date'])
            if (target_ts - last_date).days > 7:
                logging.info("Symbol %s data is too stale for target date %s. Skipping.", symbol, target_date)
                return None
            
        if len(df) < 30:
            logging.info("Symbol %s has insufficient data (%d days) for target date. Skipping.", symbol, len(df))
            return None

        # Multi-Timeframe Alignment Filter
        if REQUIRE_WEEKLY_UPTREND and not self.is_weekly_uptrend(df):
            logging.info("Symbol %s skipped: Not in a primary Weekly uptrend.", symbol)
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

        # Calculate Structural Prices (Entry, Stop, Target)
        setup = self.calculate_structural_setup(df)
        
        # Reward-to-Risk Filter
        if setup['rr_ratio'] < MIN_RR_RATIO:
            logging.info("Symbol %s skipped due to poor R:R ratio: %.2f", symbol, setup['rr_ratio'])
            return None

        entry_price = setup['entry_price']
        
        if not MIN_STOCK_PRICE < entry_price < MAX_STOCK_PRICE:
            return None

        # Calculate Scores
        score_components_baseline = self.technical_analyzer.calculate_baseline_score(df, enabled_indicators=enabled_indicators, aggregation=aggregation)
        
        # Apply Relative Strength (RS) Bonus to Baseline
        rs_ratio = 1.0
        if benchmark_df is not None:
            rs_ratio = self.calculate_relative_strength(df, benchmark_df)
            # If outperforming by > 10%, give a significant bonus
            if rs_ratio > 1.10:
                rs_bonus = 5.0
            elif rs_ratio > 1.0:
                rs_bonus = 2.0
            else:
                rs_bonus = -2.0
            
            score_components_baseline["rs_index"] = rs_bonus
            score_components_baseline["total"] += rs_bonus

        total_score_baseline = score_components_baseline.pop("total", 0.0)

        score_components_mr = self.technical_analyzer.calculate_technical_score(df, strategy="mean_reversion", enabled_indicators=enabled_indicators, aggregation=aggregation)
        total_score_mr = score_components_mr.pop("total", 0.0)

        ret_val = {
            'symbol': symbol,
            'name': price_data.get('full_name', symbol),
            'date': str(yesterday['date']),
            'entry_price': entry_price,
            'stop_loss': setup['stop_loss'],
            'take_profit': setup['take_profit'],
            'baseline_score': total_score_baseline,
            'baseline_components': score_components_baseline,
            'mr_score': total_score_mr,
            'mr_components': score_components_mr,
            'rs_ratio': rs_ratio
        }
        logging.info("Processed %s with result: %s", symbol, ret_val)
        return ret_val

    def swing_predict(self, target_date: Optional[str] = None, enabled_indicators: Optional[list[str]] = None, aggregation: str = "sum") -> None:
        """Main prediction function with parallel processing capability."""
        
        # 1. Market Context Filter (The "Big Picture")
        market_health = MarketRegime.get_market_health(target_date=target_date)
        ReportSingleton().write(f"Market Status: {market_health['status']} ({market_health['multiplier']}x risk)")
        
        if market_health['status'] == 'Bearish':
            ReportSingleton().write("BROAD MARKET IS BEARISH. Skipping all long signals to protect capital.")
            return

        # Load Benchmark for Relative Strength
        benchmark_data = load_historical_data("SPY")
        benchmark_df = None
        if benchmark_data and benchmark_data.get('days'):
            benchmark_df = pd.DataFrame(benchmark_data['days'])
            if target_date:
                benchmark_df['date'] = pd.to_datetime(benchmark_df['date'])
                benchmark_df = benchmark_df[benchmark_df['date'] <= pd.to_datetime(target_date)]

        symbols = get_symbol_name_list()
        # Reduce max_workers to avoid pegging CPU, and use as_completed for progress logging
        max_workers = min(8, os.cpu_count() or 4)
        results = []

        ReportSingleton().write(f"Yesterday was {'not ' if not GlobalData.holiday else ''}a holiday.")
        if target_date:
            ReportSingleton().write(f"Predicting for historical date: {target_date}")

        logging.info("Processing %d symbols with %d workers...", len(symbols), max_workers)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            process_func = partial(self.process_symbol, target_date=target_date, enabled_indicators=enabled_indicators, aggregation=aggregation, benchmark_df=benchmark_df)
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
                f"{res['symbol']} - Entry: {res['entry_price']:.2f} | "
                f"Stop: {res['stop_loss']:.2f} | Exit: {res['take_profit']:.2f} | "
                f"Score: {res['baseline_score']:.2f} - Name: {res['name']}"
            )

        # 2. Handle Mean Reversion (Dip) Results
        mr_sorted = sorted(valid_results, key=lambda x: x['mr_score'], reverse=True)
        ReportSingleton().write('\n--- Top 5 Mean Reversion (Dip) Candidates ---')
        for i in range(min(5, len(mr_sorted))):
            res = mr_sorted[i]
            ReportSingleton().write(
                f"{res['symbol']} - Entry: {res['entry_price']:.2f} | "
                f"Stop: {res['stop_loss']:.2f} | Exit: {res['take_profit']:.2f} | "
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

