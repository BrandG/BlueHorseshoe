#!/usr/bin/env python3
"""
Phase 3B Results Analysis (CORRECTED SHARPE CALCULATION)

Properly calculates Sharpe ratio using daily portfolio returns rather than
individual trade returns with incorrect annualization.
"""

import pandas as pd
import numpy as np
from pathlib import Path
import re
from datetime import datetime, timedelta

PHASE2_BASELINE_SHARPE = 0.310

# Map of indicators tested in Phase 3B
PHASE3B_INDICATORS = {
    'TTM': 'TTM Squeeze',
    'AROON': 'Aroon Indicator',
    'KELTNER': 'Keltner Channels',
    'FORCE': "Elder's Force Index",
    'AD': 'A/D Line'
}


def parse_test_log(log_path):
    """Parse the test log to extract date-to-config mappings."""
    with open(log_path, 'r') as f:
        log_content = f.read()

    config_map = {}  # date -> (indicator, weight)
    pattern = r'Testing: (.+?) at ([\d.]+)x weight.*?(?=Testing:|$)'

    for match in re.finditer(pattern, log_content, re.DOTALL):
        indicator_name = match.group(1)
        weight = float(match.group(2))
        section = match.group(0)

        # Map indicator name to short code
        indicator_code = None
        if 'TTM Squeeze' in indicator_name:
            indicator_code = 'TTM'
        elif 'Aroon' in indicator_name:
            indicator_code = 'AROON'
        elif 'Keltner' in indicator_name:
            indicator_code = 'KELTNER'
        elif 'Force Index' in indicator_name:
            indicator_code = 'FORCE'
        elif 'A/D Line' in indicator_name:
            indicator_code = 'AD'

        if not indicator_code:
            continue

        # Extract all run dates from this section
        date_pattern = r'Run \d+/20: (\d{4}-\d{2}-\d{2})'
        for date_match in re.finditer(date_pattern, section):
            test_date = date_match.group(1)
            config_map[test_date] = (indicator_code, weight)

    return config_map


def load_and_segment_data(csv_path, config_map):
    """Load CSV and segment by indicator/weight based on date matching."""
    df = pd.read_csv(csv_path)

    # Add config columns
    df['indicator'] = None
    df['weight'] = None

    for idx, row in df.iterrows():
        test_date = str(row['date'])
        if test_date in config_map:
            indicator, weight = config_map[test_date]
            df.at[idx, 'indicator'] = indicator
            df.at[idx, 'weight'] = weight

    matched_df = df[df['indicator'].notna()].copy()

    print(f"✓ Loaded {len(df)} total records")
    print(f"✓ Matched {len(matched_df)} records to test configurations")
    if len(df) - len(matched_df) > 0:
        print(f"⚠ Could not match {len(df) - len(matched_df)} records")

    return matched_df


