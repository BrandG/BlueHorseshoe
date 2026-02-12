#!/usr/bin/env python3
"""
PSAR 0.5x Combined Analysis (50 total runs: 20 original + 30 retest)

Combines data from:
1. Original Q3 testing: phase3a_backtest_log.csv (20 runs)
2. Retest: backtest_log.csv (30 runs)
"""

import pandas as pd
import numpy as np
from pathlib import Path
import re

PHASE2_BASELINE_SHARPE = 0.310
MIN_TRADES_THRESHOLD = 30

# Retest dates (30 runs from psar_05_retest.log)
RETEST_DATES = [
    '2024-10-12', '2025-03-06', '2025-01-12', '2025-11-23',
    '2024-11-08', '2025-08-22', '2024-12-20', '2025-12-14',
    '2024-03-23', '2025-01-31', '2025-12-10', '2025-04-24',
    '2025-09-01', '2025-05-16', '2025-03-06', '2025-11-22',
    '2025-10-19', '2025-03-26', '2024-03-25', '2024-12-27',
    '2024-12-20', '2024-02-28', '2025-10-15', '2025-04-21',
    '2025-02-26', '2024-06-28', '2025-09-03', '2025-05-25',
    '2024-03-14', '2024-05-26'
]

# Original Q3 PSAR 0.5x dates (20 runs from phase3e_q3_parallel.log)
ORIGINAL_Q3_PSAR_DATES = [
    '2024-05-02', '2024-06-30', '2024-10-08', '2025-02-04',
    '2024-06-24', '2024-01-14', '2024-08-13', '2025-10-04',
    '2024-04-26', '2025-03-02', '2024-10-31', '2025-12-12',
    '2025-05-12', '2024-09-28', '2025-11-29', '2024-12-23',
    '2024-02-22', '2024-08-05', '2024-06-15', '2024-01-13'
]


def load_combined_data():
    """Load and combine data from both test runs."""

    # Load original Q3 data
    df_original = pd.read_csv('src/logs/phase3a_backtest_log.csv')
    original_psar = df_original[df_original['date'].isin(ORIGINAL_Q3_PSAR_DATES)].copy()

    # Load retest data
    df_retest = pd.read_csv('src/logs/backtest_log.csv')
    retest_psar = df_retest[df_retest['date'].isin(RETEST_DATES)].copy()

    # Combine
    combined = pd.concat([original_psar, retest_psar], ignore_index=True)

    print(f"✓ Original Q3 PSAR 0.5x: {len(original_psar)} trades from 20 runs")
    print(f"✓ Retest PSAR 0.5x: {len(retest_psar)} trades from 30 runs")
    print(f"✓ Combined total: {len(combined)} trades from 50 runs")
    print()

    return combined, original_psar, retest_psar


def build_daily_returns(trades_df):
    """Build daily portfolio returns from individual trades."""
    if len(trades_df) == 0:
        return pd.Series(dtype=float)

    # Filter out NO_ENTRY trades
    trades_df = trades_df[trades_df['outcome'] != 'NO_ENTRY'].copy()

    if len(trades_df) == 0:
        return pd.Series(dtype=float)

    # Parse dates
    trades_df['entry_date'] = pd.to_datetime(trades_df['date'])
    trades_df['exit_date'] = pd.to_datetime(trades_df['exit_date'])

    # Get date range
    min_date = trades_df['entry_date'].min()
    max_date = trades_df['exit_date'].max()

    # Create daily date range (business days only)
    date_range = pd.date_range(start=min_date, end=max_date, freq='B')
    daily_returns = pd.Series(0.0, index=date_range)

    # Allocate each trade's return to its exit date
    for _, trade in trades_df.iterrows():
        exit_date = trade['exit_date']
        if exit_date in daily_returns.index:
            daily_returns[exit_date] += trade['profit_loss']

    return daily_returns


def calculate_sharpe_ratio(daily_returns):
    """Calculate Sharpe ratio from daily portfolio returns."""
    if len(daily_returns) == 0:
        return 0.0

    if daily_returns.std() == 0:
        return 0.0

    mean_daily_return = daily_returns.mean()
    std_daily_return = daily_returns.std()

    # Annualized Sharpe ratio
    sharpe = (mean_daily_return / std_daily_return) * np.sqrt(252)

    return sharpe


