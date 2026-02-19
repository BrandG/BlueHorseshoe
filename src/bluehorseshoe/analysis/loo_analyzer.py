"""
loo_analyzer.py

Leave-One-Out (LOO) Weight Analyzer for the Baseline strategy.

Evaluates each sub-indicator's P&L contribution by:
1. Running a full scoring pass once per date (all weights at current values)
2. Caching per-sub-indicator raw scores and setup data
3. Mathematically reconstructing LOO variants by subtracting each indicator
4. Backtesting each variant to measure P&L impact
5. Comparing results to identify which indicators help vs. hurt
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

import pandas as pd

from bluehorseshoe.analysis.backtest import Backtester, BacktestConfig, SplitExitConfig
from bluehorseshoe.analysis.constants import (
    MIN_STOCK_PRICE, MAX_STOCK_PRICE,
    MIN_RR_RATIO_BASELINE, MAX_RISK_PERCENT,
    SIGNAL_STRENGTH_THRESHOLDS, ENTRY_DISCOUNT_BY_SIGNAL,
    ENABLE_DYNAMIC_ENTRY
)
from bluehorseshoe.analysis.indicators.detailed_scoring import DetailedScorer
from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.core.symbols import get_symbol_name_list
from bluehorseshoe.data.historical_data import (
    load_historical_data, get_active_symbol_list, get_technical_indicators,
)

logger = logging.getLogger(__name__)


@dataclass
class LOOConfig:
    """Configuration for LOO weight analysis."""
    start_date: str = ""
    end_date: str = ""
    interval_days: int = 7
    top_n: int = 50
    hold_days: int = 10


@dataclass
class IndicatorStats:
    """Accumulated stats for a single indicator across all LOO runs."""
    total_pnl: float = 0.0
    trade_count: int = 0
    win_count: int = 0
    pnl_values: list = field(default_factory=list)


def _classify_signal_strength(score: float) -> str:
    """Classify score into signal strength tier."""
    thresholds = SIGNAL_STRENGTH_THRESHOLDS
    if score >= thresholds['EXTREME']:
        return 'EXTREME'
    if score >= thresholds['HIGH']:
        return 'HIGH'
    if score >= thresholds['MEDIUM']:
        return 'MEDIUM'
    if score >= thresholds['LOW']:
        return 'LOW'
    return 'WEAK'


def _get_atr_discount(score: float) -> float:
    """Get ATR discount for entry calculation based on signal strength."""
    if not ENABLE_DYNAMIC_ENTRY:
        return 0.20
    signal = _classify_signal_strength(score)
    return ENTRY_DISCOUNT_BY_SIGNAL.get(signal, 0.20)


def _reconstruct_setup(total_score: float, setup_data: Dict[str, float]) -> Optional[Dict[str, float]]:
    """
    Reconstruct entry/stop/target from a total score and setup data.
    Mirrors SwingTrader.calculate_baseline_setup() logic.

    Returns None if the setup fails validation (price out of range, bad R:R, etc.)
    """
    close = setup_data['close']
    atr = setup_data['atr']
    swing_low_5 = setup_data['swing_low_5']
    swing_high_20 = setup_data['swing_high_20']

    # Entry
    atr_discount = _get_atr_discount(total_score)
    signal_strength = _classify_signal_strength(total_score)
    entry_price = close - (atr_discount * atr)

    # Price range check
    if not MIN_STOCK_PRICE < entry_price < MAX_STOCK_PRICE:
        return None

    # Stop Loss (use default ml_stop_multiplier=2.0, ml_target_multiplier=3.0)
    ml_stop_mult = 2.0
    ml_target_mult = 3.0

    atr_stop = entry_price - (ml_stop_mult * atr)
    swing_stop = swing_low_5 * 0.985
    stop_loss = min(swing_stop, atr_stop)

    # Target
    atr_target = entry_price + (ml_target_mult * atr)
    resistance_cap = swing_high_20 * 0.98
    take_profit = min(atr_target, resistance_cap)
    if take_profit <= entry_price:
        take_profit = atr_target

    # Risk/Reward
    risk = entry_price - stop_loss
    reward = take_profit - entry_price
    rr_ratio = reward / risk if risk > 0 else 0

    # Smart stop: try ATR stop if swing stop kills R:R
    if rr_ratio < MIN_RR_RATIO_BASELINE and stop_loss == swing_stop:
        risk_atr = entry_price - atr_stop
        rr_atr = reward / risk_atr if risk_atr > 0 else 0
        if rr_atr >= MIN_RR_RATIO_BASELINE:
            stop_loss = atr_stop
            rr_ratio = rr_atr

    # Realistic check
    risk_pct = (entry_price - stop_loss) / entry_price if entry_price > 0 else 0
    is_realistic = (abs((close / entry_price) - 1) <= 0.15) and (risk_pct <= MAX_RISK_PERCENT)
    if not is_realistic:
        return None

    if rr_ratio < MIN_RR_RATIO_BASELINE:
        return None

    return {
        'entry_price': float(entry_price),
        'stop_loss': float(stop_loss),
        'take_profit': float(take_profit),
        'rr_ratio': float(rr_ratio),
        'signal_strength': signal_strength,
    }


class LOOAnalyzer:
    """
    Main orchestrator for Leave-One-Out weight analysis.

    Runs a full scoring pass once per date, caches per-sub-indicator raw scores,
    then mathematically reconstructs LOO variants and backtests each to measure
    P&L contribution of every sub-indicator.
    """

    def __init__(self, database, config: LOOConfig):
        self.database = database
        self.config = config
        self.backtester = Backtester(
            config=BacktestConfig(hold_days=config.hold_days),
            database=database,
        )
        self._data_cache: Dict[str, pd.DataFrame] = {}

    def _generate_dates(self) -> List[str]:
        """Generate backtest dates from start_date to end_date at interval_days."""
        dates = []
        current = pd.to_datetime(self.config.start_date)
        end = pd.to_datetime(self.config.end_date)
        while current <= end:
            dates.append(current.strftime('%Y-%m-%d'))
            current += pd.Timedelta(days=self.config.interval_days)
        return dates

    _OHLCV_COLS = ['date', 'open', 'high', 'low', 'close', 'volume']

    def _preload_all_data(self, symbols: List[str]) -> None:
        """Load OHLCV-only data for all symbols into memory cache using parallel I/O.

        Stores only date + OHLCV columns with float32 numerics to keep memory
        under ~300 MB for ~3000 symbols. Indicators are recomputed on-the-fly
        in _load_symbol_data when needed for scoring.
        """
        print(f"  Preloading OHLCV data for {len(symbols)} symbols...", flush=True)
        self._data_cache.clear()

        def _load_one(symbol: str) -> Optional[tuple]:
            price_data = load_historical_data(symbol, database=self.database)
            if price_data is None or not price_data.get('days'):
                return None
            df = pd.DataFrame(price_data['days'])
            # Keep only OHLCV columns
            available = [c for c in self._OHLCV_COLS if c in df.columns]
            df = df[available]
            df['date'] = pd.to_datetime(df['date'])
            # Downcast to reduce memory
            for c in df.select_dtypes('float64').columns:
                df[c] = df[c].astype('float32')
            for c in df.select_dtypes('int64').columns:
                df[c] = df[c].astype('int32')
            return (symbol, df)

        for loaded, sym in enumerate(symbols, 1):
            try:
                result = _load_one(sym)
            except Exception:
                logger.debug("Error loading %s", sym, exc_info=True)
                continue
            if result is not None:
                self._data_cache[result[0]] = result[1]
            if loaded % 500 == 0 or loaded == len(symbols):
                print(f"    {loaded}/{len(symbols)} symbols loaded ({len(self._data_cache)} cached)", flush=True)

        print(f"  Preload complete: {len(self._data_cache)} symbols cached", flush=True)

    def _load_symbol_data(self, symbol: str, target_date: str) -> Optional[pd.DataFrame]:
        """Load and filter historical data for a symbol up to target_date.

        When data is in the OHLCV cache, filters by date and recomputes
        technical indicators from OHLCV (TA-Lib, ~1ms per symbol).
        """
        cached_df = self._data_cache.get(symbol)
        if cached_df is not None:
            target_ts = pd.to_datetime(target_date)
            df = cached_df[cached_df['date'] <= target_ts]

            if df.empty or len(df) < 30:
                return None

            last_date = df.iloc[-1]['date']
            if (target_ts - last_date).days > 7:
                return None

            # Compute indicators from OHLCV (copy to avoid mutating cache)
            df = df.copy()
            # Upcast to float64 — TA-Lib candlestick functions require double
            for c in df.select_dtypes('float32').columns:
                df[c] = df[c].astype('float64')
            # get_technical_indicators modifies df in-place then returns dicts;
            # we only need the in-place modifications.
            get_technical_indicators(df)
            return df

        # Fallback to MongoDB load
        price_data = load_historical_data(symbol, database=self.database)
        if price_data is None or not price_data.get('days'):
            return None

        df = pd.DataFrame(price_data['days'])
        df['date'] = pd.to_datetime(df['date'])
        target_ts = pd.to_datetime(target_date)
        df = df[df['date'] <= target_ts]

        if df.empty or len(df) < 30:
            return None

        # Staleness check
        last_date = df.iloc[-1]['date']
        if (target_ts - last_date).days > 7:
            return None

        return df

    def _score_symbol(self, symbol: str, target_date: str) -> Optional[Dict[str, Any]]:
        """Score a single symbol. Returns candidate dict or None."""
        df = self._load_symbol_data(symbol, target_date)
        if df is None:
            return None

        raw_scores, weighted_scores, total_score = DetailedScorer.score_all_indicators(df)
        if not raw_scores or total_score <= 0:
            return None

        setup_data = DetailedScorer.get_setup_data(df)
        full_setup = _reconstruct_setup(total_score, setup_data)
        if full_setup is None:
            return None

        return {
            'symbol': symbol,
            'raw_scores': raw_scores,
            'weighted_scores': weighted_scores,
            'total_score': total_score,
            'setup_data': setup_data,
            'full_setup': full_setup,
        }

    def _score_date(self, target_date: str, symbols: List[str]) -> List[Dict[str, Any]]:
        """
        Run full scoring for all symbols on a single date.

        With data cached in memory, scoring is CPU-bound (pandas/numpy),
        so a simple sequential loop avoids thread overhead.

        Returns list of candidate dicts with:
        - symbol, raw_scores, weighted_scores, total_score, setup_data
        """
        candidates = []
        total_symbols = len(symbols)

        for completed, sym in enumerate(symbols, 1):
            try:
                result = self._score_symbol(sym, target_date)
            except Exception:
                logger.debug("Error scoring %s", sym, exc_info=True)
                continue
            if result is not None:
                candidates.append(result)
            if completed % 500 == 0 or completed == total_symbols:
                print(f"    {completed}/{total_symbols} symbols scored ({len(candidates)} candidates)", flush=True)

        # Sort by total score and take top N
        candidates.sort(key=lambda x: x['total_score'], reverse=True)
        return candidates[:self.config.top_n]

    def _backtest_variant(
        self,
        candidates: List[Dict],
        target_date: str,
        omit_key: Optional[str] = None,
        split_config: Optional[SplitExitConfig] = None,
    ) -> List[Dict[str, Any]]:
        """
        Backtest a LOO variant (or baseline if omit_key is None).

        For each candidate, reconstructs the setup with the omitted indicator's
        weighted score subtracted from the total, then runs evaluate_prediction.
        """
        results = []

        for cand in candidates:
            total = cand['total_score']
            setup_data = cand['setup_data']

            if omit_key is not None:
                # Subtract the omitted indicator's weighted contribution
                omitted_contribution = cand['weighted_scores'].get(omit_key, 0.0)
                adjusted_total = total - omitted_contribution
            else:
                adjusted_total = total

            if adjusted_total <= 0:
                continue

            # Reconstruct setup with adjusted score
            setup = _reconstruct_setup(adjusted_total, setup_data)
            if setup is None:
                continue

            # Build prediction dict for backtester
            prediction = {
                'symbol': cand['symbol'],
                'entry_price': setup['entry_price'],
                'stop_loss': setup['stop_loss'],
                'take_profit': setup['take_profit'],
            }

            # Pass cached DataFrame to avoid redundant MongoDB reads
            cached_df = self._data_cache.get(cand['symbol'])

            if split_config is not None:
                # Pass ATR from setup_data for Plan B
                prediction['atr'] = setup_data.get('atr')
                eval_result = self.backtester.evaluate_prediction_split(
                    prediction, target_date, split_config, price_df=cached_df)
            else:
                eval_result = self.backtester.evaluate_prediction(
                    prediction, target_date, price_df=cached_df)

            # Calculate P&L
            if eval_result.get('entry') is not None and eval_result.get('exit_price') is not None:
                pnl_pct = eval_result.get('blended_pnl_pct') if eval_result.get('exit_mode') == 'split_exit' else \
                    ((eval_result['exit_price'] / eval_result['entry']) - 1) * 100
                win_statuses = ['success', 'closed_profit', 'split_full_profit', 'split_partial_profit']
                is_win = eval_result['status'] in win_statuses
            else:
                pnl_pct = 0.0
                is_win = False

            results.append({
                'symbol': cand['symbol'],
                'status': eval_result['status'],
                'pnl_pct': pnl_pct,
                'is_win': is_win,
                'entry': eval_result.get('entry'),
                'exit_price': eval_result.get('exit_price'),
            })

        return results

    def _accumulate_stats(
        self,
        stats: Dict[str, IndicatorStats],
        key: str,
        results: List[Dict],
    ):
        """Accumulate backtest results into indicator stats."""
        if key not in stats:
            stats[key] = IndicatorStats()

        for r in results:
            if r.get('entry') is not None and r.get('exit_price') is not None:
                stats[key].total_pnl += r['pnl_pct']
                stats[key].trade_count += 1
                stats[key].pnl_values.append(r['pnl_pct'])
                if r['is_win']:
                    stats[key].win_count += 1

    def run(self, symbols: Optional[List[str]] = None, split_config: Optional[SplitExitConfig] = None) -> Dict[str, Any]:
        """
        Run the full LOO analysis across all dates.

        Args:
            symbols: Optional list of symbols to analyze. If None, loads all from DB.

        Returns:
            Dict with:
            - baseline_stats: IndicatorStats for all-indicators variant
            - indicator_stats: {indicator_key: IndicatorStats}
            - indicator_keys: sorted list of indicator keys analyzed
            - dates_analyzed: list of dates processed
            - config: LOOConfig used
        """
        dates = self._generate_dates()
        if not dates:
            print("No dates to analyze.")
            return {}

        print(f"LOO Analysis: {len(dates)} dates from {dates[0]} to {dates[-1]}")
        print(f"Config: top_n={self.config.top_n}, hold_days={self.config.hold_days}, interval={self.config.interval_days}d")

        # Load symbols once — default to active (tradeable) symbols
        if symbols is None:
            active_set = get_active_symbol_list(database=self.database)
            all_symbols = get_symbol_name_list(database=self.database, active_only=True)
            symbols = [s for s in all_symbols if s in active_set]
            print(f"Loaded {len(symbols)} active symbols (of {len(all_symbols)} listed)")
        else:
            print(f"Using {len(symbols)} specified symbols")

        # Preload all symbol data into memory to avoid redundant MongoDB reads
        self._preload_all_data(symbols)

        baseline_stats: Dict[str, IndicatorStats] = {}
        indicator_stats: Dict[str, IndicatorStats] = {}
        all_indicator_keys: set = set()
        dates_analyzed = []

        for date_idx, target_date in enumerate(dates):
            print(f"\n--- Date {date_idx + 1}/{len(dates)}: {target_date} ---")

            # Phase 1: Score all symbols for this date
            print(f"  Phase 1: Scoring symbols...", flush=True)
            candidates = self._score_date(target_date, symbols)
            if not candidates:
                print(f"  No valid candidates for {target_date}, skipping.")
                continue

            dates_analyzed.append(target_date)
            print(f"  Found {len(candidates)} candidates (top score: {candidates[0]['total_score']:.1f})")

            # Collect all indicator keys from this batch
            date_keys = set()
            for cand in candidates:
                date_keys.update(cand['weighted_scores'].keys())
            all_indicator_keys.update(date_keys)

            # Phase 2: Backtest baseline (all indicators)
            print(f"  Phase 2: Backtesting baseline...", flush=True)
            baseline_results = self._backtest_variant(candidates, target_date, omit_key=None, split_config=split_config)
            self._accumulate_stats(baseline_stats, 'baseline', baseline_results)

            baseline_trades = sum(1 for r in baseline_results if r.get('entry') is not None)
            baseline_pnl = sum(r['pnl_pct'] for r in baseline_results if r.get('entry') is not None)
            print(f"  Baseline: {baseline_trades} trades, P&L: {baseline_pnl:.2f}%")

            # Phase 3: LOO variants (parallelized)
            sorted_keys = sorted(date_keys)
            print(f"  Phase 3: Testing {len(sorted_keys)} LOO variants...", flush=True)

            for completed_variants, key in enumerate(sorted_keys, 1):
                try:
                    loo_results = self._backtest_variant(candidates, target_date, key, split_config)
                except Exception:
                    logger.warning("Error in LOO variant %s: %s", key, exc_info=True)
                    continue
                self._accumulate_stats(indicator_stats, key, loo_results)
                if completed_variants % 10 == 0 or completed_variants == len(sorted_keys):
                    print(f"    {completed_variants}/{len(sorted_keys)} variants tested", flush=True)

        # Free cached data
        self._data_cache.clear()

        # Compile results
        return {
            'baseline_stats': baseline_stats.get('baseline', IndicatorStats()),
            'indicator_stats': indicator_stats,
            'indicator_keys': sorted(all_indicator_keys),
            'dates_analyzed': dates_analyzed,
            'config': self.config,
        }
