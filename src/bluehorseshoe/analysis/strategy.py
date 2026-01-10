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
from bluehorseshoe.analysis.ml_overlay import MLInference
from bluehorseshoe.analysis.ml_stop_loss import StopLossInference

class SwingTrader:
    """Main class for swing trading analysis."""

    def __init__(self):
        self.technical_analyzer = TechnicalAnalyzer()
        self.ml_inference = MLInference()
        self.stop_loss_inference = StopLossInference()

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

    def calculate_baseline_setup(self, df: pd.DataFrame, ml_stop_multiplier: float = 2.0) -> Dict[str, float]:
        """
        Calculate structural prices for Baseline (Trend) strategy:
        Entry = Pullback to EMA + Bullish candle close
        Stop = Below recent swing low or ml_stop_multiplier * ATR
        Target = Prior high or 3.0 * ATR
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

        # 4. Volatility (ATR)
        if 'ATR' not in df.columns:
            df['ATR'] = AverageTrueRange(
                high=df['high'],
                low=df['low'],
                close=df['close'],
                window=ATR_WINDOW
            ).average_true_range()
        atr = df.iloc[-1]['ATR']
        if pd.isna(atr):
            atr = last_close * 0.02 # Fallback to 2%

        # 5. Structural levels
        # Recent swing low (5-day)
        swing_low_5 = df['low'].rolling(window=5).min().iloc[-1]
        # Recent swing high (20-day) for target
        swing_high_20 = df['high'].rolling(window=20).max().iloc[-1]

        # Entry Logic:
        # If already bullish (Green Candle) and has volume support, buy at current close (Momentum).
        # We rely on the Risk:Reward calculation downstream to filter out over-extended setups.
        dist_to_ema = (last_close - ema9) / ema9

        rsi = last_row.get('rsi_14', 50)
        has_decent_volume = vol_ratio >= 0.8
        has_safe_rsi = rsi <= 70

        if is_bullish and has_decent_volume and has_safe_rsi:
            entry_price = last_close
        else:
            # Otherwise (Red candle or low volume), wait for a pullback to support.
            # Support is the higher of EMA 9 or the Previous Low.
            entry_price = max(ema9, last_row['low'])

        # Stop Loss: Use the lower of (Swing Low) or (ml_stop_multiplier * ATR)
        # This provides "breathing room" based on the stock's actual volatility.
        stop_loss = min(swing_low_5 * 0.985, entry_price - (ml_stop_multiplier * atr))

        # Take Profit: Prior 20-day high, or at least a 3.0 * ATR move
        take_profit = max(swing_high_20, entry_price + (3.0 * atr))

        # 6. Calculate Reward-to-Risk (R:R)
        reward = take_profit - entry_price
        risk = entry_price - stop_loss
        rr_ratio = reward / risk if risk > 0 else 0

        if rr_ratio < 0.5:
            print(f"DEBUG: {last_row.get('symbol', 'UNK')} RR Debug: entry={entry_price:.2f}, stop={stop_loss:.2f}, exit={take_profit:.2f}, atr={atr:.2f}, mult={ml_stop_multiplier:.2f}, risk={risk:.2f}, reward={reward:.2f}")

        # 7. Quality Check: Is the entry price realistic?
        # If the targeted entry (EMA) is more than 15% away from the close,
        # the price structure is likely broken or parabolic.
        dist_to_close = abs((last_close / entry_price) - 1)
        is_realistic = dist_to_close <= 0.15

        return {
            'entry_price': float(entry_price),
            'stop_loss': float(stop_loss),
            'take_profit': float(take_profit),
            'rr_ratio': float(rr_ratio),
            'vol_ratio': float(vol_ratio),
            'is_realistic': is_realistic
        }

    def calculate_mean_reversion_setup(self, df: pd.DataFrame, ml_stop_multiplier: float = 1.5) -> Dict[str, float]:
        """
        Calculate structural prices for Mean Reversion (Dip) strategy:
        Entry = Current Close (Buying extreme weakness)
        Stop = ml_stop_multiplier * ATR (Tighter stop for fast reversals)
        Target = Reversion to 20-day EMA
        """
        last_row = df.iloc[-1]
        last_close = last_row['close']

        # 1. EMA 20 for Target (The "Mean")
        ema20 = df['close'].ewm(span=20).mean().iloc[-1]

        # 2. Volatility (ATR)
        if 'ATR' not in df.columns:
            df['ATR'] = AverageTrueRange(
                high=df['high'],
                low=df['low'],
                close=df['close'],
                window=ATR_WINDOW
            ).average_true_range()
        atr = df.iloc[-1]['ATR']
        if pd.isna(atr):
            atr = last_close * 0.02

        # 3. Entry is current close
        entry_price = last_close

        # 4. Stop Loss: ml_stop_multiplier * ATR below entry
        stop_loss = entry_price - (ml_stop_multiplier * atr)

        # 5. Take Profit: EMA 20
        take_profit = max(ema20, entry_price + (2.0 * atr))

        # 6. Reward-to-Risk
        reward = take_profit - entry_price
        risk = entry_price - stop_loss
        rr_ratio = reward / risk if risk > 0 else 0

        return {
            'entry_price': float(entry_price),
            'stop_loss': float(stop_loss),
            'take_profit': float(take_profit),
            'rr_ratio': float(rr_ratio),
            'vol_ratio': last_row['volume'] / last_row.get('avg_volume_20', 1) if last_row.get('avg_volume_20', 0) > 0 else 0,
            'is_realistic': True
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
                print(f"DEBUG: {symbol} - DF empty after target_date filter")
                return None

            # Staleness check
            last_date = pd.to_datetime(df.iloc[-1]['date'])
            if (target_ts - last_date).days > 7:
                print(f"DEBUG: {symbol} - Data too stale: {last_date}")
                logging.info("Symbol %s data is too stale for target date %s. Skipping.", symbol, target_date)
                return None

        if len(df) < 30:
            print(f"DEBUG: {symbol} - Insufficient data: {len(df)}")
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

        # --- Baseline Strategy Processing ---
        baseline_data = None
        is_uptrend = self.is_weekly_uptrend(df)

        # Baseline strictly requires Weekly Uptrend if enabled
        if not REQUIRE_WEEKLY_UPTREND or is_uptrend:
            score_components = self.technical_analyzer.calculate_baseline_score(df, enabled_indicators=enabled_indicators, aggregation=aggregation)

            # Predict ML Stop Loss Multiplier
            # ml_stop_multiplier = self.stop_loss_inference.predict_stop_loss_multiplier(symbol, score_components, target_date=str(yesterday['date'])[:10])
            ml_stop_multiplier = 2.0

            baseline_setup = self.calculate_baseline_setup(df, ml_stop_multiplier=ml_stop_multiplier)
            if baseline_setup['is_realistic'] and baseline_setup['rr_ratio'] >= MIN_RR_RATIO:
                entry_price = baseline_setup['entry_price']
                if MIN_STOCK_PRICE < entry_price < MAX_STOCK_PRICE:
                    # Apply Relative Strength (RS) Bonus
                    rs_ratio = 1.0
                    if benchmark_df is not None:
                        rs_ratio = self.calculate_relative_strength(df, benchmark_df)
                        if rs_ratio > 1.10: rs_bonus = 5.0
                        elif rs_ratio > 1.0: rs_bonus = 2.0
                        else: rs_bonus = -2.0
                        score_components["rs_index"] = rs_bonus
                        score_components["total"] += rs_bonus

                    # Calculate ML Win Probability
                    ml_prob = self.ml_inference.predict_probability(symbol, score_components, target_date=str(yesterday['date'])[:10], strategy="baseline")

                    baseline_data = {
                        "score": score_components.pop("total", 0.0),
                        "components": score_components,
                        "setup": baseline_setup,
                        "ml_prob": ml_prob,
                        "stop_multiplier": ml_stop_multiplier
                    }
                else:
                    print(f"DEBUG: {symbol} - Baseline price out of range: {entry_price}")
            else:
                print(f"DEBUG: {symbol} - Baseline failed setup checks: realistic={baseline_setup['is_realistic']}, rr={baseline_setup['rr_ratio']}")
        else:
            print(f"DEBUG: {symbol} - Baseline failed weekly uptrend")

        # --- Mean Reversion Strategy Processing ---
        mr_data = None
        # MR relaxes the Weekly Uptrend requirement (can buy dips in Stage 1/4)
        score_components_mr = self.technical_analyzer.calculate_technical_score(df, strategy="mean_reversion", enabled_indicators=enabled_indicators, aggregation=aggregation)

        # Predict ML Stop Loss Multiplier (specifically for MR)
        ml_stop_multiplier_mr = self.stop_loss_inference.predict_stop_loss_multiplier(symbol, score_components_mr, target_date=str(yesterday['date'])[:10])

        mr_setup = self.calculate_mean_reversion_setup(df, ml_stop_multiplier=ml_stop_multiplier_mr)
        if mr_setup['rr_ratio'] >= MIN_RR_RATIO:
            entry_price = mr_setup['entry_price']
            if MIN_STOCK_PRICE < entry_price < MAX_STOCK_PRICE:
                # Calculate ML Win Probability
                ml_prob_mr = self.ml_inference.predict_probability(symbol, score_components_mr, target_date=str(yesterday['date'])[:10], strategy="mean_reversion")

                mr_data = {
                    "score": score_components_mr.pop("total", 0.0),
                    "components": score_components_mr,
                    "setup": mr_setup,
                    "ml_prob": ml_prob_mr,
                    "stop_multiplier": ml_stop_multiplier_mr
                }

        if not baseline_data and not mr_data:
            return None

        # Calculate RS ratio once if not already done
        rs_ratio = self.calculate_relative_strength(df, benchmark_df) if benchmark_df is not None else 1.0

        ret_val = {
            'symbol': symbol,
            'name': price_data.get('full_name', symbol),
            'date': str(yesterday['date']),
            'rs_ratio': rs_ratio,
            'baseline_score': baseline_data['score'] if baseline_data else 0.0,
            'baseline_components': baseline_data['components'] if baseline_data else {},
            'baseline_setup': baseline_data['setup'] if baseline_data else {},
            'baseline_ml_prob': baseline_data['ml_prob'] if baseline_data else 0.0,
            'mr_score': mr_data['score'] if mr_data else 0.0,
            'mr_components': mr_data['components'] if mr_data else {},
            'mr_setup': mr_data['setup'] if mr_data else {},
            'mr_ml_prob': mr_data['ml_prob'] if mr_data else 0.0
        }
        logging.info("Processed %s with results Baseline: %.2f, MR: %.2f", symbol, ret_val['baseline_score'], ret_val['mr_score'])
        return ret_val

    def swing_predict(self, target_date: Optional[str] = None, enabled_indicators: Optional[list[str]] = None, aggregation: str = "sum", symbols: Optional[list[str]] = None) -> None:
        """Main prediction function with parallel processing capability."""

        # 1. Market Context Filter (The "Big Picture")
        market_health = MarketRegime.get_market_health(target_date=target_date)
        ReportSingleton().write(f"Market Status: {market_health['status']} ({market_health['multiplier']}x risk)")

        # if market_health['status'] == 'Bearish':
        #     ReportSingleton().write("BROAD MARKET IS BEARISH. Skipping all long signals to protect capital.")
        #     return

        # Load Benchmark for Relative Strength
        benchmark_data = load_historical_data("SPY")
        benchmark_df = None
        if benchmark_data and benchmark_data.get('days'):
            benchmark_df = pd.DataFrame(benchmark_data['days'])
            if target_date:
                benchmark_df['date'] = pd.to_datetime(benchmark_df['date'])
                benchmark_df = benchmark_df[benchmark_df['date'] <= pd.to_datetime(target_date)]

        if symbols is None:
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

                if processed_count % 50 == 0 or processed_count == total_symbols:
                    msg = f"Progress: {processed_count}/{total_symbols} symbols processed ({(processed_count/total_symbols)*100:.1f}%)"
                    logging.info(msg)
                    print(msg, flush=True)

        # Filter None results
        valid_results = [r for r in results if r is not None]

        # 1. Handle Baseline (Trend) Results
        baseline_sorted = sorted([r for r in valid_results if r['baseline_score'] > 0], key=lambda x: x['baseline_score'], reverse=True)
        ReportSingleton().write('\n--- Top 5 Baseline (Trend) Candidates ---')
        for i in range(min(5, len(baseline_sorted))):
            res = baseline_sorted[i]
            setup = res['baseline_setup']
            ReportSingleton().write(
                f"{res['symbol']} - Entry: {setup['entry_price']:.2f} | "
                f"Stop: {setup['stop_loss']:.2f} (SL Mult: {res.get('stop_multiplier', 0):.1f}) | Exit: {setup['take_profit']:.2f} | "
                f"Score: {res['baseline_score']:.2f} | ML Win%: {res['baseline_ml_prob']*100:.1f}% - Name: {res['name']}"
            )

        # 2. Handle Mean Reversion (Dip) Results
        mr_sorted = sorted([r for r in valid_results if r['mr_score'] > 0], key=lambda x: x['mr_score'], reverse=True)
        ReportSingleton().write('\n--- Top 5 Mean Reversion (Dip) Candidates ---')
        for i in range(min(5, len(mr_sorted))):
            res = mr_sorted[i]
            setup = res['mr_setup']
            ReportSingleton().write(
                f"{res['symbol']} - Entry: {setup['entry_price']:.2f} | "
                f"Stop: {setup['stop_loss']:.2f} (SL Mult: {res.get('stop_multiplier', 0):.1f}) | Exit: {setup['take_profit']:.2f} | "
                f"Score: {res['mr_score']:.2f} | ML Win%: {res['mr_ml_prob']*100:.1f}% - Name: {res['name']}"
            )

        # Save results to the trade_scores collection
        if valid_results:
            score_data = []
            for r in valid_results:
                # Add Baseline score
                if r['baseline_score'] > 0:
                    setup = r['baseline_setup']
                    score_data.append({
                        "symbol": r["symbol"],
                        "date": r["date"][:10],
                        "score": r["baseline_score"],
                        "strategy": "baseline",
                        "version": "1.6", # Incremented version
                        "metadata": {
                            "entry_price": setup["entry_price"],
                            "stop_loss": setup["stop_loss"],
                            "take_profit": setup["take_profit"],
                            "ml_win_prob": r["baseline_ml_prob"],
                            "stop_multiplier": r.get("stop_multiplier", 2.0),
                            "components": r["baseline_components"]
                        }
                    })
                # Add Mean Reversion score
                if r['mr_score'] > 0:
                    setup = r['mr_setup']
                    score_data.append({
                        "symbol": r["symbol"],
                        "date": r["date"][:10],
                        "score": r["mr_score"],
                        "strategy": "mean_reversion",
                        "version": "1.6",
                        "metadata": {
                            "entry_price": setup["entry_price"],
                            "stop_loss": setup["stop_loss"],
                            "take_profit": setup["take_profit"],
                            "ml_win_prob": r["mr_ml_prob"],
                            "stop_multiplier": r.get("stop_multiplier", 1.5),
                            "components": r["mr_components"]
                        }
                    })

            score_manager.save_scores(score_data)
            logging.info("Saved %d scores (Baseline & Mean Reversion) to trade_scores", len(score_data))

