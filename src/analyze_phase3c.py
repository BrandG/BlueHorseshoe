#!/usr/bin/env python3
"""
Phase 3C Results Analysis - MACD Indicators

Analyzes the Phase 3C backtest data (MACD and MACD_SIGNAL testing).
NOTE: Without the test run log, we can't segment by specific configurations,
but we can analyze overall performance vs baseline.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

PHASE2_BASELINE_SHARPE = 0.310

def build_daily_returns(trades_df):
    """
    Build daily portfolio returns from individual trades.
    Allocate all trade returns to their exit dates.
    """
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


def analyze_phase3c_data(csv_path):
    """Analyze Phase 3C backtest data."""
    df = pd.read_csv(csv_path)

    print(f"\n✓ Loaded {len(df)} total records")

    # Filter out NO_ENTRY trades for statistics
    traded_df = df[df['outcome'] != 'NO_ENTRY'].copy()
    total_trades = len(traded_df)

    if total_trades == 0:
        print("❌ No trades with entries found")
        return None

    # Basic statistics
    wins = len(traded_df[traded_df['outcome'] == 'WIN'])
    losses = len(traded_df[traded_df['outcome'] == 'LOSS'])
    timeouts = len(traded_df[traded_df['outcome'] == 'TIMEOUT'])
    win_rate = wins / total_trades if total_trades > 0 else 0

    # Build daily returns and calculate Sharpe
    daily_returns = build_daily_returns(df)
    sharpe = calculate_sharpe_ratio(daily_returns)

    # P&L statistics
    total_pnl = traded_df['profit_loss'].sum()
    avg_trade_pnl = traded_df['profit_loss'].mean()

    winners = traded_df[traded_df['outcome'] == 'WIN']
    losers = traded_df[traded_df['outcome'] == 'LOSS']

    avg_win = winners['profit_loss'].mean() if len(winners) > 0 else 0
    avg_loss = losers['profit_loss'].mean() if len(losers) > 0 else 0

    profit_factor = abs(winners['profit_loss'].sum() / losers['profit_loss'].sum()) if len(losers) > 0 and losers['profit_loss'].sum() != 0 else 0

    # Date range analysis
    unique_dates = df['date'].nunique()
    date_range_start = df['date'].min()
    date_range_end = df['date'].max()

    # Score distribution
    score_stats = traded_df['score'].describe()

    return {
        'total_records': len(df),
        'total_trades': total_trades,
        'no_entries': len(df[df['outcome'] == 'NO_ENTRY']),
        'wins': wins,
        'losses': losses,
        'timeouts': timeouts,
        'win_rate': win_rate,
        'sharpe_ratio': sharpe,
        'total_pnl': total_pnl,
        'avg_trade_pnl': avg_trade_pnl,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'profit_factor': profit_factor,
        'beats_baseline': sharpe > PHASE2_BASELINE_SHARPE,
        'unique_test_dates': unique_dates,
        'date_range_start': date_range_start,
        'date_range_end': date_range_end,
        'score_mean': score_stats['mean'],
        'score_std': score_stats['std'],
        'score_min': score_stats['min'],
        'score_max': score_stats['max']
    }


def estimate_completion_status(unique_dates):
    """
    Estimate if Phase 3C completed based on unique test dates.

    Expected: 2 indicators × 4 weights × 20 runs = 160 backtests
    Each backtest tests on a random date from 2024-01-01 to 2026-01-27.
    With 160 random dates drawn from ~2 years, we expect ~140-155 unique dates
    (accounting for some collisions).
    """
    expected_backtests = 160

    # With 160 random draws from ~500 business days, estimate unique dates
    # Using birthday paradox approximation
    total_days = 500  # Approximate business days in 2-year range

    # Expected unique dates after n draws: total_days * (1 - (1 - 1/total_days)^n)
    expected_unique = total_days * (1 - (1 - 1/total_days) ** expected_backtests)

    completion_pct = (unique_dates / expected_unique) * 100

    return {
        'expected_backtests': expected_backtests,
        'unique_dates': unique_dates,
        'expected_unique_dates': int(expected_unique),
        'estimated_completion': completion_pct
    }


def generate_report(results, completion_status):
    """Generate summary report."""
    print("\n" + "="*80)
    print("PHASE 3C RESULTS ANALYSIS - MACD INDICATORS")
    print("="*80)
    print(f"Baseline (Phase 2): Sharpe Ratio = {PHASE2_BASELINE_SHARPE:.3f}")
    print("Testing: MACD and MACD_SIGNAL indicators")
    print("\nNOTE: Without test run log, cannot segment by specific configurations")
    print("      Analyzing overall aggregate performance")
    print("="*80)

    print("\n📊 DATA SUMMARY")
    print("-" * 80)
    print(f"Total records:          {results['total_records']:,}")
    print(f"Unique test dates:      {results['unique_test_dates']}")
    print(f"Date range:             {results['date_range_start']} to {results['date_range_end']}")
    print(f"Total trades executed:  {results['total_trades']:,}")
    print(f"No entries (limit):     {results['no_entries']:,}")

    print("\n📈 COMPLETION ESTIMATE")
    print("-" * 80)
    print(f"Expected backtests:     {completion_status['expected_backtests']}")
    print(f"Expected unique dates:  ~{completion_status['expected_unique_dates']}")
    print(f"Actual unique dates:    {completion_status['unique_dates']}")
    print(f"Estimated completion:   {completion_status['estimated_completion']:.0f}%")

    if completion_status['estimated_completion'] >= 90:
        print("✓ Likely completed or nearly completed (~90%+)")
    elif completion_status['estimated_completion'] >= 70:
        print("⚠ Partially completed (~70-90%)")
    else:
        print("❌ Significantly incomplete (<70%)")

    print("\n💰 PERFORMANCE METRICS")
    print("-" * 80)
    print(f"Win rate:               {results['win_rate']:.2%}")
    print(f"Wins:                   {results['wins']:,}")
    print(f"Losses:                 {results['losses']:,}")
    print(f"Timeouts:               {results['timeouts']:,}")
    print(f"")
    print(f"Total P&L:              {results['total_pnl']:+.2f}%")
    print(f"Avg trade P&L:          {results['avg_trade_pnl']:+.3f}%")
    print(f"Avg win:                {results['avg_win']:+.2f}%")
    print(f"Avg loss:               {results['avg_loss']:+.2f}%")
    print(f"Profit factor:          {results['profit_factor']:.2f}")

    print("\n🎯 SHARPE RATIO")
    print("-" * 80)
    print(f"Sharpe ratio:           {results['sharpe_ratio']:.3f}")
    print(f"Baseline (Phase 2):     {PHASE2_BASELINE_SHARPE:.3f}")

    if results['beats_baseline']:
        improvement = results['sharpe_ratio'] - PHASE2_BASELINE_SHARPE
        pct_improvement = (improvement / PHASE2_BASELINE_SHARPE) * 100
        print(f"Result:                 ✓ BEATS BASELINE by {improvement:.3f} ({pct_improvement:+.0f}%)")
    else:
        decline = PHASE2_BASELINE_SHARPE - results['sharpe_ratio']
        pct_decline = (decline / PHASE2_BASELINE_SHARPE) * 100
        print(f"Result:                 ✗ Below baseline by {decline:.3f} ({pct_decline:.0f}%)")

    print("\n📊 SCORE DISTRIBUTION")
    print("-" * 80)
    print(f"Mean score:             {results['score_mean']:.2f}")
    print(f"Std dev:                {results['score_std']:.2f}")
    print(f"Range:                  {results['score_min']:.1f} - {results['score_max']:.1f}")

    print("\n" + "="*80)
    print("RECOMMENDATIONS")
    print("="*80)

    if completion_status['estimated_completion'] < 90:
        print("\n⚠️  Testing appears incomplete:")
        print(f"    - Only ~{completion_status['estimated_completion']:.0f}% of expected backtests")
        print("    - Results may not be representative")
        print("    - Recommendation: Re-run Phase 3C for complete data")

    if results['beats_baseline']:
        improvement = results['sharpe_ratio'] - PHASE2_BASELINE_SHARPE
        pct_improvement = (improvement / PHASE2_BASELINE_SHARPE) * 100
        print(f"\n✓ MACD indicators show promise:")
        print(f"  - Aggregate Sharpe: {results['sharpe_ratio']:.3f} (+{pct_improvement:.0f}% vs baseline)")
        print(f"  - Win rate: {results['win_rate']:.1%}")
        print(f"  - Profit factor: {results['profit_factor']:.2f}")
        print(f"\n  However, without configuration segmentation:")
        print(f"  - Cannot determine optimal weights")
        print(f"  - Cannot compare MACD vs MACD_SIGNAL")
        print(f"  - Recommendation: Re-run with proper logging OR deploy cautiously")
    else:
        print(f"\n✗ MACD indicators underperform baseline:")
        print(f"  - Sharpe: {results['sharpe_ratio']:.3f} vs {PHASE2_BASELINE_SHARPE:.3f} baseline")
        print(f"  - Recommendation: Do NOT deploy to production")
        print(f"  - Keep existing 11-indicator configuration")

    print("\n" + "="*80)


def main():
    print("\n" + "#"*80)
    print("# PHASE 3C RESULTS ANALYSIS - MACD INDICATORS")
    print("#"*80)
    print()

    csv_path = 'src/logs/backtest_log.csv'

    if not Path(csv_path).exists():
        print(f"❌ File not found: {csv_path}")
        return

    print(f"Analyzing: {csv_path}")

    results = analyze_phase3c_data(csv_path)

    if not results:
        print("❌ No results to analyze")
        return

    completion_status = estimate_completion_status(results['unique_test_dates'])

    generate_report(results, completion_status)

    # Save summary to CSV
    summary_df = pd.DataFrame([{
        'indicator_group': 'MACD+MACD_SIGNAL',
        'sharpe_ratio': results['sharpe_ratio'],
        'win_rate': results['win_rate'],
        'total_pnl': results['total_pnl'],
        'total_trades': results['total_trades'],
        'avg_win': results['avg_win'],
        'avg_loss': results['avg_loss'],
        'profit_factor': results['profit_factor'],
        'beats_baseline': results['beats_baseline'],
        'estimated_completion': completion_status['estimated_completion']
    }])

    output_file = 'src/logs/phase3c_analysis.csv'
    summary_df.to_csv(output_file, index=False)
    print(f"\n✓ Summary saved to: {output_file}\n")


if __name__ == '__main__':
    main()
