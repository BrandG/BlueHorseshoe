"""
indicator_impact.py

Standalone indicator impact analyzer. Measures each indicator's independent
predictive power by correlating raw scores with actual forward returns.

Completely divorced from the strategy pipeline — no top-N selection,
no setup reconstruction, no position sizing. Just:

  For each indicator, across many symbols and dates:
    - How often does it fire (non-zero score)?
    - When it fires positive, what are the average forward returns?
    - When it doesn't fire, what are the average forward returns?
    - What's the lift (difference)?
    - What's the correlation between score and forward return?
"""

import csv
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from bluehorseshoe.analysis.indicators.detailed_scoring import DetailedScorer
from bluehorseshoe.core.symbols import get_symbol_name_list
from bluehorseshoe.data.historical_data import (
    load_historical_data, get_active_symbol_list, get_technical_indicators,
)

logger = logging.getLogger(__name__)


@dataclass
class ImpactConfig:
    """Configuration for indicator impact analysis."""
    start_date: str = ""
    end_date: str = ""
    interval_days: int = 14
    hold_days: int = 10


@dataclass
class IndicatorStats:
    """Accumulator for a single indicator's observations."""
    positive_returns: List[float] = field(default_factory=list)
    zero_returns: List[float] = field(default_factory=list)
    score_return_pairs: List[tuple] = field(default_factory=list)
    positive_scores: List[float] = field(default_factory=list)


