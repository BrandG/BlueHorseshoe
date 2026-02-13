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
from pymongo.database import Database
from ta.volatility import AverageTrueRange

from bluehorseshoe.analysis.constants import (
    MIN_STOCK_PRICE, MAX_STOCK_PRICE,
    ATR_WINDOW,
    MIN_RR_RATIO_BASELINE, MIN_RR_RATIO_MEAN_REVERSION,
    MAX_RISK_PERCENT,
    REQUIRE_WEEKLY_UPTREND,
    SIGNAL_STRENGTH_THRESHOLDS,
    ENTRY_DISCOUNT_BY_SIGNAL,
    ENABLE_DYNAMIC_ENTRY
)
from bluehorseshoe.analysis.market_regime import MarketRegime
from bluehorseshoe.analysis.ml_overlay import MLInference
from bluehorseshoe.analysis.ml_stop_loss import StopLossInference
from bluehorseshoe.analysis.ml_profit_target import ProfitTargetInference
from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer
from bluehorseshoe.core.config import Settings, get_settings, weights_config
from bluehorseshoe.core.scores import ScoreManager
from bluehorseshoe.core.symbols import get_symbol_name_list, get_symbols_from_mongo
from bluehorseshoe.data.historical_data import load_historical_data
from bluehorseshoe.reporting.report_generator import ReportWriter, ReportSingleton

@dataclass
class StrategyContext:
    """Encapsulates common parameters for strategy processing."""
    target_date: Optional[str] = None
    enabled_indicators: Optional[List[str]] = None
    aggregation: str = "sum"
    benchmark_df: Optional[pd.DataFrame] = None
    market_health: Optional[Dict[str, Any]] = None
    symbol_map: Optional[Dict[str, str]] = None

