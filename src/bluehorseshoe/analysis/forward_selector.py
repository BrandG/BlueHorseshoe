"""
forward_selector.py

Forward Selection Weight Analyzer for the Baseline strategy.

Builds the minimal effective indicator set by starting with all weights at 0.0
and adding one indicator at a time, keeping it only if it improves P&L.

Reuses existing infrastructure:
- DetailedScorer.score_all_indicators() for per-sub-indicator scoring
- _reconstruct_setup() from loo_analyzer.py for entry/stop/target calculation
- Backtester.evaluate_prediction_split() for P&L simulation
- LOOAnalyzer._preload_all_data() pattern for memory-efficient data loading
"""

import csv
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Any

import pandas as pd

from bluehorseshoe.analysis.backtest import Backtester, BacktestConfig, SplitExitConfig
from bluehorseshoe.analysis.indicators.detailed_scoring import DetailedScorer
from bluehorseshoe.analysis.loo_analyzer import _reconstruct_setup
from bluehorseshoe.core.symbols import get_symbol_name_list
from bluehorseshoe.data.historical_data import (
    load_historical_data, get_active_symbol_list, get_technical_indicators,
)

logger = logging.getLogger(__name__)

# Plan A split-exit (2% T1) — always used for forward selection
SPLIT_CONFIG = SplitExitConfig(mode='fixed_pct', t1_profit_pct=0.02)

# Minimum cumulative P&L% improvement required to add an indicator
DEFAULT_MIN_IMPROVEMENT = 0.1


@dataclass
class ForwardConfig:
    """Configuration for forward selection analysis."""
    start_date: str = ""
    end_date: str = ""
    interval_days: int = 7
    top_n: int = 50
    hold_days: int = 10
    min_improvement: float = DEFAULT_MIN_IMPROVEMENT