def analyze_dataset(df, label):
    """Analyze a single dataset."""
    if len(df) == 0:
        return None

    # Filter out NO_ENTRY trades for stats
    traded_df = df[df['outcome'] != 'NO_ENTRY']
    total_trades = len(traded_df)

    if total_trades == 0:
        return None

    wins = len(traded_df[traded_df['outcome'] == 'WIN'])
    losses = len(traded_df[traded_df['outcome'] == 'LOSS'])
    timeouts = len(traded_df[traded_df['outcome'] == 'TIMEOUT'])
    win_rate = wins / total_trades if total_trades > 0 else 0

    # Build daily returns and calculate Sharpe
    daily_returns = build_daily_returns(df)
    sharpe = calculate_sharpe_ratio(daily_returns)

    # Total P&L
    total_pnl = traded_df['profit_loss'].sum()
    avg_win = traded_df[traded_df['outcome'] == 'WIN']['profit_loss'].mean() if wins > 0 else 0
    avg_loss = traded_df[traded_df['outcome'] == 'LOSS']['profit_loss'].mean() if losses > 0 else 0

    return {
        'label': label,
        'total_trades': total_trades,
        'wins': wins,
        'losses': losses,
        'timeouts': timeouts,
        'win_rate': win_rate,
        'sharpe_ratio': sharpe,
        'total_pnl': total_pnl,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'statistically_valid': total_trades >= MIN_TRADES_THRESHOLD,
        'beats_baseline': sharpe > PHASE2_BASELINE_SHARPE
    }


def main():
    print("\n" + "="*80)
    print("PSAR 0.5x COMBINED ANALYSIS (50 TOTAL RUNS)")
    print("="*80)
    print()

    # Load data
    combined, original, retest = load_combined_data()

    # Analyze each dataset
    results = []

    original_stats = analyze_dataset(original, "Original Q3 (20 runs)")
    if original_stats:
        results.append(original_stats)

    retest_stats = analyze_dataset(retest, "Retest (30 runs)")
    if retest_stats:
        results.append(retest_stats)

    combined_stats = analyze_dataset(combined, "Combined (50 runs)")
    if combined_stats:
        results.append(combined_stats)

    # Display results
    print("="*80)
    print("RESULTS COMPARISON")
    print("="*80)
    print()

    for stats in results:
        print(f"{stats['label']}:")
        print(f"  Trades:      {stats['total_trades']:4d} (Valid: {stats['statistically_valid']})")
        print(f"  Win Rate:    {stats['win_rate']:6.1%}")
        print(f"  Sharpe:      {stats['sharpe_ratio']:7.3f} {'✅' if stats['beats_baseline'] else '❌'}")
        print(f"  Total P&L:   {stats['total_pnl']:7.2f}%")
        print(f"  Avg Win:     {stats['avg_win']:+6.2f}%")
        print(f"  Avg Loss:    {stats['avg_loss']:+6.2f}%")
        print()

    # Final recommendation
    print("="*80)
    print("RECOMMENDATION")
    print("="*80)
    print()

    if combined_stats:
        if combined_stats['beats_baseline'] and combined_stats['statistically_valid']:
            improvement = combined_stats['sharpe_ratio'] - PHASE2_BASELINE_SHARPE
            pct_improvement = (improvement / PHASE2_BASELINE_SHARPE) * 100

            print(f"✅ PSAR 0.5x VALIDATED")
            print(f"   Sharpe: {combined_stats['sharpe_ratio']:.3f} (baseline: {PHASE2_BASELINE_SHARPE:.3f})")
            print(f"   Improvement: +{improvement:.3f} (+{pct_improvement:.0f}%)")
            print(f"   Trades: {combined_stats['total_trades']} (≥{MIN_TRADES_THRESHOLD} required)")
            print(f"   Win Rate: {combined_stats['win_rate']:.1%}")
            print()
            print("   This indicator is statistically valid and beats the baseline.")
            print("   It is a strong candidate for deployment.")
        else:
            print(f"❌ PSAR 0.5x DOES NOT MEET CRITERIA")
            if not combined_stats['statistically_valid']:
                print(f"   Reason: Insufficient trades ({combined_stats['total_trades']} < {MIN_TRADES_THRESHOLD})")
            if not combined_stats['beats_baseline']:
                print(f"   Reason: Does not beat baseline (Sharpe {combined_stats['sharpe_ratio']:.3f} ≤ {PHASE2_BASELINE_SHARPE:.3f})")

    print()
    print("="*80)

    # Save results
    results_df = pd.DataFrame(results)
    output_file = 'src/logs/psar_05_combined_analysis.csv'
    results_df.to_csv(output_file, index=False)
    print(f"\n✓ Results saved to: {output_file}\n")


if __name__ == '__main__':
    main()