class SwingTrader:
    """Main class for swing trading analysis."""

    def __init__(
        self,
        database: Optional[Database] = None,
        config: Optional[Settings] = None,
        ml_inference: Optional[MLInference] = None,
        stop_loss_inference: Optional[StopLossInference] = None,
        profit_target_inference: Optional[ProfitTargetInference] = None,
        report_writer: Optional[ReportWriter] = None
    ):
        """
        Initialize SwingTrader with dependency injection.

        Args:
            database: MongoDB Database instance. If None, uses legacy global singleton.
            config: Settings instance. If None, loads from environment.
            ml_inference: MLInference instance. If None, creates new instance.
            stop_loss_inference: StopLossInference instance. If None, creates new instance.
            profit_target_inference: ProfitTargetInference instance. If None, creates new instance.
            report_writer: ReportWriter instance for logging. If None, uses legacy ReportSingleton.
        """
        # Store injected dependencies
        self.database = database
        self.config = config if config is not None else get_settings()
        self.report_writer = report_writer

        # Initialize analysis components
        self.technical_analyzer = TechnicalAnalyzer()
        self.ml_inference = ml_inference if ml_inference is not None else MLInference(database=database)
        self.stop_loss_inference = stop_loss_inference if stop_loss_inference is not None else StopLossInference(database=database)
        self.profit_target_inference = profit_target_inference if profit_target_inference is not None else ProfitTargetInference(database=database)

        # Create ScoreManager with injected database
        if database is not None:
            self.score_manager = ScoreManager(database=database)
        else:
            # Backward compatibility - create temporary score manager
            from bluehorseshoe.core.container import create_app_container
            _temp_container = create_app_container()
            self.score_manager = ScoreManager(database=_temp_container.get_database())

    def _write_report(self, content: str) -> None:
        """
        Write to report using injected writer or fallback to singleton.

        Args:
            content: Content to write to the report
        """
        if self.report_writer is not None:
            self.report_writer.write(content)
        else:
            # Backward compatibility - use singleton
            ReportSingleton().write(content)

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
        atr = df['ATR'].values[-1]
        if pd.isna(atr):
            return df['close'].values[-1] * 0.02
        return float(atr)

    @staticmethod
    def _classify_signal_strength(score: float) -> str:
        """
        Classify technical score into strength tier.

        Args:
            score: Technical score (typically 0-100+)

        Returns:
            Signal strength classification: EXTREME, HIGH, MEDIUM, LOW, or WEAK
        """
        thresholds = SIGNAL_STRENGTH_THRESHOLDS
        if score >= thresholds['EXTREME']:
            return 'EXTREME'
        elif score >= thresholds['HIGH']:
            return 'HIGH'
        elif score >= thresholds['MEDIUM']:
            return 'MEDIUM'
        elif score >= thresholds['LOW']:
            return 'LOW'
        else:
            return 'WEAK'

    @staticmethod
    def _get_dynamic_atr_discount(technical_score: float) -> float:
        """
        Calculate dynamic ATR discount based on signal strength.

        Args:
            technical_score: Technical score (0-100+)

        Returns:
            ATR multiplier (0.05 - 0.50) for entry calculation
        """
        if not ENABLE_DYNAMIC_ENTRY:
            return 0.20  # Revert to original default

        signal_class = SwingTrader._classify_signal_strength(technical_score)
        return ENTRY_DISCOUNT_BY_SIGNAL.get(signal_class, 0.20)

    def _determine_baseline_entry(
        self,
        last_row: pd.Series,
        ema9: float,
        atr: float,
        technical_score: float = 0.0
    ) -> tuple[float, float, str]:
        """
        Determine entry price using dynamic ATR discount based on signal strength.

        Args:
            last_row: Latest price data
            ema9: 9-period EMA (kept for compatibility, not currently used)
            atr: Average True Range
            technical_score: Technical score for signal quality (default 0.0 for backward compat)

        Returns:
            Tuple of (entry_price, atr_discount_used, signal_strength)
        """
        last_close = last_row['close']

        # Get dynamic ATR discount based on signal strength
        atr_discount = self._get_dynamic_atr_discount(technical_score)
        signal_strength = self._classify_signal_strength(technical_score)

        # Calculate entry price
        entry_price = last_close - (atr_discount * atr)

        return entry_price, atr_discount, signal_strength

    def calculate_baseline_setup(self, df: pd.DataFrame, ml_stop_multiplier: float = 2.0, ml_profit_multiplier: float = 3.0) -> Dict[str, float]:
        """
        Calculate structural prices for Baseline (Trend) strategy:
        Entry = Pullback to EMA + Bullish candle close
        Stop = Below recent swing low or ml_stop_multiplier * ATR
        Target = Prior high or ml_profit_multiplier * ATR
        """
        last_row = df.iloc[-1]
        last_close = last_row['close']

        # 1. Indicators
        ema9 = df['close'].ewm(span=9).mean().iloc[-1]
        atr = self._calculate_atr(df)

        # 2. Structural levels
        swing_low_5 = df['low'].rolling(window=5).min().iloc[-1]
        swing_high_20 = df['high'].rolling(window=20).max().iloc[-1]

        # 3. Entry Logic (using default score=0 which gives MEDIUM/0.20 discount)
        entry_price, _, _ = self._determine_baseline_entry(last_row, ema9, atr, technical_score=0.0)

        # 4. Stop Loss & Take Profit
        atr_stop = entry_price - (ml_stop_multiplier * atr)
        swing_stop = swing_low_5 * 0.985

        # Default to safest stop (widest)
        stop_loss = min(swing_stop, atr_stop)

        take_profit = max(swing_high_20, entry_price + (ml_profit_multiplier * atr))

        # 5. Risk Calculation
        risk = entry_price - stop_loss
        reward = take_profit - entry_price
        rr_ratio = reward / risk if risk > 0 else 0

        # Smart Stop Logic: If structural stop is too wide (killing RR), try ATR stop
        if rr_ratio < MIN_RR_RATIO_BASELINE and stop_loss == swing_stop:
            # Check if tightening to ATR stop saves the trade
            risk_atr = entry_price - atr_stop
            rr_atr = reward / risk_atr if risk_atr > 0 else 0

            if rr_atr >= MIN_RR_RATIO_BASELINE:
                stop_loss = atr_stop
                rr_ratio = rr_atr
                # print(f"DEBUG: {last_row.get('symbol')} Tightened stop to ATR to save RR ({rr_ratio:.2f})")

        # Debugging
        # if rr_ratio < 0.5:
        #    print(
        #        f"DEBUG: {last_row.get('symbol', 'UNK')} RR Debug: entry={entry_price:.2f}, "
        #        f"stop={stop_loss:.2f}, exit={take_profit:.2f}, atr={atr:.2f}, "
        #        f"mult={ml_stop_multiplier:.2f}, rr={rr_ratio:.2f}"
        #    )

        # 6. Quality Check & Return
        avg_volume = last_row.get('avg_volume_20', 1)
        risk_pct = (entry_price - stop_loss) / entry_price if entry_price > 0 else 0

        return {
            'entry_price': float(entry_price),
            'stop_loss': float(stop_loss),
            'take_profit': float(take_profit),
            'rr_ratio': float(rr_ratio),
            'vol_ratio': float(last_row['volume'] / avg_volume if avg_volume > 0 else 0),
            'is_realistic': (abs((last_close / entry_price) - 1) <= 0.15) and (risk_pct <= MAX_RISK_PERCENT)
        }

    def calculate_mean_reversion_setup(self, df: pd.DataFrame, ml_stop_multiplier: float = 1.5, ml_profit_multiplier: float = 2.0) -> Dict[str, float]:
        """
        Calculate structural prices for Mean Reversion (Dip) strategy:
        Entry = Current Close (Buying extreme weakness)
        Stop = ml_stop_multiplier * ATR (Tighter stop for fast reversals)
        Target = Reversion to 20-day EMA or ml_profit_multiplier * ATR
        """
        last_row = df.iloc[-1]
        last_close = last_row['close']

        # 1. EMA 20 for Target (The "Mean")
        ema20 = df['close'].ewm(span=20).mean().iloc[-1]

        # 2. Volatility (ATR) - reuse cached calculation
        atr = self._calculate_atr(df)

        # 3. Entry is current close
        entry_price = last_close

        # 4. Stop Loss: ml_stop_multiplier * ATR below entry
        stop_loss = entry_price - (ml_stop_multiplier * atr)

        # 5. Take Profit: EMA 20 or ml_profit_multiplier * ATR
        take_profit = max(ema20, entry_price + (ml_profit_multiplier * atr))

        # 6. Reward-to-Risk
        reward = take_profit - entry_price
        risk = entry_price - stop_loss
        rr_ratio = reward / risk if risk > 0 else 0
        risk_pct = risk / entry_price if entry_price > 0 else 0

        return {
            'entry_price': float(entry_price),
            'stop_loss': float(stop_loss),
            'take_profit': float(take_profit),
            'rr_ratio': float(rr_ratio),
            'vol_ratio': last_row['volume'] / last_row.get('avg_volume_20', 1) if last_row.get('avg_volume_20', 0) > 0 else 0,
            'is_realistic': risk_pct <= MAX_RISK_PERCENT
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
        price_data = load_historical_data(symbol, database=self.database, score_manager_instance=self.score_manager)
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
        if not target_date and not self.config.holiday_mode:
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
        # UPDATED (Jan 2026): User requested to bypass this hard filter.
        # if ctx.market_health and ctx.market_health['status'] == 'Bearish':
        #    return None

        # Dynamic Regime Filtering:
        # In Bear/Neutral markets, we MUST have a Weekly Uptrend to avoid "bull traps".
        # In strong Bull markets, we can relax this to capture early reversals or strong daily momentum.
        should_enforce_weekly = REQUIRE_WEEKLY_UPTREND
        if ctx.market_health and ctx.market_health['status'] == 'Bullish':
            should_enforce_weekly = False

        is_uptrend = self.is_weekly_uptrend(df)
        if should_enforce_weekly and not is_uptrend:
            # print(f"DEBUG: {symbol} - Baseline failed weekly uptrend")
            return None

        # *** STEP 1: Calculate score FIRST ***
        score_components = self.technical_analyzer.calculate_baseline_score(
            df,
            enabled_indicators=ctx.enabled_indicators,
            aggregation=ctx.aggregation
        )
        technical_score = score_components.get("total", 0.0)

        # *** STEP 2: Get dynamic entry parameters ***
        last_row = df.iloc[-1]
        ema9 = df['close'].ewm(span=9).mean().iloc[-1]
        atr = self._calculate_atr(df)

        entry_price, atr_discount_used, signal_strength = self._determine_baseline_entry(
            last_row, ema9, atr, technical_score
        )

        # *** STEP 3: Predict ML profit target multiplier ***
        ml_profit_multiplier = self.profit_target_inference.predict_profit_target_multiplier(
            symbol,
            score_components,
            target_date=str(yesterday['date'])[:10],
            strategy="baseline"
        )

        # *** STEP 4: Calculate baseline setup with ML stop & profit ***
        ml_stop_multiplier = 2.0
        baseline_setup = self.calculate_baseline_setup(df, ml_stop_multiplier=ml_stop_multiplier, ml_profit_multiplier=ml_profit_multiplier)

        # *** STEP 5: Override entry price with dynamic calculation ***
        baseline_setup['entry_price'] = entry_price

        # *** STEP 6: Recalculate risk/reward with new entry ***
        stop_loss = baseline_setup['stop_loss']
        take_profit = baseline_setup['take_profit']
        risk = entry_price - stop_loss
        reward = take_profit - entry_price
        baseline_setup['rr_ratio'] = reward / risk if risk > 0 else 0

        # Recalculate is_realistic with new entry
        last_close = last_row['close']
        risk_pct = (entry_price - stop_loss) / entry_price if entry_price > 0 else 0
        baseline_setup['is_realistic'] = (
            (abs((last_close / entry_price) - 1) <= 0.15) and
            (risk_pct <= MAX_RISK_PERCENT)
        )

        # *** STEP 7: Add new metadata fields ***
        baseline_setup['atr_discount_used'] = atr_discount_used
        baseline_setup['signal_strength'] = signal_strength
        baseline_setup['profit_multiplier'] = ml_profit_multiplier

        # Validation checks
        if not baseline_setup['is_realistic'] or baseline_setup['rr_ratio'] < MIN_RR_RATIO_BASELINE:
            # print(f"DEBUG: {symbol} - Baseline failed setup checks: realistic={baseline_setup['is_realistic']}, rr={baseline_setup['rr_ratio']}")
            return None

        entry_price = baseline_setup['entry_price']
        if not MIN_STOCK_PRICE < entry_price < MAX_STOCK_PRICE:
            print(f"DEBUG: {symbol} - Baseline price out of range: {entry_price}")
            return None

        # Apply Relative Strength (RS) Bonus
        rs_multiplier = weights_config.get_weights('momentum').get('RS_MULTIPLIER', 1.0)
        if ctx.benchmark_df is not None and rs_multiplier != 0.0:
            rs_ratio = self.calculate_relative_strength(df, ctx.benchmark_df)
            if rs_ratio > 1.10:
                rs_bonus = 5.0
            elif rs_ratio > 1.0:
                rs_bonus = 2.0
            else:
                rs_bonus = -2.0
            rs_bonus *= rs_multiplier
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
            "stop_multiplier": ml_stop_multiplier,
            "profit_multiplier": ml_profit_multiplier
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

        # Predict ML Profit Target Multiplier
        ml_profit_multiplier_mr = self.profit_target_inference.predict_profit_target_multiplier(
            symbol,
            score_components_mr,
            target_date=str(yesterday['date'])[:10],
            strategy="mean_reversion"
        )

        mr_setup = self.calculate_mean_reversion_setup(df, ml_stop_multiplier=ml_stop_multiplier_mr, ml_profit_multiplier=ml_profit_multiplier_mr)
        if not mr_setup['is_realistic'] or mr_setup['rr_ratio'] < MIN_RR_RATIO_MEAN_REVERSION:
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

        # Add profit multiplier to setup metadata
        mr_setup['profit_multiplier'] = ml_profit_multiplier_mr

        return {
            "score": score_components_mr.pop("total", 0.0),
            "components": score_components_mr,
            "setup": mr_setup,
            "ml_prob": ml_prob_mr,
            "stop_multiplier": ml_stop_multiplier_mr,
            "profit_multiplier": ml_profit_multiplier_mr
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
            'exchange': ctx.symbol_map.get(symbol, 'Unknown') if ctx.symbol_map else 'Unknown',
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
        benchmark_data = load_historical_data("SPY", database=self.database, score_manager_instance=self.score_manager)
        if benchmark_data and benchmark_data.get('days'):
            df = pd.DataFrame(benchmark_data['days'])
            if target_date:
                df['date'] = pd.to_datetime(df['date'])
                df = df[df['date'] <= pd.to_datetime(target_date)]
            return df
        return None

    def _execute_prediction_batch(self, symbols: List[str], ctx: StrategyContext, progress_callback=None) -> List[Dict]:
        """Execute parallel prediction for a batch of symbols."""
        max_workers = min(8, os.cpu_count() or 4)

        self._write_report(f"Yesterday was {'not ' if not self.config.holiday_mode else ''}a holiday.")
        if ctx.target_date:
            self._write_report(f"Predicting for historical date: {ctx.target_date}")
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
                    if progress_callback:
                        progress_callback(i, total, pct)

        return [r for r in results if r is not None]

    def _report_top_candidates(self, results, strategy_key, setup_key, title):
        sorted_results = sorted([r for r in results if r[strategy_key] > 0], key=lambda x: x[strategy_key], reverse=True)
        self._write_report(f'\n--- Top 5 {title} Candidates ---')
        for i in range(min(5, len(sorted_results))):
            res = sorted_results[i]
            setup = res[setup_key]
            prob_key = 'baseline_ml_prob' if 'baseline' in strategy_key else 'mr_ml_prob'
            self._write_report(
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
                        "components": r["baseline_components"],
                        "atr_discount_used": setup.get("atr_discount_used", 0.20),
                        "signal_strength": setup.get("signal_strength", "MEDIUM")
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

    def _get_previous_trading_date(self, current_date: str) -> Optional[str]:
        """Finds the trading date immediately preceding the current_date."""
        # Use SPY as proxy for market days
        data = self.database.historical_prices.find_one(
            {"symbol": "SPY"},
            {"days.date": 1}
        )
        if not data or 'days' not in data:
            return None
            
        dates = sorted([d['date'] for d in data['days']])
        
        prev_date = None
        for d in dates:
            if d < current_date:
                prev_date = d
            else:
                break
        return prev_date

    def get_previous_performance(self, target_date: str) -> Dict[str, Any]:
        """
        Evaluates the performance of the PREVIOUS day's top candidates on the target_date.
        """
        prev_date = self._get_previous_trading_date(target_date)
        if not prev_date:
            return {}
            
        # Get Scores for Prev Date
        baseline_scores = self.score_manager.get_scores(prev_date, strategy="baseline")
        mr_scores = self.score_manager.get_scores(prev_date, strategy="mean_reversion")
        
        # Filter Top 5 of each
        top_baseline = sorted(baseline_scores, key=lambda x: x['score'], reverse=True)[:5]
        top_mr = sorted(mr_scores, key=lambda x: x['score'], reverse=True)[:5]
        
        combined_candidates = top_baseline + top_mr
        results = []
        
        for cand in combined_candidates:
            symbol = cand['symbol']
            setup = cand.get('metadata', {})
            
            entry = setup.get('entry_price')
            stop = setup.get('stop_loss')
            target = setup.get('take_profit')
            
            if not entry:
                continue
                
            # Get Price Data for Target Date (Today)
            price_doc = self.database.historical_prices.find_one(
                {"symbol": symbol},
                {"days": {"$elemMatch": {"date": target_date}}}
            )
            
            if not price_doc or 'days' not in price_doc or not price_doc['days']:
                # Maybe data missing for this symbol?
                continue
                
            day_data = price_doc['days'][0]
            
            # Logic
            triggered = day_data['low'] <= entry
            
            outcome = "Pending"
            pnl_pct = 0.0
            
            if triggered:
                # Check Stop/Target
                if day_data['low'] <= stop:
                    outcome = "Stopped Out"
                    pnl_pct = (stop - entry) / entry
                elif day_data['high'] >= target:
                    outcome = "Target Hit"
                    pnl_pct = (target - entry) / entry
                else:
                    outcome = "Active"
                    pnl_pct = (day_data['close'] - entry) / entry
            else:
                outcome = "No Entry"
                
            results.append({
                "symbol": symbol,
                "strategy": cand.get('strategy', 'Unknown'),
                "entry": entry,
                "stop": stop,
                "target": target,
                "outcome": outcome,
                "pnl": pnl_pct,
                "close": day_data['close'],
                "high": day_data['high'],
                "low": day_data['low']
            })
            
        return {"date": prev_date, "results": results}

    def swing_predict(
        self,
        target_date: Optional[str] = None,
        enabled_indicators: Optional[list[str]] = None,
        aggregation: str = "sum",
        symbols: Optional[list[str]] = None,
        progress_callback=None
    ) -> Dict[str, Any]:
        """Main prediction function with parallel processing capability."""

        # 1. Market Context Filter
        market_health = MarketRegime.get_market_health(target_date=target_date, database=self.database)
        self._write_report(f"Market Status: {market_health['status']} ({market_health['multiplier']}x risk)")

        # 2. Setup Data
        benchmark_df = self._load_benchmark_data(target_date)
        if symbols is None:
            symbols = get_symbol_name_list(database=self.database)

        # Build symbol metadata map
        all_symbols = get_symbols_from_mongo(database=self.database)
        symbol_map = {s['symbol']: s.get('exchange', 'Unknown') for s in all_symbols}

        ctx = StrategyContext(
            target_date=target_date,
            enabled_indicators=enabled_indicators,
            aggregation=aggregation,
            benchmark_df=benchmark_df,
            market_health=market_health,
            symbol_map=symbol_map
        )

        # 3. Execute
        valid_results = self._execute_prediction_batch(symbols, ctx, progress_callback=progress_callback)

        # 4. Report & Collect Data
        # We print to console/txt via ReportSingleton inside these helpers
        self._report_top_candidates(valid_results, 'baseline_score', 'baseline_setup', 'Baseline (Trend)')
        self._report_top_candidates(valid_results, 'mr_score', 'mr_setup', 'Mean Reversion (Dip)')

        # 5. Save
        if valid_results:
            score_data = self._prepare_scores_for_save(valid_results)
            self.score_manager.save_scores(score_data)
            logging.info("Saved %d scores (Baseline & Mean Reversion) to trade_scores", len(score_data))

        # 6. Prepare Return Data for HTML Reporter
        candidates = []
        for r in valid_results:
            # Flatten results for the reporter
            if r['baseline_score'] > 0:
                setup = r['baseline_setup']
                candidates.append({
                    "symbol": r["symbol"],
                    "exchange": r.get("exchange", "Unknown"),
                    "strategy": "Baseline",
                    "score": r["baseline_score"],
                    "close": setup.get("entry_price", 0), # Approx
                    "stop_loss": setup.get("stop_loss", 0),
                    "target": setup.get("take_profit", 0),
                    "ml_prob": r.get("baseline_ml_prob", 0.0),
                    "reasons": [f"{k}={v:.1f}" for k, v in r['baseline_components'].items() if v != 0]
                })
            if r['mr_score'] > 0:
                setup = r['mr_setup']
                candidates.append({
                    "symbol": r["symbol"],
                    "exchange": r.get("exchange", "Unknown"),
                    "strategy": "MeanRev",
                    "score": r["mr_score"],
                    "close": setup.get("entry_price", 0),
                    "stop_loss": setup.get("stop_loss", 0),
                    "target": setup.get("take_profit", 0),
                    "ml_prob": r.get("mr_ml_prob", 0.0),
                    "reasons": [f"{k}={v:.1f}" for k, v in r['mr_components'].items() if v != 0]
                })

        # Sort by score desc
        candidates.sort(key=lambda x: x['score'], reverse=True)

        return {
            "regime": market_health,
            "candidates": candidates[:50], # Top 50 for the report
            "charts": [] # TODO: Add chart generation logic if needed
        }