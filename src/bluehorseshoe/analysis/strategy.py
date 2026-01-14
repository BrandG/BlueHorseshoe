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
import concurrent.futures
from functools import partial
from dataclasses import dataclass
from typing import Dict, Optional, List, Any

import pandas as pd
from ta.volatility import AverageTrueRange

from bluehorseshoe.analysis.constants import (
    MIN_STOCK_PRICE, MAX_STOCK_PRICE,
    ATR_WINDOW,
    MIN_RR_RATIO, REQUIRE_WEEKLY_UPTREND
)

from bluehorseshoe.analysis.market_regime import MarketRegime
from bluehorseshoe.analysis.ml_overlay import MLInference
from bluehorseshoe.analysis.ml_stop_loss import StopLossInference
from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer
from bluehorseshoe.core.globals import GlobalData
from bluehorseshoe.core.scores import score_manager
from bluehorseshoe.core.symbols import get_symbol_name_list
from bluehorseshoe.data.historical_data import load_historical_data
from bluehorseshoe.reporting.report_generator import ReportSingleton

@dataclass
class StrategyContext:
    """Encapsulates common parameters for strategy processing."""
    target_date: Optional[str] = None
    enabled_indicators: Optional[List[str]] = None
    aggregation: str = "sum"
    benchmark_df: Optional[pd.DataFrame] = None
    market_health: Optional[Dict[str, Any]] = None

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

    def _calculate_atr(self, df: pd.DataFrame) -> float:
        """Helper to calculate or retrieve ATR."""
        if 'ATR' not in df.columns:
            df['ATR'] = AverageTrueRange(
                high=df['high'],
                low=df['low'],
                close=df['close'],
                window=ATR_WINDOW
            ).average_true_range()
        atr = df.iloc[-1]['ATR']
        if pd.isna(atr):
            return df.iloc[-1]['close'] * 0.02
        return atr

    def _determine_baseline_entry(self, last_row: pd.Series, ema9: float) -> float:
        """Helper to determine entry price based on momentum or pullback."""
        last_close = last_row['close']
        is_bullish = last_close > last_row['open']

        avg_volume = last_row.get('avg_volume_20', 1)
        vol_ratio = last_row['volume'] / avg_volume if avg_volume > 0 else 0
        has_decent_volume = vol_ratio >= 0.8

        rsi = last_row.get('rsi_14', 50)
        has_safe_rsi = rsi <= 70

        if is_bullish and has_decent_volume and has_safe_rsi:
            return last_close

        return max(ema9, last_row['low'])

    def calculate_baseline_setup(self, df: pd.DataFrame, ml_stop_multiplier: float = 2.0) -> Dict[str, float]:
        """
        Calculate structural prices for Baseline (Trend) strategy:
        Entry = Pullback to EMA + Bullish candle close
        Stop = Below recent swing low or ml_stop_multiplier * ATR
        Target = Prior high or 3.0 * ATR
        """
        last_row = df.iloc[-1]
        last_close = last_row['close']

        # 1. Indicators
        ema9 = df['close'].ewm(span=9).mean().iloc[-1]
        atr = self._calculate_atr(df)

        # 2. Structural levels
        swing_low_5 = df['low'].rolling(window=5).min().iloc[-1]
        swing_high_20 = df['high'].rolling(window=20).max().iloc[-1]

        # 3. Entry Logic
        entry_price = self._determine_baseline_entry(last_row, ema9)

        # 4. Stop Loss & Take Profit
        stop_loss = min(swing_low_5 * 0.985, entry_price - (ml_stop_multiplier * atr))
        take_profit = max(swing_high_20, entry_price + (3.0 * atr))

        # 5. Risk Calculation
        rr_ratio = (take_profit - entry_price) / (entry_price - stop_loss) if (entry_price - stop_loss) > 0 else 0

        # Debugging
        if rr_ratio < 0.5:
            print(
                f"DEBUG: {last_row.get('symbol', 'UNK')} RR Debug: entry={entry_price:.2f}, "
                f"stop={stop_loss:.2f}, exit={take_profit:.2f}, atr={atr:.2f}, "
                f"mult={ml_stop_multiplier:.2f}, rr={rr_ratio:.2f}"
            )

        # 6. Quality Check & Return
        avg_volume = last_row.get('avg_volume_20', 1)

        return {
            'entry_price': float(entry_price),
            'stop_loss': float(stop_loss),
            'take_profit': float(take_profit),
            'rr_ratio': float(rr_ratio),
            'vol_ratio': float(last_row['volume'] / avg_volume if avg_volume > 0 else 0),
            'is_realistic': abs((last_close / entry_price) - 1) <= 0.15
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

    def _load_and_validate_data(self, symbol: str, target_date: Optional[str]) -> Optional[tuple[pd.DataFrame, dict, dict]]:
        """Helper to load and validate historical data."""
        price_data = load_historical_data(symbol)
        if price_data is None or not price_data.get('days'):
            logging.error("Failed to load historical data for %s.", symbol)
            return None

        df = pd.DataFrame(price_data['days'])

        if target_date:
            df['date'] = pd.to_datetime(df['date'])
            target_ts = pd.to_datetime(target_date)
            df = df[df['date'] <= target_ts]

            if not df.empty:
                last_date = pd.to_datetime(df.iloc[-1]['date'])
                if (target_ts - last_date).days > 7:
                    logging.info("Symbol %s data is too stale for target date %s. Skipping.", symbol, target_date)
                    return None

        if df.empty or len(df) < 30:
            logging.info("Symbol %s has insufficient data (%d days) for target date. Skipping.", symbol, len(df))
            return None

        yesterday = dict(df.iloc[-1])
        if not target_date and not GlobalData.holiday:
            last_trading_day = pd.Timestamp.now().normalize() - pd.offsets.BDay(1)
            yesterday['date'] = pd.to_datetime(yesterday['date'])
            if yesterday['date'] != last_trading_day:
                logging.error("Data for %s on date '%s' is not '%s'.", symbol, yesterday['date'], last_trading_day)
                with open('src/error_symbols.txt', 'a', encoding='utf-8') as f:
                    f.write(f"{symbol}\n")
                return None

        return df, price_data, yesterday

    def _process_baseline(self, df: pd.DataFrame, symbol: str, yesterday: dict, ctx: StrategyContext) -> Optional[Dict]:
        """Process Baseline strategy logic."""
        # Regime Filter: Skip momentum during bearish regimes
        if ctx.market_health and ctx.market_health['status'] == 'Bearish':
            return None

        is_uptrend = self.is_weekly_uptrend(df)
        if REQUIRE_WEEKLY_UPTREND and not is_uptrend:
            print(f"DEBUG: {symbol} - Baseline failed weekly uptrend")
            return None

        score_components = self.technical_analyzer.calculate_baseline_score(
            df,
            enabled_indicators=ctx.enabled_indicators,
            aggregation=ctx.aggregation
        )

        ml_stop_multiplier = 2.0
        baseline_setup = self.calculate_baseline_setup(df, ml_stop_multiplier=ml_stop_multiplier)

        if not baseline_setup['is_realistic'] or baseline_setup['rr_ratio'] < MIN_RR_RATIO:
            print(f"DEBUG: {symbol} - Baseline failed setup checks: realistic={baseline_setup['is_realistic']}, rr={baseline_setup['rr_ratio']}")
            return None

        entry_price = baseline_setup['entry_price']
        if not MIN_STOCK_PRICE < entry_price < MAX_STOCK_PRICE:
            print(f"DEBUG: {symbol} - Baseline price out of range: {entry_price}")
            return None

        # Apply Relative Strength (RS) Bonus
        if ctx.benchmark_df is not None:
            rs_ratio = self.calculate_relative_strength(df, ctx.benchmark_df)
            if rs_ratio > 1.10:
                rs_bonus = 5.0
            elif rs_ratio > 1.0:
                rs_bonus = 2.0
            else:
                rs_bonus = -2.0
            score_components["rs_index"] = rs_bonus
            score_components["total"] += rs_bonus

        # Calculate ML Win Probability
        ml_prob = self.ml_inference.predict_probability(
            symbol,
            score_components,
            target_date=str(yesterday['date'])[:10],
            strategy="baseline"
        )

        return {
            "score": score_components.pop("total", 0.0),
            "components": score_components,
            "setup": baseline_setup,
            "ml_prob": ml_prob,
            "stop_multiplier": ml_stop_multiplier
        }

    def _process_mr(self, df: pd.DataFrame, symbol: str, yesterday: dict, ctx: StrategyContext) -> Optional[Dict]:
        """Process Mean Reversion strategy logic."""
        score_components_mr = self.technical_analyzer.calculate_technical_score(
            df,
            strategy="mean_reversion",
            enabled_indicators=ctx.enabled_indicators,
            aggregation=ctx.aggregation
        )

        # Predict ML Stop Loss Multiplier
        ml_stop_multiplier_mr = self.stop_loss_inference.predict_stop_loss_multiplier(
            symbol,
            score_components_mr,
            target_date=str(yesterday['date'])[:10]
        )

        mr_setup = self.calculate_mean_reversion_setup(df, ml_stop_multiplier=ml_stop_multiplier_mr)
        if mr_setup['rr_ratio'] < MIN_RR_RATIO:
            return None

        entry_price = mr_setup['entry_price']
        if not MIN_STOCK_PRICE < entry_price < MAX_STOCK_PRICE:
            return None

        # Calculate ML Win Probability
        ml_prob_mr = self.ml_inference.predict_probability(
            symbol,
            score_components_mr,
            target_date=str(yesterday['date'])[:10],
            strategy="mean_reversion"
        )

        return {
            "score": score_components_mr.pop("total", 0.0),
            "components": score_components_mr,
            "setup": mr_setup,
            "ml_prob": ml_prob_mr,
            "stop_multiplier": ml_stop_multiplier_mr
        }

    def process_symbol(self, symbol: str, ctx: StrategyContext) -> Optional[Dict]:
        """Process a single symbol and return its trading data."""
        # 1. Load and Validate Data
        data_result = self._load_and_validate_data(symbol, ctx.target_date)
        if not data_result:
            return None
        df, price_data, yesterday = data_result

        # 2. Process Strategies
        baseline_data = self._process_baseline(df, symbol, yesterday, ctx)
        mr_data = self._process_mr(df, symbol, yesterday, ctx)

        if not baseline_data and not mr_data:
            return None

        # 3. Finalize Result
        rs_ratio = 1.0
        if ctx.benchmark_df is not None:
            rs_ratio = self.calculate_relative_strength(df, ctx.benchmark_df)

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
    def _load_benchmark_data(self, target_date: Optional[str]) -> Optional[pd.DataFrame]:
        benchmark_data = load_historical_data("SPY")
        if benchmark_data and benchmark_data.get('days'):
            df = pd.DataFrame(benchmark_data['days'])
            if target_date:
                df['date'] = pd.to_datetime(df['date'])
                df = df[df['date'] <= pd.to_datetime(target_date)]
            return df
        return None

    def _execute_prediction_batch(self, symbols: List[str], ctx: StrategyContext) -> List[Dict]:
        """Execute parallel prediction for a batch of symbols."""
        max_workers = min(8, os.cpu_count() or 4)

        ReportSingleton().write(f"Yesterday was {'not ' if not GlobalData.holiday else ''}a holiday.")
        if ctx.target_date:
            ReportSingleton().write(f"Predicting for historical date: {ctx.target_date}")
        logging.info("Processing %d symbols with %d workers...", len(symbols), max_workers)

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Partial binding for the common arguments
            process_func = partial(
                self.process_symbol,
                ctx=ctx
            )

            # Submit all tasks
            future_map = {executor.submit(process_func, sym): sym for sym in symbols}

            total = len(symbols)
            for i, future in enumerate(concurrent.futures.as_completed(future_map), 1):
                try:
                    res = future.result()
                    results.append(res)
                except Exception as e: # pylint: disable=broad-exception-caught
                    sym = future_map[future]
                    logging.error("%s generated an exception: %s", sym, e)

                if i % 50 == 0 or i == total:
                    pct = (i / total) * 100
                    logging.info("Progress: %d/%d symbols processed (%.1f%%)", i, total, pct)
                    print(f"Progress: {i}/{total} symbols processed ({pct:.1f}%)", flush=True)

        return [r for r in results if r is not None]

    def _report_top_candidates(self, results, strategy_key, setup_key, title):
        sorted_results = sorted([r for r in results if r[strategy_key] > 0], key=lambda x: x[strategy_key], reverse=True)
        ReportSingleton().write(f'\n--- Top 5 {title} Candidates ---')
        for i in range(min(5, len(sorted_results))):
            res = sorted_results[i]
            setup = res[setup_key]
            prob_key = 'baseline_ml_prob' if 'baseline' in strategy_key else 'mr_ml_prob'
            ReportSingleton().write(
                f"{res['symbol']} - Entry: {setup['entry_price']:.2f} | "
                f"Stop: {setup['stop_loss']:.2f} (SL Mult: {res.get('stop_multiplier', 0):.1f}) | Exit: {setup['take_profit']:.2f} | "
                f"Score: {res[strategy_key]:.2f} | ML Win%: {res[prob_key]*100:.1f}% - Name: {res['name']}"
            )

    def _prepare_scores_for_save(self, valid_results) -> List[Dict]:
        score_data = []
        for r in valid_results:
            if r['baseline_score'] > 0:
                setup = r['baseline_setup']
                score_data.append({
                    "symbol": r["symbol"],
                    "date": r["date"][:10],
                    "score": r["baseline_score"],
                    "strategy": "baseline",
                    "version": "1.6",
                    "metadata": {
                        "entry_price": setup["entry_price"],
                        "stop_loss": setup["stop_loss"],
                        "take_profit": setup["take_profit"],
                        "ml_win_prob": r["baseline_ml_prob"],
                        "stop_multiplier": r.get("stop_multiplier", 2.0),
                        "components": r["baseline_components"]
                    }
                })
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
        return score_data

    def swing_predict(
        self,
        target_date: Optional[str] = None,
        enabled_indicators: Optional[list[str]] = None,
        aggregation: str = "sum",
        symbols: Optional[list[str]] = None
    ) -> Dict[str, Any]:
        """Main prediction function with parallel processing capability."""

        # 1. Market Context Filter
        market_health = MarketRegime.get_market_health(target_date=target_date)
        ReportSingleton().write(f"Market Status: {market_health['status']} ({market_health['multiplier']}x risk)")

        # 2. Setup Data
        benchmark_df = self._load_benchmark_data(target_date)
        if symbols is None:
            symbols = get_symbol_name_list()

        ctx = StrategyContext(
            target_date=target_date,
            enabled_indicators=enabled_indicators,
            aggregation=aggregation,
            benchmark_df=benchmark_df,
            market_health=market_health
        )

        # 3. Execute
        valid_results = self._execute_prediction_batch(symbols, ctx)

        # 4. Report & Collect Data
        # We print to console/txt via ReportSingleton inside these helpers
        self._report_top_candidates(valid_results, 'baseline_score', 'baseline_setup', 'Baseline (Trend)')
        self._report_top_candidates(valid_results, 'mr_score', 'mr_setup', 'Mean Reversion (Dip)')

        # 5. Save
        if valid_results:
            score_data = self._prepare_scores_for_save(valid_results)
            score_manager.save_scores(score_data)
            logging.info("Saved %d scores (Baseline & Mean Reversion) to trade_scores", len(score_data))

        # 6. Prepare Return Data for HTML Reporter
        candidates = []
        for r in valid_results:
            # Flatten results for the reporter
            if r['baseline_score'] > 0:
                setup = r['baseline_setup']
                candidates.append({
                    "symbol": r["symbol"],
                    "strategy": "Baseline",
                    "score": r["baseline_score"],
                    "close": setup.get("entry_price", 0), # Approx
                    "reasons": [f"{k}={v:.1f}" for k, v in r['baseline_components'].items() if v != 0]
                })
            if r['mr_score'] > 0:
                setup = r['mr_setup']
                candidates.append({
                    "symbol": r["symbol"],
                    "strategy": "MeanRev",
                    "score": r["mr_score"],
                    "close": setup.get("entry_price", 0),
                    "reasons": [f"{k}={v:.1f}" for k, v in r['mr_components'].items() if v != 0]
                })

        # Sort by score desc
        candidates.sort(key=lambda x: x['score'], reverse=True)

        return {
            "regime": market_health,
            "candidates": candidates[:50], # Top 50 for the report
            "charts": [] # TODO: Add chart generation logic if needed
        }