class IndicatorImpactAnalyzer:
    """
    Measures each indicator's independent predictive power.

    For each indicator across multiple dates and symbols:
    1. Compute the indicator's raw score (no weight multiplication)
    2. Compute the symbol's actual forward return (next-day open → close after hold_days)
    3. Aggregate: fire rate, avg return when positive vs zero, lift, correlation
    """

    _OHLCV_COLS = ['date', 'open', 'high', 'low', 'close', 'volume']

    def __init__(self, database, config: ImpactConfig):
        self.database = database
        self.config = config
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
        """Load OHLCV data for all symbols into memory cache."""
        print(f"  Preloading data for {len(symbols)} symbols...", flush=True)
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
                print(f"    {loaded}/{len(symbols)} loaded ({len(self._data_cache)} cached)", flush=True)

        print(f"  Preload complete: {len(self._data_cache)} symbols cached", flush=True)

    def _get_scored_data(self, symbol: str, target_date: str) -> Optional[pd.DataFrame]:
        """Load, filter, and add technical indicators for scoring."""
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

    def _compute_forward_return(self, symbol: str, target_date: str) -> Optional[float]:
        """
        Compute forward return: next-day open → close after hold_days.

        This mirrors what a real trade would look like: you see the signal
        at end of day, buy at next open, hold for N days, sell at close.
        """
        cached_df = self._data_cache.get(symbol)
        if cached_df is None:
            return None

        target_ts = pd.to_datetime(target_date)

        # Need float64 for return calculation
        df = cached_df.copy()
        if 'open' in df.select_dtypes('float32').columns:
            df['open'] = df['open'].astype('float64')
            df['close'] = df['close'].astype('float64')

        future = df[df['date'] > target_ts]
        if len(future) < self.config.hold_days:
            return None

        entry_price = float(future.iloc[0]['open'])
        exit_price = float(future.iloc[self.config.hold_days - 1]['close'])

        if entry_price <= 0:
            return None

        return ((exit_price / entry_price) - 1) * 100

    def run(self, symbols: Optional[List[str]] = None) -> Dict:
        """
        Run indicator impact analysis.

        Returns dict with per-indicator metrics.
        """
        dates = self._generate_dates()
        if not dates:
            print("No dates to analyze.")
            return {}

        print(f"Indicator Impact Analysis: {len(dates)} dates "
              f"from {dates[0]} to {dates[-1]}")
        print(f"Config: hold_days={self.config.hold_days}, "
              f"interval={self.config.interval_days}d")

        # Load symbols
        if symbols is None:
            active_set = get_active_symbol_list(database=self.database)
            all_symbols = get_symbol_name_list(database=self.database, active_only=True)
            symbols = [s for s in all_symbols if s in active_set]
            print(f"Loaded {len(symbols)} active symbols")
        else:
            print(f"Using {len(symbols)} specified symbols")

        # Phase 1: Preload
        self._preload_all_data(symbols)

        # Phase 2: Score all symbols × dates, pair with forward returns
        indicator_stats: Dict[str, IndicatorStats] = defaultdict(IndicatorStats)
        total_observations = 0
        total_scored = 0

        for date_idx, target_date in enumerate(dates):
            print(f"\n  Date {date_idx + 1}/{len(dates)}: {target_date}", flush=True)
            date_scored = 0

            for completed, sym in enumerate(symbols, 1):
                try:
                    df = self._get_scored_data(sym, target_date)
                    if df is None:
                        continue

                    fwd_return = self._compute_forward_return(sym, target_date)
                    if fwd_return is None:
                        continue

                    raw_scores, _, _ = DetailedScorer.score_all_indicators(df)
                    if not raw_scores:
                        continue

                    total_observations += 1
                    date_scored += 1

                    for key, score in raw_scores.items():
                        if key.startswith('modifier.'):
                            continue

                        stats = indicator_stats[key]
                        stats.score_return_pairs.append((score, fwd_return))

                        if score > 0:
                            stats.positive_returns.append(fwd_return)
                            stats.positive_scores.append(score)
                        else:
                            stats.zero_returns.append(fwd_return)

                except Exception:
                    logger.debug("Error processing %s on %s", sym, target_date, exc_info=True)
                    continue

                if completed % 500 == 0 or completed == len(symbols):
                    print(f"    {completed}/{len(symbols)} processed "
                          f"({date_scored} scored)", flush=True)

            total_scored += date_scored
            print(f"    {target_date}: {date_scored} symbol-dates scored", flush=True)

        # Phase 3: Compute metrics
        print(f"\n  Total observations: {total_scored}")
        results = self._compute_metrics(indicator_stats, total_scored)

        # Output
        self._print_report(results, total_scored)
        self._export_csv(results)

        # Free memory
        self._data_cache.clear()

        return results

    @staticmethod
    def _compute_metrics(
        indicator_stats: Dict[str, IndicatorStats],
        total_observations: int,
    ) -> List[Dict]:
        """Compute per-indicator metrics from accumulated observations."""
        results = []

        for key in sorted(indicator_stats.keys()):
            stats = indicator_stats[key]
            n_positive = len(stats.positive_returns)
            n_zero = len(stats.zero_returns)
            n_total = n_positive + n_zero

            if n_total == 0:
                continue

            fire_rate = (n_positive / n_total) * 100 if n_total > 0 else 0

            avg_return_positive = (
                np.mean(stats.positive_returns) if n_positive > 0 else 0.0
            )
            avg_return_zero = (
                np.mean(stats.zero_returns) if n_zero > 0 else 0.0
            )
            lift = avg_return_positive - avg_return_zero

            avg_score_positive = (
                np.mean(stats.positive_scores) if n_positive > 0 else 0.0
            )

            # Correlation between score and forward return
            correlation = 0.0
            if len(stats.score_return_pairs) >= 10:
                scores_arr = np.array([p[0] for p in stats.score_return_pairs])
                returns_arr = np.array([p[1] for p in stats.score_return_pairs])
                if np.std(scores_arr) > 0 and np.std(returns_arr) > 0:
                    correlation = float(np.corrcoef(scores_arr, returns_arr)[0, 1])

            # Hit rate: of positive-score trades, what % had positive returns
            hit_rate = 0.0
            if n_positive > 0:
                hits = sum(1 for r in stats.positive_returns if r > 0)
                hit_rate = (hits / n_positive) * 100

            results.append({
                'indicator': key,
                'n_positive': n_positive,
                'n_zero': n_zero,
                'fire_rate': round(fire_rate, 1),
                'avg_score': round(float(avg_score_positive), 3),
                'avg_return_positive': round(float(avg_return_positive), 3),
                'avg_return_zero': round(float(avg_return_zero), 3),
                'lift': round(float(lift), 3),
                'correlation': round(float(correlation), 4),
                'hit_rate': round(float(hit_rate), 1),
            })

        # Sort by absolute lift descending
        results.sort(key=lambda x: abs(x['lift']), reverse=True)
        return results

    @staticmethod
    def _print_report(results: List[Dict], total_observations: int) -> None:
        """Print impact report to console."""
        print("\n" + "=" * 120)
        print("INDICATOR IMPACT REPORT")
        print("=" * 120)
        print(f"Total symbol-date observations: {total_observations:,}")
        print()

        header = (
            f"{'Indicator':<30} {'Fires':>7} {'Fire%':>6} "
            f"{'AvgScore':>9} {'Ret(+)':>8} {'Ret(0)':>8} "
            f"{'Lift':>8} {'Corr':>7} {'Hit%':>6}"
        )
        print(header)
        print("-" * 120)

        for r in results:
            print(
                f"{r['indicator']:<30} {r['n_positive']:>7,} {r['fire_rate']:>5.1f}% "
                f"{r['avg_score']:>9.3f} {r['avg_return_positive']:>+7.3f}% "
                f"{r['avg_return_zero']:>+7.3f}% {r['lift']:>+7.3f}% "
                f"{r['correlation']:>+7.4f} {r['hit_rate']:>5.1f}%"
            )

        print("-" * 120)
        print()

    @staticmethod
    def _export_csv(results: List[Dict], output_dir: str = "src/logs") -> str:
        """Export impact results to CSV."""
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y-%m-%d')
        csv_path = os.path.join(output_dir, f"indicator_impact_{timestamp}.csv")

        fieldnames = [
            'indicator', 'n_positive', 'n_zero', 'fire_rate',
            'avg_score', 'avg_return_positive', 'avg_return_zero',
            'lift', 'correlation', 'hit_rate',
        ]

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        print(f"CSV exported to: {csv_path}")
        return csv_path