def build_daily_returns(trades_df):
    """
    Build daily portfolio returns from individual trades.

    Approach: Allocate all trade returns to their exit dates.
    This represents the actual realized daily P&L of the strategy.
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
            # Add this trade's return to the exit date
            daily_returns[exit_date] += trade['profit_loss']

    return daily_returns


def calculate_sharpe_ratio(daily_returns):
    """Calculate Sharpe ratio from daily portfolio returns."""
    if len(daily_returns) == 0:
        return 0.0

    # Use ALL days including zeros - they represent days with no realized P&L
    if daily_returns.std() == 0:
        return 0.0

    mean_daily_return = daily_returns.mean()
    std_daily_return = daily_returns.std()

    # Annualized Sharpe ratio
    # Since these are business daily returns, we can use sqrt(252)
    sharpe = (mean_daily_return / std_daily_return) * np.sqrt(252)

    return sharpe


def analyze_configuration(df, indicator, weight):
    """Analyze performance for a specific indicator at a specific weight."""
    config_df = df[(df['indicator'] == indicator) & (df['weight'] == weight)]

    if len(config_df) == 0:
        return None

    # Filter out NO_ENTRY trades for stats
    traded_df = config_df[config_df['outcome'] != 'NO_ENTRY']
    total_trades = len(traded_df)

    if total_trades == 0:
        return None

    wins = len(traded_df[traded_df['outcome'] == 'WIN'])
    losses = len(traded_df[traded_df['outcome'] == 'LOSS'])
    timeouts = len(traded_df[traded_df['outcome'] == 'TIMEOUT'])
    win_rate = wins / total_trades if total_trades > 0 else 0

    # Build daily returns and calculate Sharpe
    daily_returns = build_daily_returns(config_df)
    sharpe = calculate_sharpe_ratio(daily_returns)

    # Total P&L
    total_pnl = traded_df['profit_loss'].sum()
    avg_win = traded_df[traded_df['outcome'] == 'WIN']['profit_loss'].mean() if wins > 0 else 0
    avg_loss = traded_df[traded_df['outcome'] == 'LOSS']['profit_loss'].mean() if losses > 0 else 0

    return {
        'indicator': indicator,
        'weight': weight,
        'total_trades': total_trades,
        'wins': wins,
        'losses': losses,
        'timeouts': timeouts,
        'win_rate': win_rate,
        'sharpe_ratio': sharpe,
        'total_pnl': total_pnl,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'beats_baseline': sharpe > PHASE2_BASELINE_SHARPE
    }


def generate_summary_report(results_df):
    """Generate summary report of Phase 3B testing."""
    print("\n" + "="*80)
    print("PHASE 3B RESULTS SUMMARY (CORRECTED SHARPE CALCULATION)")
    print("="*80)
    print(f"Baseline (Phase 2): Sharpe Ratio = {PHASE2_BASELINE_SHARPE:.3f}")
    print("\nNOTE: Using proper daily portfolio returns for Sharpe calculation")
    print("="*80)
    print()

    # Analyze each indicator
    for indicator_code, indicator_name in PHASE3B_INDICATORS.items():
        indicator_results = results_df[results_df['indicator'] == indicator_code]

        if len(indicator_results) == 0:
            print(f"\n{indicator_name}: No data")
            continue

        print(f"\n{indicator_name}:")
        print("-" * 60)

        best_idx = indicator_results['sharpe_ratio'].idxmax()
        best_config = indicator_results.loc[best_idx]

        for _, row in indicator_results.sort_values('weight').iterrows():
            weight = row['weight']
            sharpe = row['sharpe_ratio']
            win_rate = row['win_rate']
            total_pnl = row['total_pnl']
            trades = row['total_trades']
            beats = "✓" if row['beats_baseline'] else "✗"

            marker = "⭐" if row.name == best_idx else "  "

            print(f"{marker} {weight}x: Sharpe={sharpe:6.3f} | Win={win_rate:5.1%} | "
                  f"PnL={total_pnl:7.2f}% | Trades={trades:4d} | Beats baseline: {beats}")

        if best_config['beats_baseline']:
            improvement = best_config['sharpe_ratio'] - PHASE2_BASELINE_SHARPE
            pct_improvement = (improvement / PHASE2_BASELINE_SHARPE) * 100
            print(f"\n   🎯 WINNER: {best_config['weight']}x weight "
                  f"(Sharpe={best_config['sharpe_ratio']:.3f}, +{pct_improvement:.0f}%)")
        else:
            print(f"\n   ❌ Best is {best_config['weight']}x but doesn't beat baseline")

    print("\n" + "="*80)
    print("RECOMMENDATIONS")
    print("="*80)

    # Find all configs that beat baseline
    winners = results_df[results_df['beats_baseline'] == True].sort_values('sharpe_ratio', ascending=False)

    if len(winners) == 0:
        print("\n❌ No configurations beat the Phase 2 baseline")
        print("   Recommendation: Keep current production weights")
    else:
        print(f"\n✓ {len(winners)} configurations beat baseline:\n")
        for idx, (_, row) in enumerate(winners.iterrows(), 1):
            indicator_name = PHASE3B_INDICATORS[row['indicator']]
            improvement = row['sharpe_ratio'] - PHASE2_BASELINE_SHARPE
            pct_improvement = (improvement / PHASE2_BASELINE_SHARPE) * 100
            print(f"  {idx}. {indicator_name} at {row['weight']}x "
                  f"(Sharpe: {row['sharpe_ratio']:.3f}, +{pct_improvement:.0f}%, "
                  f"Win: {row['win_rate']:.1%}, Trades: {int(row['total_trades'])})")

        print("\n   Recommendation: Deploy top performers to production")

    print("\n" + "="*80)


def main():
    print("\n" + "#"*80)
    print("# PHASE 3B RESULTS ANALYSIS (CORRECTED SHARPE CALCULATION)")
    print("#"*80)
    print()

    # Parse test log to build date-to-config mapping
    log_path = 'src/logs/phase3b_test_run.log'
    print("Parsing test log to extract configurations...")
    config_map = parse_test_log(log_path)
    print(f"✓ Mapped {len(config_map)} test dates to configurations\n")

    # Load and segment CSV data
    csv_path = 'src/logs/backtest_log_fixed.csv'
    df = load_and_segment_data(csv_path, config_map)

    if len(df) == 0:
        print("❌ No data to analyze")
        return

    print()

    # Analyze each configuration
    results = []
    for indicator in PHASE3B_INDICATORS.keys():
        for weight in [0.5, 1.0, 1.5, 2.0]:
            result = analyze_configuration(df, indicator, weight)
            if result:
                results.append(result)

    if not results:
        print("❌ No results generated")
        return

    results_df = pd.DataFrame(results)

    # Generate report
    generate_summary_report(results_df)

    # Save detailed results
    output_file = 'src/logs/phase3b_analysis_corrected.csv'
    results_df.to_csv(output_file, index=False)
    print(f"\n✓ Detailed results saved to: {output_file}\n")


if __name__ == '__main__':
    main()