class ForwardSelector:
    """
    Forward selection weight analyzer.

    Starts with all indicator weights at 0.0, adds one indicator at a time,
    and keeps it only if cumulative P&L improves by at least min_improvement.
    """

    _OHLCV_COLS = ['date', 'open', 'high', 'low', 'close', 'volume']

    def __init__(self, database, config: ForwardConfig):
        self.database = database
        self.config = config
        self.backtester = Backtester(
            config=BacktestConfig(hold_days=config.hold_days),
            database=database,
        )
        self._data_cache: Dict[str, pd.DataFrame] = {}

    def _generate_dates(self) -> List[str]:
        """Generate analysis dates from start_date to end_date at interval_days."""
        dates = []
        current = pd.to_datetime(self.config.start_date)
        end = pd.to_datetime(self.config.end_date)
        while current <= end:
            dates.append(current.strftime('%Y-%m-%d'))
            current += pd.Timedelta(days=self.config.interval_days)
        return dates

    def _preload_all_data(self, symbols: List[str]) -> None:
        """Load OHLCV-only data for all symbols into memory cache."""
        print(f"  Preloading OHLCV data for {len(symbols)} symbols...", flush=True)
        self._data_cache.clear()

        for loaded, sym in enumerate(symbols, 1):
            try:
                price_data = load_historical_data(sym, database=self.database)
                if price_data is None or not price_data.get('days'):
                    continue
                df = pd.DataFrame(price_data['days'])
                available = [c for c in self._OHLCV_COLS if c in df.columns]
                df = df[available]
                df['date'] = pd.to_datetime(df['date'])
                for c in df.select_dtypes('float64').columns:
                    df[c] = df[c].astype('float32')
                for c in df.select_dtypes('int64').columns:
                    df[c] = df[c].astype('int32')
                self._data_cache[sym] = df
            except Exception:
                logger.debug("Error loading %s", sym, exc_info=True)
                continue

            if loaded % 500 == 0 or loaded == len(symbols):
                print(f"    {loaded}/{len(symbols)} symbols loaded ({len(self._data_cache)} cached)", flush=True)

        print(f"  Preload complete: {len(self._data_cache)} symbols cached", flush=True)

    def _load_symbol_data(self, symbol: str, target_date: str) -> Optional[pd.DataFrame]:
        """Load and filter historical data for a symbol up to target_date."""
        cached_df = self._data_cache.get(symbol)
        if cached_df is None:
            return None

        target_ts = pd.to_datetime(target_date)
        df = cached_df[cached_df['date'] <= target_ts]

        if df.empty or len(df) < 30:
            return None

        last_date = df.iloc[-1]['date']
        if (target_ts - last_date).days > 7:
            return None

        df = df.copy()
        for c in df.select_dtypes('float32').columns:
            df[c] = df[c].astype('float64')
        get_technical_indicators(df)
        return df

    def _score_all_dates(
        self, symbols: List[str], dates: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Score all symbols across all dates. Cache the full per-indicator
        breakdown so we can reconstruct trial totals cheaply.

        Returns:
            {date: [candidate_dict, ...]} where each candidate has:
            - symbol, raw_scores, weighted_scores, total_score, setup_data
        """
        scored_data: Dict[str, List[Dict[str, Any]]] = {}

        for date_idx, target_date in enumerate(dates):
            print(f"\n  Scoring date {date_idx + 1}/{len(dates)}: {target_date}", flush=True)
            candidates = []
            total_symbols = len(symbols)

            for completed, sym in enumerate(symbols, 1):
                try:
                    df = self._load_symbol_data(sym, target_date)
                    if df is None:
                        continue

                    raw_scores, weighted_scores, total_score = DetailedScorer.score_all_indicators(df)
                    if not raw_scores or total_score <= 0:
                        continue

                    setup_data = DetailedScorer.get_setup_data(df)
                    candidates.append({
                        'symbol': sym,
                        'raw_scores': raw_scores,
                        'weighted_scores': weighted_scores,
                        'total_score': total_score,
                        'setup_data': setup_data,
                    })
                except Exception:
                    logger.debug("Error scoring %s on %s", sym, target_date, exc_info=True)
                    continue

                if completed % 500 == 0 or completed == total_symbols:
                    print(f"    {completed}/{total_symbols} scored ({len(candidates)} candidates)", flush=True)

            scored_data[target_date] = candidates
            print(f"    {target_date}: {len(candidates)} candidates", flush=True)

        return scored_data

    def _evaluate_indicator_set(
        self,
        active_keys: set,
        scored_data: Dict[str, List[Dict[str, Any]]],
        dates: List[str],
    ) -> float:
        """
        Evaluate cumulative P&L for a given set of active indicator keys.

        For each date:
        1. Reconstruct trial_total for each candidate by summing raw_scores
           (weight=1.0) for keys in active_keys + all modifier.* keys.
        2. Take top-N by trial_total.
        3. Reconstruct setups and backtest with Plan A split-exit.
        4. Accumulate P&L.

        Uses raw_scores (not weighted_scores) so that every indicator is
        evaluated on a level playing field regardless of production weights.
        """
        total_pnl = 0.0

        for target_date in dates:
            candidates = scored_data.get(target_date, [])
            if not candidates:
                continue

            # Reconstruct trial totals using raw scores (equal weight = 1.0)
            trial_candidates = []
            for cand in candidates:
                trial_total = 0.0
                for key, raw_score in cand['raw_scores'].items():
                    # Always include modifiers (penalties/bonuses)
                    if key.startswith('modifier.') or key in active_keys:
                        trial_total += raw_score

                if trial_total <= 0:
                    continue

                trial_candidates.append({
                    'symbol': cand['symbol'],
                    'trial_total': trial_total,
                    'setup_data': cand['setup_data'],
                })

            # Sort by trial_total and take top-N
            trial_candidates.sort(key=lambda x: x['trial_total'], reverse=True)
            top_candidates = trial_candidates[:self.config.top_n]

            # Backtest each candidate
            for tc in top_candidates:
                setup = _reconstruct_setup(tc['trial_total'], tc['setup_data'])
                if setup is None:
                    continue

                prediction = {
                    'symbol': tc['symbol'],
                    'entry_price': setup['entry_price'],
                    'stop_loss': setup['stop_loss'],
                    'take_profit': setup['take_profit'],
                }

                cached_df = self._data_cache.get(tc['symbol'])
                eval_result = self.backtester.evaluate_prediction_split(
                    prediction, target_date, SPLIT_CONFIG, price_df=cached_df
                )

                if eval_result.get('entry') is not None and eval_result.get('exit_price') is not None:
                    if eval_result.get('exit_mode') == 'split_exit':
                        pnl_pct = eval_result.get('blended_pnl_pct', 0.0)
                    else:
                        pnl_pct = ((eval_result['exit_price'] / eval_result['entry']) - 1) * 100
                    total_pnl += pnl_pct

        return total_pnl

    def run(self, symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Run the forward selection algorithm.

        Returns:
            Dict with:
            - rounds: list of {round, indicator, cumulative_pnl, marginal_improvement}
            - active_set: final set of selected indicator keys
            - baseline_pnl: P&L with modifiers only (no weighted indicators)
            - config: ForwardConfig used
        """
        dates = self._generate_dates()
        if not dates:
            print("No dates to analyze.")
            return {}

        print(f"Forward Selection: {len(dates)} dates from {dates[0]} to {dates[-1]}")
        print(f"Config: top_n={self.config.top_n}, hold_days={self.config.hold_days}, "
              f"interval={self.config.interval_days}d, min_improvement={self.config.min_improvement}%")

        # Load symbols
        if symbols is None:
            active_set = get_active_symbol_list(database=self.database)
            all_symbols = get_symbol_name_list(database=self.database, active_only=True)
            symbols = [s for s in all_symbols if s in active_set]
            print(f"Loaded {len(symbols)} active symbols (of {len(all_symbols)} listed)")
        else:
            print(f"Using {len(symbols)} specified symbols")

        # Phase 1: Preload data
        self._preload_all_data(symbols)

        # Phase 2: Score all symbols across all dates (once)
        print("\n=== Phase 2: Scoring all symbols across all dates ===")
        scored_data = self._score_all_dates(symbols, dates)

        # Collect all non-modifier indicator keys
        all_keys = set()
        for date_candidates in scored_data.values():
            for cand in date_candidates:
                for key in cand['weighted_scores']:
                    if not key.startswith('modifier.'):
                        all_keys.add(key)

        remaining = sorted(all_keys)
        print(f"\n{len(remaining)} indicator candidates to evaluate")

        # Phase 3: Forward selection
        print("\n=== Phase 3: Forward Selection ===")
        active_keys: set = set()
        rounds: List[Dict[str, Any]] = []

        # Evaluate baseline (modifiers only, no weighted indicators)
        baseline_pnl = self._evaluate_indicator_set(set(), scored_data, dates)
        print(f"Baseline (modifiers only): P&L = {baseline_pnl:.2f}%")

        current_pnl = baseline_pnl

        for round_num in range(1, len(remaining) + 1):
            best_key = None
            best_pnl = current_pnl

            print(f"\n--- Round {round_num} ({len(remaining)} candidates remaining) ---")

            for trial_idx, candidate_key in enumerate(remaining, 1):
                trial_set = active_keys | {candidate_key}
                trial_pnl = self._evaluate_indicator_set(trial_set, scored_data, dates)

                if trial_pnl > best_pnl + self.config.min_improvement:
                    best_key = candidate_key
                    best_pnl = trial_pnl

                if trial_idx % 10 == 0 or trial_idx == len(remaining):
                    print(f"  Tested {trial_idx}/{len(remaining)} "
                          f"(best so far: {best_key or 'none'}, P&L: {best_pnl:.2f}%)", flush=True)

            if best_key is None:
                print(f"\nNo indicator improves P&L by >= {self.config.min_improvement}%. Stopping.")
                break

            improvement = best_pnl - current_pnl
            active_keys.add(best_key)
            remaining.remove(best_key)
            current_pnl = best_pnl

            round_info = {
                'round': round_num,
                'indicator': best_key,
                'cumulative_pnl': round(current_pnl, 4),
                'marginal_improvement': round(improvement, 4),
            }
            rounds.append(round_info)
            print(f"  >>> Added '{best_key}': P&L = {current_pnl:.2f}% (+{improvement:.2f}%)")

        # Free cached data
        self._data_cache.clear()

        results = {
            'rounds': rounds,
            'active_set': sorted(active_keys),
            'baseline_pnl': round(baseline_pnl, 4),
            'final_pnl': round(current_pnl, 4),
            'config': self.config,
            'dates': dates,
        }

        # Output reports
        self._print_summary(results)
        self._export_csv(results)
        self._export_weights_suggestion(results)

        return results

    @staticmethod
    def _print_summary(results: Dict[str, Any]) -> None:
        """Print forward selection summary to console."""
        config = results['config']
        rounds = results['rounds']
        active_set = results['active_set']

        print("\n" + "=" * 80)
        print("FORWARD SELECTION RESULTS")
        print("=" * 80)
        print(f"Dates: {config.start_date} to {config.end_date} "
              f"(interval={config.interval_days}d, {len(results['dates'])} dates)")
        print(f"Config: top_n={config.top_n}, hold_days={config.hold_days}, "
              f"min_improvement={config.min_improvement}%")
        print(f"Split-exit: Plan A (fixed_pct 2% T1)")
        print()

        print(f"Baseline P&L (modifiers only): {results['baseline_pnl']:.2f}%")
        print(f"Final P&L ({len(active_set)} indicators): {results['final_pnl']:.2f}%")
        print(f"Total improvement: {results['final_pnl'] - results['baseline_pnl']:.2f}%")
        print()

        if rounds:
            print(f"{'Round':<6} {'Indicator':<35} {'Cum P&L':>10} {'Marginal':>10}")
            print("-" * 65)
            for r in rounds:
                print(f"{r['round']:<6} {r['indicator']:<35} {r['cumulative_pnl']:>9.2f}% "
                      f"{r['marginal_improvement']:>+9.2f}%")
            print("-" * 65)
        else:
            print("No indicators selected (none improve P&L above threshold).")

        print()
        print(f"Selected indicators ({len(active_set)}):")
        for key in active_set:
            print(f"  - {key}")
        print()

    @staticmethod
    def _export_csv(results: Dict[str, Any], output_dir: str = "src/logs") -> str:
        """Export forward selection results to CSV."""
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y-%m-%d')
        csv_path = os.path.join(output_dir, f"forward_selection_{timestamp}.csv")

        fieldnames = ['round', 'indicator', 'cumulative_pnl', 'marginal_improvement']

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results['rounds'])

        print(f"CSV exported to: {csv_path}")
        return csv_path

    @staticmethod
    def _export_weights_suggestion(results: Dict[str, Any], output_dir: str = "src/logs") -> str:
        """Export suggested weights.json snippet."""
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y-%m-%d')
        json_path = os.path.join(output_dir, f"forward_weights_{timestamp}.json")

        # Build weight suggestion: active indicators get 1.0, others get 0.0
        weights = {}
        for r in results['rounds']:
            key = r['indicator']
            weights[key] = 1.0

        suggestion = {
            'description': 'Forward selection suggested weights',
            'baseline_pnl': results['baseline_pnl'],
            'final_pnl': results['final_pnl'],
            'active_indicators': weights,
            'note': 'Indicators not listed should have weight 0.0',
        }

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(suggestion, f, indent=2)

        print(f"Weight suggestion exported to: {json_path}")
        return json_path
