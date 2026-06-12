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
import gc
import logging
import multiprocessing
import os
import concurrent.futures
from dataclasses import dataclass
from typing import Dict, Optional, List, Any

import numpy as np
import pandas as pd
from pymongo.database import Database
from ta.volatility import AverageTrueRange

from bluehorseshoe.analysis.constants import (
    MIN_STOCK_PRICE, MAX_STOCK_PRICE,
    ATR_WINDOW,
    MIN_RR_RATIO_BASELINE,
    MAX_RISK_PERCENT,
    SIGNAL_STRENGTH_THRESHOLDS,
    ENTRY_DISCOUNT_BY_SIGNAL,
    ENABLE_DYNAMIC_ENTRY
)
from bluehorseshoe.analysis.market_regime import MarketRegime
from bluehorseshoe.analysis.ml_overlay import MLInference
from bluehorseshoe.analysis.ml_profit_target import ProfitTargetInference
from bluehorseshoe.analysis.ml_stop_loss import StopLossInference
from bluehorseshoe.analysis.news_annotation import annotate_deepos_results as annotate_news_deepos_results
from bluehorseshoe.analysis.options_annotation import (
    annotate_deepos_results as annotate_options_deepos_results,
)
from bluehorseshoe.analysis.postprocess import CandidateAssembler, SentimentEnricher
from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer
from bluehorseshoe.core.config import Settings, get_settings, weights_config
from bluehorseshoe.core.scores import ScoreManager
from bluehorseshoe.core.service import get_latest_market_date
from bluehorseshoe.core.symbol_repository import get_overview, get_symbols
from bluehorseshoe.core.symbols import (
    get_symbol_name_list,
    get_sentiment_score,
)
from bluehorseshoe.analysis.ml_utils import build_ml_features
from bluehorseshoe.analysis.strategy_registry import get_all_strategies
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
    score_history: Optional[Dict[str, List[float]]] = None
    solvency: Optional[Dict[str, float]] = None

