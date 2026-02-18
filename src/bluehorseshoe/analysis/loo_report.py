"""
loo_report.py

Generates output from LOO weight analysis results:
- Console summary table ranked by P&L contribution
- CSV export with full stats per indicator
- Weight suggestions based on P&L ranking
"""

import csv
import os
from datetime import datetime
from typing import Dict, Any

from bluehorseshoe.analysis.loo_analyzer import IndicatorStats


def _calc_derived_stats(stats: IndicatorStats, baseline: IndicatorStats) -> Dict[str, Any]:
    """Calculate derived statistics for an indicator."""
    avg_pnl = stats.total_pnl / stats.trade_count if stats.trade_count > 0 else 0.0
    win_rate = (stats.win_count / stats.trade_count * 100) if stats.trade_count > 0 else 0.0

    # P&L delta: positive means removing this indicator HURT (indicator helps)
    # negative means removing this indicator HELPED (indicator hurts)
    baseline_avg = baseline.total_pnl / baseline.trade_count if baseline.trade_count > 0 else 0.0
    pnl_delta = baseline_avg - avg_pnl  # baseline - LOO = indicator contribution

    return {
        'total_pnl': stats.total_pnl,
        'avg_pnl': avg_pnl,
        'trade_count': stats.trade_count,
        'win_count': stats.win_count,
        'win_rate': win_rate,
        'pnl_delta': pnl_delta,
    }


def _suggest_weight(pnl_delta: float) -> float:
    """
    Suggest a weight multiplier based on P&L delta.

    pnl_delta > 0 means the indicator helps (removing it hurts P&L).
    pnl_delta < 0 means the indicator hurts (removing it helps P&L).
    """
    if pnl_delta > 0.5:
        return 2.0
    if pnl_delta > 0.2:
        return 1.5
    if pnl_delta > -0.1:
        return 1.0
    if pnl_delta > -0.3:
        return 0.5
    return 0.0


def print_console_report(results: Dict[str, Any]) -> None:
    """Print a formatted console summary of LOO analysis results."""
    baseline = results['baseline_stats']
    indicator_stats = results['indicator_stats']
    dates_analyzed = results['dates_analyzed']
    config = results['config']

    print("\n" + "=" * 90)
    print("LOO WEIGHT ANALYSIS REPORT")
    print("=" * 90)
    print(f"Dates analyzed: {len(dates_analyzed)} ({dates_analyzed[0]} to {dates_analyzed[-1]})")
    print(f"Config: top_n={config.top_n}, hold_days={config.hold_days}, interval={config.interval_days}d")
    print()

    # Baseline summary
    baseline_avg = baseline.total_pnl / baseline.trade_count if baseline.trade_count > 0 else 0.0
    baseline_wr = (baseline.win_count / baseline.trade_count * 100) if baseline.trade_count > 0 else 0.0
    print(f"BASELINE (all indicators): {baseline.trade_count} trades | "
          f"Total P&L: {baseline.total_pnl:.2f}% | Avg P&L: {baseline_avg:.2f}% | "
          f"Win Rate: {baseline_wr:.1f}%")
    print()

    # Build ranked list
    ranked = []
    for key, stats in indicator_stats.items():
        derived = _calc_derived_stats(stats, baseline)
        ranked.append((key, stats, derived))

    # Sort by P&L delta descending (most helpful indicators first)
    ranked.sort(key=lambda x: x[2]['pnl_delta'], reverse=True)

    # Print table header
    print(f"{'Indicator':<35} {'Delta':>8} {'LOO Avg':>8} {'LOO Tot':>9} {'Trades':>7} "
          f"{'Win%':>6} {'Suggested':>9}")
    print("-" * 90)

    for key, stats, derived in ranked:
        suggested = _suggest_weight(derived['pnl_delta'])
        delta_str = f"{derived['pnl_delta']:+.3f}%"
        print(f"{key:<35} {delta_str:>8} {derived['avg_pnl']:>7.2f}% "
              f"{derived['total_pnl']:>8.2f}% {derived['trade_count']:>7} "
              f"{derived['win_rate']:>5.1f}% {suggested:>9.1f}")

    print("-" * 90)
    print()
    print("Delta = Baseline_Avg_PnL - LOO_Avg_PnL")
    print("  Positive delta: removing this indicator HURTS P&L (indicator is HELPFUL)")
    print("  Negative delta: removing this indicator HELPS P&L (indicator is HARMFUL)")
    print()

    # Top helpers and hurters
    helpers = [(k, d) for k, _, d in ranked if d['pnl_delta'] > 0.1]
    hurters = [(k, d) for k, _, d in ranked if d['pnl_delta'] < -0.1]

    if helpers:
        print("TOP HELPERS (keep/increase weight):")
        for key, derived in helpers[:10]:
            print(f"  {key}: delta {derived['pnl_delta']:+.3f}%")

    if hurters:
        print("\nTOP HURTERS (reduce/remove weight):")
        for key, derived in hurters[-10:]:
            print(f"  {key}: delta {derived['pnl_delta']:+.3f}%")

    print()


def export_csv(results: Dict[str, Any], output_dir: str = "src/logs") -> str:
    """
    Export LOO analysis results to CSV.

    Returns the path to the saved CSV file.
    """
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y-%m-%d')
    csv_path = os.path.join(output_dir, f"loo_analysis_{timestamp}.csv")

    baseline = results['baseline_stats']
    indicator_stats = results['indicator_stats']

    fieldnames = [
        'indicator', 'pnl_delta', 'suggested_weight',
        'loo_total_pnl', 'loo_avg_pnl', 'loo_trade_count',
        'loo_win_count', 'loo_win_rate',
        'baseline_total_pnl', 'baseline_avg_pnl', 'baseline_trade_count',
        'baseline_win_rate',
    ]

    baseline_avg = baseline.total_pnl / baseline.trade_count if baseline.trade_count > 0 else 0.0
    baseline_wr = (baseline.win_count / baseline.trade_count * 100) if baseline.trade_count > 0 else 0.0

    # Build ranked list
    rows = []
    for key, stats in indicator_stats.items():
        derived = _calc_derived_stats(stats, baseline)
        suggested = _suggest_weight(derived['pnl_delta'])
        rows.append({
            'indicator': key,
            'pnl_delta': round(derived['pnl_delta'], 4),
            'suggested_weight': suggested,
            'loo_total_pnl': round(derived['total_pnl'], 4),
            'loo_avg_pnl': round(derived['avg_pnl'], 4),
            'loo_trade_count': derived['trade_count'],
            'loo_win_count': derived['win_count'],
            'loo_win_rate': round(derived['win_rate'], 2),
            'baseline_total_pnl': round(baseline.total_pnl, 4),
            'baseline_avg_pnl': round(baseline_avg, 4),
            'baseline_trade_count': baseline.trade_count,
            'baseline_win_rate': round(baseline_wr, 2),
        })

    # Sort by pnl_delta descending
    rows.sort(key=lambda x: x['pnl_delta'], reverse=True)

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"CSV exported to: {csv_path}")
    return csv_path