class SwingTrader:
    """Main class for swing trading analysis."""

    def __init__(
        self,
        database: Optional[Database] = None,
        config: Optional[Settings] = None,
        ml_inference: Optional[MLInference] = None,
        stop_loss_inference: Optional[StopLossInference] = None,
        profit_target_inference: Optional[ProfitTargetInference] = None,
        report_writer: Optional[ReportWriter] = None,
        store=None,
        strategies=None
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
            store: DuckDBStore for OHLCV data. If provided, used instead of MongoDB for reads.
            strategies: List of TradingStrategy objects. If None, uses all registered strategies.
        """
        # Store injected dependencies
        self.database = database
        self.store = store
        self.strategies = strategies if strategies is not None else get_all_strategies()
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

        # Create SignalJournal (non-fatal if unavailable)
        if database is not None:
            try:
                from bluehorseshoe.core.journal import SignalJournal  # pylint: disable=import-outside-toplevel
                self.signal_journal = SignalJournal(database=database)
            except Exception:  # pylint: disable=broad-exception-caught
                self.signal_journal = None
        else:
            self.signal_journal = None

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
        return atr

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

    def calculate_baseline_setup(self, df: pd.DataFrame, ml_stop_multiplier: float = 2.0, ml_target_multiplier: float = 3.0, technical_score: float = 0.0) -> Dict[str, float]:
        """
        Calculate structural prices for Baseline (Trend) strategy:
        Entry = Pullback to EMA + Bullish candle close
        Stop = Below recent swing low or ml_stop_multiplier * ATR
        Target = Prior high or ml_target_multiplier * ATR
        """
        last_row = df.iloc[-1]
        last_close = last_row['close']

        # 1. Indicators
        ema9 = df['close'].ewm(span=9).mean().iloc[-1]
        atr = self._calculate_atr(df)

        # 2. Structural levels
        swing_low_5 = df['low'].rolling(window=5).min().iloc[-1]

        # 3. Entry Logic (uses actual technical_score for dynamic ATR discount)
        entry_price, atr_discount_used, signal_strength = self._determine_baseline_entry(last_row, ema9, atr, technical_score=technical_score)

        # 4. Stop Loss & Take Profit
        atr_stop = entry_price - (ml_stop_multiplier * atr)
        swing_stop = swing_low_5 * 0.985

        # Default to safest stop (widest)
        stop_loss = min(swing_stop, atr_stop)

        atr_target = entry_price + (ml_target_multiplier * atr)
        take_profit = entry_price + (atr_target - entry_price) * 0.98

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
            'is_realistic': (abs((last_close / entry_price) - 1) <= 0.15) and (risk_pct <= MAX_RISK_PERCENT),
            'atr_discount_used': float(atr_discount_used),
            'signal_strength': signal_strength,
            'actual_close': float(last_close),
        }

    def calculate_mean_reversion_setup(self, df: pd.DataFrame, ml_stop_multiplier: float = 1.5, ml_target_multiplier: float = 2.0) -> Dict[str, float]:
        """
        Calculate structural prices for Mean Reversion (Dip) strategy:
        Entry = Current Close (Buying extreme weakness)
        Stop = ml_stop_multiplier * ATR (Tighter stop for fast reversals)
        Target = ml_target_multiplier * ATR with 2% delta haircut
        """
        last_row = df.iloc[-1]
        last_close = last_row['close']

        # 1. Volatility (ATR)
        atr = self._calculate_atr(df)

        # 2. Entry is current close
        entry_price = last_close

        # 3. Stop Loss: ml_stop_multiplier * ATR below entry
        stop_loss = entry_price - (ml_stop_multiplier * atr)

        # 4. Take Profit: ATR-based target with 2% delta haircut
        atr_target = entry_price + (ml_target_multiplier * atr)
        take_profit = entry_price + (atr_target - entry_price) * 0.98

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
            'is_realistic': risk_pct <= MAX_RISK_PERCENT,
            'actual_close': float(last_close),
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

    def process_symbol(self, symbol: str, ctx: StrategyContext) -> Optional[Dict]:
        """Process a single symbol and return its trading data."""
        # 1. Load and Validate Data
        data_result = self._load_and_validate_data(symbol, ctx.target_date)
        if not data_result:
            return None
        df, price_data, yesterday = data_result

        # 2. Process all registered strategies
        strategy_results = {}
        for strategy in self.strategies:
            result = strategy.process(self, df, symbol, yesterday, ctx)
            if result is not None:
                strategy_results[strategy.name] = result

        if not strategy_results:
            return None

        # 3. Connors RSI(2) flag — computed for ALL symbols with enough data
        connors_flag = False
        connors_rsi2 = None
        connors_sma200 = None
        if len(df) >= 200:
            import talib as ta
            rsi_2 = ta.RSI(df['close'].values, timeperiod=2)
            sma_200 = df['close'].rolling(200).mean()
            if not pd.isna(rsi_2[-1]) and not pd.isna(sma_200.iloc[-1]):
                connors_rsi2 = float(rsi_2[-1])
                connors_sma200 = float(sma_200.iloc[-1])
                connors_flag = bool(connors_rsi2 < 10 and df['close'].iloc[-1] > connors_sma200)

        # 4. Finalize Result — build backward-compatible dict using strategy keys
        rs_ratio = 1.0
        if ctx.benchmark_df is not None:
            rs_ratio = self.calculate_relative_strength(df, ctx.benchmark_df)

        cloud_flags = compute_cloud_dislocation_flags(df)

        ret_val = {
            'symbol': symbol,
            'name': price_data.get('full_name', symbol),
            'exchange': ctx.symbol_map.get(symbol, 'Unknown') if ctx.symbol_map else 'Unknown',
            'date': str(yesterday['date']),
            'rs_ratio': rs_ratio,
            'connors_flag': connors_flag,
            'connors_rsi2': connors_rsi2,
            'connors_sma200': connors_sma200,
            **cloud_flags,
        }

        for strategy in self.strategies:
            sr = strategy_results.get(strategy.name)
            ret_val[strategy.score_key] = sr.score if sr else 0.0
            ret_val[strategy.components_key] = sr.components if sr else {}
            ret_val[strategy.setup_key] = sr.setup if sr else {}
            ret_val[strategy.ml_prob_key] = sr.ml_prob if sr else 0.0
            if sr:
                ret_val['stop_multiplier'] = sr.stop_multiplier
                ret_val['target_multiplier'] = sr.target_multiplier

        score_parts = " | ".join(
            f"{s.display_name}: {ret_val.get(s.score_key, 0):.2f}"
            for s in self.strategies
        )
        logging.info("Processed %s with results %s", symbol, score_parts)
        return ret_val
    def _load_benchmark_data(self, target_date: Optional[str]) -> Optional[pd.DataFrame]:
        benchmark_data = load_historical_data("SPY", database=self.database, score_manager_instance=self.score_manager, store=self.store)
        if benchmark_data and benchmark_data.get('days'):
            df = pd.DataFrame(benchmark_data['days'])
            if target_date:
                df['date'] = pd.to_datetime(df['date'])
                df = df[df['date'] <= pd.to_datetime(target_date)]
            return df
        return None

    def _fetch_recent_scores(self, target_date: str, lookback_days: int = 5) -> Dict[str, List[float]]:
        """
        Fetch recent baseline scores from MongoDB for score acceleration calculation.

        Args:
            target_date: Current target date (scores before this date are fetched)
            lookback_days: Number of recent trading days to fetch

        Returns:
            Dict mapping symbol to list of scores ordered oldest→newest
        """
        try:
            # Get distinct dates before target_date, sorted descending, limited to lookback_days
            pipeline = [
                {"$match": {"strategy": "baseline", "date": {"$lt": target_date}}},
                {"$group": {"_id": "$date"}},
                {"$sort": {"_id": -1}},
                {"$limit": lookback_days},
            ]
            date_docs = list(self.score_manager.collection.aggregate(pipeline))
            if not date_docs:
                return {}

            recent_dates = sorted([d["_id"] for d in date_docs])  # oldest→newest

            # Batch-fetch all baseline scores for these dates
            cursor = self.score_manager.collection.find(
                {"strategy": "baseline", "date": {"$in": recent_dates}},
                {"symbol": 1, "date": 1, "score": 1, "_id": 0},
            )

            # Build {symbol: {date: score}} then flatten to ordered list
            symbol_date_scores: Dict[str, Dict[str, float]] = {}
            for doc in cursor:
                sym = doc["symbol"]
                if sym not in symbol_date_scores:
                    symbol_date_scores[sym] = {}
                symbol_date_scores[sym][doc["date"]] = doc["score"]

            # Convert to ordered list (oldest→newest)
            result: Dict[str, List[float]] = {}
            for sym, date_map in symbol_date_scores.items():
                scores = [date_map[d] for d in recent_dates if d in date_map]
                if len(scores) >= 2:
                    result[sym] = scores

            return result
        except Exception as e:  # pylint: disable=broad-exception-caught
            logging.warning("Failed to fetch recent scores for acceleration: %s", e)
            return {}

    @staticmethod
    def _calculate_score_acceleration(scores: List[float]) -> float:
        """
        Calculate score acceleration bonus from a list of recent scores (oldest→newest).

        Returns:
            Bonus value:
              +3.0 for 3+ strictly ascending scores
              +2.0 for positive slope with R² > 0.5
              +1.0 for positive slope with R² ≤ 0.5
               0.0 for flat or insufficient data
              -1.0 for negative slope
        """
        if len(scores) < 2:
            return 0.0

        # Check for 3+ strictly ascending
        if len(scores) >= 3:
            is_ascending = all(scores[i] < scores[i + 1] for i in range(len(scores) - 1))
            if is_ascending:
                return 3.0

        # Linear regression: slope and R²
        x = np.arange(len(scores), dtype=float)
        y = np.array(scores, dtype=float)
        coeffs = np.polyfit(x, y, 1)
        slope = coeffs[0]

        if slope <= 0:
            return -1.0

        # Calculate R²
        y_pred = np.polyval(coeffs, x)
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        if r_squared > 0.5:
            return 2.0
        return 1.0

    def _preload_symbol_data(self, symbol: str, target_date: Optional[str]) -> Optional[Dict]:
        """
        Load all data needed for scoring from the database.
        Returns a picklable dict or None if the symbol should be skipped.

        Called from Phase 1 (ThreadPoolExecutor in the main process).
        Loads: historical OHLCV, company overview, sentiment score.
        """
        # 1. Load historical data (DuckDB → MongoDB → file → net)
        price_data = load_historical_data(symbol, database=self.database, score_manager_instance=self.score_manager, store=self.store)
        if price_data is None or not price_data.get('days'):
            logging.error("Failed to load historical data for %s.", symbol)
            return None

        df = pd.DataFrame(price_data['days'])

        # 2. Filter to target date if specified
        if target_date:
            df['date'] = pd.to_datetime(df['date'])
            target_ts = pd.to_datetime(target_date)
            df = df[df['date'] <= target_ts]

            if not df.empty:
                last_date = pd.to_datetime(df.iloc[-1]['date'])
                if (target_ts - last_date).days > 7:
                    logging.info("Symbol %s data too stale for %s. Skipping.", symbol, target_date)
                    return None

        # 3. Validate minimum data
        if df.empty or len(df) < 30:
            logging.info("Symbol %s has insufficient data (%d days). Skipping.", symbol, len(df))
            return None

        # 4. Freshness check (non-historical mode)
        yesterday = dict(df.iloc[-1])
        if not target_date and not self.config.holiday_mode:
            last_trading_day = pd.Timestamp.now().normalize() - pd.offsets.BDay(1)
            yesterday_date = pd.to_datetime(yesterday['date'])
            if yesterday_date != last_trading_day:
                logging.error("Data for %s on '%s' is not '%s'.", symbol, yesterday_date, last_trading_day)
                with open('src/error_symbols.txt', 'a', encoding='utf-8') as f:
                    f.write(f"{symbol}\n")
                return None

        # 5. Load fundamental overview (for ML features)
        overview = get_overview(symbol, database=self.database)

        # 6. Load sentiment score (for ML features)
        target_date_str = str(yesterday['date'])[:10]
        sentiment = get_sentiment_score(symbol, target_date_str, database=self.database)

        # 7. Return picklable dict (DataFrame → dict-of-lists for efficient serialization)
        return {
            'df_data': df.to_dict('list'),
            'full_name': price_data.get('full_name', symbol),
            'overview': overview or {},
            'sentiment': sentiment,
        }

    def _execute_prediction_batch(self, symbols: List[str], ctx: StrategyContext, progress_callback=None) -> List[Dict]:
        """
        Execute prediction in chunked phases for true CPU parallelism:
        - ProcessPoolExecutor created once (workers persist across chunks)
        - For each chunk: Phase 1 (I/O preload) → Phase 2 (CPU scoring)
        Chunking prevents OOM by limiting how much preloaded data is in memory.
        """
        io_workers = min(4, os.cpu_count() or 4)
        cpu_workers = max(1, min(os.cpu_count() or 2, 2))  # Cap at 2 for 4GB container
        chunk_size = 200

        self._write_report(f"Yesterday was {'not ' if not self.config.holiday_mode else ''}a holiday.")
        if ctx.target_date:
            self._write_report(f"Predicting for historical date: {ctx.target_date}")
        logging.info("Processing %d symbols (I/O: %d threads, CPU: %d processes, chunk: %d)...",
                     len(symbols), io_workers, cpu_workers, chunk_size)

        # Fetch recent score history for acceleration indicator
        score_history = {}
        accel_multiplier = weights_config.get_weights('trend').get('SCORE_ACCEL_MULTIPLIER', 0.0)
        if accel_multiplier != 0.0 and ctx.target_date:
            score_history = self._fetch_recent_scores(ctx.target_date, lookback_days=5)
        ctx.score_history = score_history

        # Load motif catalog scores for CurveIndicator
        from bluehorseshoe.analysis.curves.motif_lookup import load_motif_scores_for_workers  # pylint: disable=import-outside-toplevel
        motif_scores = load_motif_scores_for_workers(self.database)

        # Shared context passed via initializer (same for all chunks)
        shared_ctx = {
            'benchmark_data': ctx.benchmark_df.to_dict('list') if ctx.benchmark_df is not None else None,
            'market_health': ctx.market_health,
            'enabled_indicators': ctx.enabled_indicators,
            'aggregation': ctx.aggregation,
            'score_history': score_history,
            'motif_scores': motif_scores,
            'solvency': ctx.solvency or {},
        }

        # ML model paths
        overlay_paths = {
            'general': 'src/models/ml_overlay_v1.joblib',
            'baseline': 'src/models/ml_overlay_baseline.joblib',
            'mean_reversion': 'src/models/ml_overlay_mean_reversion.joblib',
        }
        stop_loss_path = 'src/models/ml_stop_loss_v1.joblib'
        profit_target_paths = {
            'general': 'src/models/ml_profit_target_v1.joblib',
            'baseline': 'src/models/ml_profit_target_baseline.joblib',
            'mean_reversion': 'src/models/ml_profit_target_mean_reversion.joblib',
        }

        all_results = []
        total_symbols = len(symbols)
        total_valid = 0
        total_scored = 0
        total_chunks = (total_symbols + chunk_size - 1) // chunk_size

        # Use 'fork' context for memory efficiency (copy-on-write sharing).
        # Workers never access MongoDB, so inherited connections are harmless.
        mp_ctx = multiprocessing.get_context('fork')
        pool_initargs = (overlay_paths, stop_loss_path, profit_target_paths, shared_ctx)

        # Recreate the pool every N chunks to release accumulated worker memory
        # (Python's allocator doesn't return freed pages to the OS)
        pool_refresh_interval = 3
        cpu_pool = None

        try:
            for chunk_idx, chunk_start in enumerate(range(0, total_symbols, chunk_size)):
                chunk_end = min(chunk_start + chunk_size, total_symbols)
                chunk_symbols = symbols[chunk_start:chunk_end]
                chunk_num = chunk_idx + 1

                # ===== PHASE 1: Pre-load chunk data (I/O-bound, threads) =====
                print(f"Chunk {chunk_num}/{total_chunks} - Phase 1: Loading {len(chunk_symbols)} symbols...", flush=True)
                symbol_data = {}
                with concurrent.futures.ThreadPoolExecutor(max_workers=io_workers) as io_pool:
                    futures = {
                        io_pool.submit(self._preload_symbol_data, sym, ctx.target_date): sym
                        for sym in chunk_symbols
                    }
                    for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
                        sym = futures[future]
                        try:
                            result = future.result()
                            if result is not None:
                                symbol_data[sym] = result
                        except Exception as e:  # pylint: disable=broad-exception-caught
                            logging.error("Preload failed for %s: %s", sym, e)

                        if i % 200 == 0 or i == len(futures):
                            print(f"  Phase 1: {i}/{len(futures)} loaded ({len(symbol_data)} valid)", flush=True)

                total_valid += len(symbol_data)

                if not symbol_data:
                    total_scored += len(chunk_symbols)
                    continue

                # Build per-symbol work items
                work_items = []
                for sym, data in symbol_data.items():
                    work_items.append({
                        'symbol': sym,
                        'df_data': data['df_data'],
                        'overview': data['overview'],
                        'sentiment': data['sentiment'],
                        'full_name': data['full_name'],
                        'exchange': ctx.symbol_map.get(sym, 'Unknown') if ctx.symbol_map else 'Unknown',
                    })

                # Free preloaded data before scoring (work_items has its own copy)
                del symbol_data

                # Refresh pool periodically to release accumulated worker memory
                if cpu_pool is None or chunk_idx % pool_refresh_interval == 0:
                    if cpu_pool is not None:
                        cpu_pool.shutdown(wait=True)
                        gc.collect()
                    cpu_pool = concurrent.futures.ProcessPoolExecutor(
                        max_workers=cpu_workers,
                        mp_context=mp_ctx,
                        initializer=_init_worker,
                        initargs=pool_initargs,
                    )

                # ===== PHASE 2: CPU scoring =====
                print(f"Chunk {chunk_num}/{total_chunks} - Phase 2: Scoring {len(work_items)} symbols...", flush=True)

                chunk_total = len(work_items)
                for i, result in enumerate(cpu_pool.map(_score_symbol_worker, work_items, chunksize=50), 1):
                    if result is not None:
                        all_results.append(result)

                    total_scored += 1
                    if i % 50 == 0 or i == chunk_total:
                        overall_pct = (total_scored / total_symbols) * 100
                        print(f"  Phase 2: {i}/{chunk_total} scored | Overall: {total_scored}/{total_symbols} ({overall_pct:.1f}%)", flush=True)
                        if progress_callback:
                            progress_callback(total_scored, total_symbols, overall_pct)

                # Free work items after scoring and reclaim memory
                del work_items
                gc.collect()
        finally:
            if cpu_pool is not None:
                cpu_pool.shutdown(wait=True)

        logging.info("Complete: %d candidates from %d valid symbols (%d total)",
                     len(all_results), total_valid, total_symbols)
        return all_results

    def _report_top_candidates(self, results, strategy_key, setup_key, title, ml_prob_key=None):
        sorted_results = sorted([r for r in results if r[strategy_key] > 0], key=lambda x: x[strategy_key], reverse=True)
        self._write_report(f'\n--- Top 5 {title} Candidates ---')
        if ml_prob_key is None:
            ml_prob_key = 'baseline_ml_prob' if 'baseline' in strategy_key else 'mr_ml_prob'
        for i in range(min(5, len(sorted_results))):
            res = sorted_results[i]
            setup = res[setup_key]
            self._write_report(
                f"{res['symbol']} - Entry: {setup['entry_price']:.2f} | "
                f"Stop: {setup['stop_loss']:.2f} (SL Mult: {res.get('stop_multiplier', 0):.1f}) | "
                f"Exit: {setup['take_profit']:.2f} (TP Mult: {res.get('target_multiplier', 0):.1f}) | "
                f"Score: {res[strategy_key]:.2f} | ML Win%: {res[ml_prob_key]*100:.1f}% - Name: {res['name']}"
            )

    def _prepare_scores_for_save(self, valid_results) -> List[Dict]:
        score_data = []
        for r in valid_results:
            for strat in self.strategies:
                score = r.get(strat.score_key, 0)
                if score > 0:
                    setup = r.get(strat.setup_key, {})
                    score_data.append({
                        "symbol": r["symbol"],
                        "date": r["date"][:10],
                        "score": score,
                        "strategy": strat.name,
                        "version": "1.6",
                        "metadata": {
                            "entry_price": setup.get("entry_price", 0),
                            "stop_loss": setup.get("stop_loss", 0),
                            "take_profit": setup.get("take_profit", 0),
                            "actual_close": setup.get("actual_close", 0),
                            "ml_win_prob": r.get(strat.ml_prob_key, 0.0),
                            "stop_multiplier": r.get("stop_multiplier", strat.default_stop_multiplier),
                            "target_multiplier": r.get("target_multiplier", strat.default_target_multiplier),
                            "components": r.get(strat.components_key, {}),
                            "atr_discount_used": setup.get("atr_discount_used", 0.0),
                            "signal_strength": setup.get("signal_strength", "MEDIUM"),
                            "connors_flag": r.get("connors_flag", False),
                            "connors_rsi2": r.get("connors_rsi2"),
                            "connors_sma200": r.get("connors_sma200"),
                            "cloud_age": r.get("cloud_age", 0),
                            "confluence_star": r.get("confluence_star", False),
                            "chronic_dislocation": r.get("chronic_dislocation", False),
                            "sentiment": r.get("sentiment", 0.0),
                            "sentiment_tiingo": r.get("sentiment_tiingo", 0.0),
                            "sentiment_stocktwits": r.get("sentiment_stocktwits", 0.0),
                            "sentiment_finviz": r.get("sentiment_finviz", 0.0),
                        }
                    })
        return score_data

    def _enrich_with_intraday(self, candidates: List[dict]) -> List[dict]:
        """Fetch 5-min bars for top candidates and compute intraday confirmation."""
        from bluehorseshoe.analysis.intraday_context import compute_intraday_confirmation

        for candidate in candidates[:20]:
            symbol = candidate.get("symbol", "")
            resistance = candidate.get("intraday_resistance")
            if not symbol or not resistance:
                continue
            try:
                import requests as req

                url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
                params = {"range": "1d", "interval": "5m"}
                headers = {"User-Agent": "Mozilla/5.0"}
                resp = req.get(url, params=params, headers=headers, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                result = data["chart"]["result"][0]
                timestamps = result["timestamp"]
                quote = result["indicators"]["quote"][0]
                df = pd.DataFrame({
                    "datetime": pd.to_datetime(timestamps, unit="s"),
                    "open": quote["open"],
                    "high": quote["high"],
                    "low": quote["low"],
                    "close": quote["close"],
                    "volume": [v if v is not None else 1 for v in quote["volume"]],
                })
                df = df.dropna(subset=["open", "high", "low", "close"])
                if len(df) >= 10:
                    candidate["intraday_confirmation"] = compute_intraday_confirmation(df, resistance)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logging.debug("Intraday confirmation skipped for %s: %s", symbol, exc)
        return candidates

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
        solvency = {}
        if self.store is not None:
            asof_date = (
                target_date
                or (self.store.get_latest_date() if hasattr(self.store, "get_latest_date") else None)
            )
            if asof_date and hasattr(self.store, "load_solvency_asof"):
                solvency = self.store.load_solvency_asof(str(asof_date)[:10])
        if symbols is None:
            symbols = get_symbol_name_list(database=self.database, active_only=True)

        # Filter to symbols with market cap data (excludes ETFs, warrants, SPACs, shells)
        mcap_symbols = {
            d['symbol'] for d in self.database['symbol_overviews'].find(
                {'MarketCapitalization': {'$exists': True, '$nin': [None, '', '0', 'None']}},
                {'symbol': 1, '_id': 0}
            )
        }
        before = len(symbols)
        symbols = [s for s in symbols if s in mcap_symbols]
        logging.info("Market-cap filter: %d → %d symbols (%d skipped)", before, len(symbols), before - len(symbols))

        # Build symbol metadata map
        all_symbols = get_symbols(database=self.database)
        symbol_map = {s['symbol']: s.get('exchange', 'Unknown') for s in all_symbols}

        ctx = StrategyContext(
            target_date=target_date,
            enabled_indicators=enabled_indicators,
            aggregation=aggregation,
            benchmark_df=benchmark_df,
            market_health=market_health,
            symbol_map=symbol_map,
            solvency=solvency,
        )

        # 3. Execute
        valid_results = self._execute_prediction_batch(symbols, ctx, progress_callback=progress_callback)

        # 4. Report & Collect Data
        # We print to console/txt via ReportSingleton inside these helpers.
        # Only live (paper_tradeable) sleeves get a "Top 5" on the human surface:
        # untraded Baseline/MeanRev rankings anti-select (entry-signal alpha
        # absent) and ADX-Down is tracking-only. Their scores still compute and
        # persist below for backtests/research — they just don't get a trade list.
        _strategy_titles = {"deep_oversold": "Deep Oversold (Persistent Dip)"}
        for strat in self.strategies:
            if not strat.paper_tradeable:
                continue
            title = _strategy_titles.get(strat.name, strat.display_name)
            self._report_top_candidates(
                valid_results, strat.score_key, strat.setup_key, title,
                ml_prob_key=strat.ml_prob_key,
            )

        # 5. Save
        if valid_results:
            score_data = self._prepare_scores_for_save(valid_results)
            self.score_manager.save_scores(score_data)
            logging.info("Saved %d scores (%d strategies) to trade_scores",
                         len(score_data), len(self.strategies))

        candidate_assembler = CandidateAssembler(self.strategies)
        top_candidates = candidate_assembler.build_top_candidates(valid_results)
        top_candidates = self._enrich_with_intraday(top_candidates)

        is_live = self._is_live_target_date(ctx.target_date)

        # 5a-2. Tracking-only news annotation on DeepOS-family fires (live runs only:
        # current news stamped onto historical fires would poison the forward record).
        # Must run BEFORE the journal freeze so the arms land in journal_signals.
        if is_live and valid_results:
            try:
                annotate_news_deepos_results(
                    valid_results,
                    target_date=valid_results[0]["date"][:10],
                    database=self.database,
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logging.error("News annotation failed (non-fatal): %s", exc)
            try:
                annotate_options_deepos_results(
                    valid_results,
                    target_date=valid_results[0]["date"][:10],
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logging.error("Options annotation failed (non-fatal): %s", exc)

        # 5b. Freeze Signal Journal (immutable record)
        if self.signal_journal is not None and valid_results:
            try:
                self.signal_journal.freeze_batch(
                    batch_date=valid_results[0]["date"][:10],
                    valid_results=valid_results,
                    market_health=market_health,
                    symbol_count=len(symbols),
                    paper_settings={
                        "paper_trading_enabled": self.config.paper_trading_enabled,
                        "paper_total_investment": self.config.paper_total_investment,
                        "paper_max_positions": self.config.paper_max_positions,
                    },
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logging.error("SignalJournal freeze failed (non-fatal): %s", exc)

        sentiment_enricher = SentimentEnricher(self.database)
        top_candidates = sentiment_enricher.enrich(
            top_candidates,
            target_date=ctx.target_date,
            market_health=market_health,
            is_live=is_live,
        )

        self._annotate_planned_sizing(top_candidates)

        return {
            "regime": market_health,
            "candidates": top_candidates,
            "charts": [] # TODO: Add chart generation logic if needed
        }

    def _is_live_target_date(self, target_date: Optional[str]) -> bool:
        """True when this prediction runs against the latest market date.

        Gates sentiment-snapshot archiving: live feeds describe *now*, so persisting
        them under a historical target date poisons the point-in-time archive (the
        pre-2026-04 contamination). Fails closed - if the latest market date cannot
        be resolved, the run is treated as historical and nothing is archived.
        """
        if target_date is None:
            return True
        try:
            latest = get_latest_market_date(database=self.database, store=self.store)
        except Exception as exc:  # pylint: disable=broad-except
            logging.warning(
                "Could not resolve latest market date (%s); treating run as historical "
                "for sentiment snapshot archiving", exc,
            )
            return False
        if not latest:
            logging.warning(
                "Latest market date unavailable; treating run as historical "
                "for sentiment snapshot archiving",
            )
            return False
        return str(target_date)[:10] == str(latest)[:10]

    def _annotate_planned_sizing(self, candidates: list[dict]) -> None:
        """Tag candidates with the bot's intended FRACTIONAL position size for the report.

        The report shows the unfloored ideal (`planned_shares`/`planned_dollars`); the
        live paper trader floors to whole shares at execution. Reuses the trader's real
        selection + conviction sizing (broker-free, empty-book assumption). Non-fatal.
        """
        try:
            from bluehorseshoe.trading.paper_trader import (  # pylint: disable=import-outside-toplevel
                PaperTrader, PaperTradeConfig,
            )
            cfg = PaperTradeConfig(
                total_investment=self.config.paper_total_investment,
                max_positions=self.config.paper_max_positions,
                slots_deep_oversold=self.config.paper_slots_deep_oversold,
                conviction_sizing=self.config.paper_conviction_sizing,
                max_position_mult=self.config.paper_max_position_mult,
            )
            plan = PaperTrader(ibkr_client=None, config=cfg,
                               database=None).preview_fractional_plan(candidates)
            for cand in candidates:
                sized = plan.get(id(cand))
                if sized:
                    cand['planned_shares'] = sized['shares']
                    cand['planned_dollars'] = sized['dollars']
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.warning("Planned-sizing annotation failed (non-fatal): %s", exc)


# =====================================================================
# ProcessPoolExecutor Worker Functions
# =====================================================================
# Module-level functions required by ProcessPoolExecutor (must be picklable).
# These run in separate processes without access to the main process's
# database connections. ML models are loaded once per worker via initializer.
# =====================================================================

_worker_state = {}  # Populated by _init_worker, one copy per worker process


def _init_worker(overlay_paths, stop_loss_path, profit_target_paths, shared_ctx):
    """
    Initializer for ProcessPoolExecutor workers.
    Called once per worker process to:
    1. Create a compute-only SwingTrader (no DB connections)
    2. Load ML models from disk
    3. Cache shared context (benchmark data, market health, etc.)
    """
    global _worker_state  # pylint: disable=global-statement
    import joblib  # pylint: disable=import-outside-toplevel

    # Create compute-only SwingTrader (bypass __init__ to avoid DB connections)
    trader = SwingTrader.__new__(SwingTrader)
    trader.technical_analyzer = TechnicalAnalyzer()
    trader.strategies = get_all_strategies()

    # Reconstruct benchmark DataFrame from dict-of-lists
    benchmark_data = shared_ctx.get('benchmark_data')

    _worker_state = {
        'trader': trader,
        'strategies': trader.strategies,
        'benchmark_df': pd.DataFrame(benchmark_data) if benchmark_data else None,
        'market_health': shared_ctx.get('market_health'),
        'enabled_indicators': shared_ctx.get('enabled_indicators'),
        'aggregation': shared_ctx.get('aggregation', 'sum'),
        'score_history': shared_ctx.get('score_history', {}),
        'motif_scores': shared_ctx.get('motif_scores', {}),
        'solvency': shared_ctx.get('solvency', {}),
        'ml_overlay': {'models': {}, 'encoders': {}, 'features': {}},
        'ml_stop_loss': {'model': None, 'encoders': {}, 'features': []},
        'ml_profit_target': {'models': {}, 'encoders': {}, 'features': {}},
    }

    # Load ML overlay models (general + strategy-specific)
    for key, path in overlay_paths.items():
        if path and os.path.exists(path):
            try:
                data = joblib.load(path)
                _worker_state['ml_overlay']['models'][key] = data['model']
                _worker_state['ml_overlay']['encoders'][key] = data.get('encoders', {})
                _worker_state['ml_overlay']['features'][key] = data.get('features', [])
            except Exception as e:  # pylint: disable=broad-exception-caught
                logging.warning("Worker: failed to load ML overlay %s: %s", path, e)

    # Load ML stop loss model
    if stop_loss_path and os.path.exists(stop_loss_path):
        try:
            data = joblib.load(stop_loss_path)
            _worker_state['ml_stop_loss']['model'] = data['model']
            _worker_state['ml_stop_loss']['encoders'] = data.get('encoders', {})
            _worker_state['ml_stop_loss']['features'] = data.get('features', [])
        except Exception as e:  # pylint: disable=broad-exception-caught
            logging.warning("Worker: failed to load ML stop loss %s: %s", stop_loss_path, e)

    # Load ML profit target models (general + strategy-specific)
    for key, path in profit_target_paths.items():
        if path and os.path.exists(path):
            try:
                data = joblib.load(path)
                _worker_state['ml_profit_target']['models'][key] = data['model']
                _worker_state['ml_profit_target']['encoders'][key] = data.get('encoders', {})
                _worker_state['ml_profit_target']['features'][key] = data.get('features', [])
            except Exception as e:  # pylint: disable=broad-exception-caught
                logging.warning("Worker: failed to load ML profit target %s: %s", path, e)


def _worker_ml_predict_probability(components, overview, sentiment, strategy="general"):
    """Predict win probability using pre-loaded ML models. No DB access."""
    ml = _worker_state.get('ml_overlay', {})
    model_key = strategy if strategy in ml.get('models', {}) else "general"
    model = ml.get('models', {}).get(model_key)
    if model is None:
        return 0.0

    # Build features from pre-loaded data (no DB queries)
    feat = build_ml_features(components, overview, sentiment)

    # Encode categorical features
    encoders = ml.get('encoders', {}).get(model_key, {})
    for col in ['Sector', 'Industry']:
        le = encoders.get(col)
        val = str(feat.get(col, 'Unknown'))
        if le:
            try:
                feat[col] = le.transform([val])[0]
            except ValueError:
                feat[col] = 0
        else:
            feat[col] = 0

    # Prepare inference DataFrame aligned with model's training features
    df_inf = pd.DataFrame([feat])
    model_features = ml.get('features', {}).get(model_key, [])
    for f in model_features:  # pylint: disable=invalid-name
        if f not in df_inf.columns:
            df_inf[f] = 0.0
    df_inf = df_inf[model_features].fillna(0)

    probs = model.predict_proba(df_inf)[0]
    return float(probs[1])


def _worker_ml_predict_stop_loss(components, overview, sentiment):
    """Predict stop loss ATR multiplier using pre-loaded ML models. No DB access."""
    sl = _worker_state.get('ml_stop_loss', {})
    model = sl.get('model')
    if model is None:
        return 2.0  # Default fallback

    # Build features from pre-loaded data (no DB queries)
    feat = build_ml_features(components, overview, sentiment)

    # Encode categorical features
    encoders = sl.get('encoders', {})
    for col in ['Sector', 'Industry']:
        le = encoders.get(col)
        val = str(feat.get(col, 'Unknown'))
        if le:
            try:
                feat[col] = le.transform([val])[0]
            except ValueError:
                feat[col] = 0
        else:
            feat[col] = 0

    # Prepare inference DataFrame
    df_inf = pd.DataFrame([feat])
    model_features = sl.get('features', [])
    for f in model_features:  # pylint: disable=invalid-name
        if f not in df_inf.columns:
            df_inf[f] = 0.0
    df_inf = df_inf[model_features].fillna(0)

    predicted_mae = float(model.predict(df_inf)[0])
    return max(1.5, predicted_mae + 0.5)


def _worker_ml_predict_profit_target(components, overview, sentiment, strategy="general"):
    """Predict profit target ATR multiplier using pre-loaded ML models. No DB access."""
    pt = _worker_state.get('ml_profit_target', {})
    model_key = strategy if strategy in pt.get('models', {}) else "general"
    model = pt.get('models', {}).get(model_key)

    # Fallback defaults per strategy
    fallback = 3.0 if strategy == "baseline" else 2.0
    if model is None:
        return fallback

    # Build features from pre-loaded data (no DB queries)
    feat = build_ml_features(components, overview, sentiment)

    # Encode categorical features
    encoders = pt.get('encoders', {}).get(model_key, {})
    for col in ['Sector', 'Industry']:
        le = encoders.get(col)
        val = str(feat.get(col, 'Unknown'))
        if le:
            try:
                feat[col] = le.transform([val])[0]
            except ValueError:
                feat[col] = 0
        else:
            feat[col] = 0

    # Prepare inference DataFrame
    df_inf = pd.DataFrame([feat])
    model_features = pt.get('features', {}).get(model_key, [])
    for f in model_features:  # pylint: disable=invalid-name
        if f not in df_inf.columns:
            df_inf[f] = 0.0
    df_inf = df_inf[model_features].fillna(0)

    predicted_mfe = float(model.predict(df_inf)[0])

    # Apply safety factor and clamp
    recommended_multiplier = predicted_mfe * 0.75
    return max(1.5, min(2.5, recommended_multiplier))


# Liquidity floor for the cloud-dislocation annotation: the research net-of-cost edge
# (research/indicator_screen/) held on names with >=$25M 20-day dollar-volume.
CLOUD_DISLOCATION_LIQ_MIN = 25_000_000.0


def compute_cloud_dislocation_flags(df) -> Dict:
    """Ichimoku cloud-dislocation annotation flags for the report (research-validated, advisory only).

    Cell = price stuck below the (displaced) Ichimoku cloud for >=26 consecutive bars. Split by RSI(14):
      confluence_star  : age>=26 AND rsi<30  (the super-additive 'recently slammed + chronically broken' cell)
      chronic_dislocation: age>=26 AND rsi>=30  (below_not_os & age26 — the RSI-orthogonal cell)
    Both gated to liquid names (>=$25M 20d dollar-volume), where the net-of-cost edge was validated.
    `cloud_age` (consecutive bars below cloud through the signal bar) is always reported for the tooltip.
    """
    out = {'cloud_age': 0, 'confluence_star': False, 'chronic_dislocation': False}
    if df is None or len(df) < 78:  # need 52-bar Span B + 26-bar forward displacement
        return out
    high, low, close = df['high'], df['low'], df['close']
    tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
    kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
    bottom = pd.concat([span_a, span_b], axis=1).min(axis=1)
    below = (close < bottom).to_numpy()
    age = 0
    for i in range(len(below) - 1, -1, -1):
        if below[i]:
            age += 1
        else:
            break
    out['cloud_age'] = int(age)
    if age < 26:
        return out
    # liquidity gate (research edge validated only on >=$25M dollar-volume names)
    vol20 = df['volume'].rolling(20).mean().iloc[-1] if 'volume' in df.columns else float('nan')
    last_close = float(close.iloc[-1])
    dollar_vol = last_close * float(vol20) if not pd.isna(vol20) else 0.0
    if dollar_vol < CLOUD_DISLOCATION_LIQ_MIN:
        return out
    if 'rsi_14' in df.columns and not pd.isna(df['rsi_14'].iloc[-1]):
        rsi = float(df['rsi_14'].iloc[-1])
    else:
        import talib as ta
        rsi_arr = ta.RSI(close.to_numpy(dtype=float), timeperiod=14)
        rsi = float(rsi_arr[-1]) if not pd.isna(rsi_arr[-1]) else 50.0
    if rsi < 30:
        out['confluence_star'] = True
    else:
        out['chronic_dislocation'] = True
    return out


def _score_symbol_worker(work_item):
    """
    CPU worker for ProcessPoolExecutor.
    Replicates SwingTrader.process_symbol() without database access.
    Uses pre-loaded data (from Phase 1) and ML models (from _init_worker).
    """
    try:
        trader = _worker_state['trader']
        strategies = _worker_state['strategies']
        benchmark_df = _worker_state['benchmark_df']
        overview = work_item['overview']
        sentiment = work_item['sentiment']

        symbol = work_item['symbol']
        full_name = work_item['full_name']
        exchange = work_item['exchange']

        # Reconstruct DataFrame from dict-of-lists
        df = pd.DataFrame(work_item['df_data'])
        yesterday = dict(df.iloc[-1])

        # --- Process all strategies via strategy interface ---
        strategy_results = {}
        for strategy in strategies:
            sr = strategy.process_worker(
                trader, df, symbol, yesterday, _worker_state,
                overview, sentiment,
            )
            if sr is not None:
                strategy_results[strategy.name] = sr

        if not strategy_results:
            return None

        # --- Connors RSI(2) flag — computed for ALL symbols with enough data ---
        connors_flag = False
        connors_rsi2 = None
        connors_sma200 = None
        if len(df) >= 200:
            import talib as ta
            rsi_2 = ta.RSI(df['close'].values, timeperiod=2)
            sma_200 = df['close'].rolling(200).mean()
            if not pd.isna(rsi_2[-1]) and not pd.isna(sma_200.iloc[-1]):
                connors_rsi2 = float(rsi_2[-1])
                connors_sma200 = float(sma_200.iloc[-1])
                connors_flag = bool(connors_rsi2 < 10 and df['close'].iloc[-1] > connors_sma200)

        # --- Assemble result using strategy keys (same structure as process_symbol) ---
        rs_ratio = 1.0
        if benchmark_df is not None:
            rs_ratio = trader.calculate_relative_strength(df, benchmark_df)

        cloud_flags = compute_cloud_dislocation_flags(df)
        options_atr = float("nan")
        try:
            options_atr = trader._calculate_atr(df)  # pylint: disable=protected-access
        except Exception:  # pylint: disable=broad-exception-caught
            pass

        result = {
            'symbol': symbol,
            'name': full_name,
            'exchange': exchange,
            'date': str(yesterday['date']),
            'rs_ratio': rs_ratio,
            'sentiment': sentiment,
            'connors_flag': connors_flag,
            'connors_rsi2': connors_rsi2,
            'connors_sma200': connors_sma200,
            'options_history': {
                'closes': df['close'].tail(10).astype(float).tolist(),
                'atr': options_atr,
            },
            **cloud_flags,
        }

        for strategy in strategies:
            sr = strategy_results.get(strategy.name)
            result[strategy.score_key] = sr.score if sr else 0.0
            result[strategy.components_key] = sr.components if sr else {}
            result[strategy.setup_key] = sr.setup if sr else {}
            result[strategy.ml_prob_key] = sr.ml_prob if sr else 0.0
            if sr:
                result['stop_multiplier'] = sr.stop_multiplier
                result['target_multiplier'] = sr.target_multiplier

        score_parts = " | ".join(
            f"{s.display_name}={result.get(s.score_key, 0):.2f}"
            for s in strategies
        )
        logging.info("Scored %s: %s", symbol, score_parts)
        return result

    except Exception as e:  # pylint: disable=broad-exception-caught
        logging.error("Worker error for %s: %s", work_item.get('symbol', '?'), e)
        return None
