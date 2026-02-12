#!/usr/bin/env python3
"""
Phase 3E Quarter 1 Results Analysis (ADX + Stochastic)

Analyzes trend/momentum indicators using proper daily portfolio returns
for Sharpe ratio calculation.
"""

import pandas as pd
import numpy as np
from pathlib import Path
import re

PHASE2_BASELINE_SHARPE = 0.310
MIN_TRADES_THRESHOLD = 30  # Minimum trades for statistical validity

# Map of indicators tested in Phase 3E Q1
PHASE3E_Q1_INDICATORS = {
    'ADX': 'Average Directional Index',
    'STOCHASTIC': 'Stochastic Oscillator'
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
        if 'Average Directional Index' in indicator_name:
            indicator_code = 'ADX'
        elif 'Stochastic Oscillator' in indicator_name:
            indicator_code = 'STOCHASTIC'

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
        'statistically_valid': total_trades >= MIN_TRADES_THRESHOLD,
        'beats_baseline': sharpe > PHASE2_BASELINE_SHARPE
    }


def generate_summary_report(results_df):
    """Generate summary report of Phase 3E Q1 testing."""
    print("\n" + "="*80)
    print("PHASE 3E QUARTER 1 RESULTS SUMMARY")
    print("="*80)
    print(f"Baseline (Phase 2): Sharpe Ratio = {PHASE2_BASELINE_SHARPE:.3f}")
    print("\nIndicators Tested: ADX (trend) + Stochastic (momentum)")
    print("="*80)
    print()

    # Analyze each indicator
    for indicator_code, indicator_name in PHASE3E_Q1_INDICATORS.items():
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
            is_valid = row['statistically_valid']
            beats = "✓" if row['beats_baseline'] else "✗"

            marker = "⭐" if row.name == best_idx else "  "
            validity = "" if is_valid else " [INVALID: <30 trades]"

            print(f"{marker} {weight}x: Sharpe={sharpe:6.3f} | Win={win_rate:5.1%} | "
                  f"PnL={total_pnl:7.2f}% | Trades={trades:4d} | Beats baseline: {beats}{validity}")

        if best_config['beats_baseline'] and best_config['statistically_valid']:
            improvement = best_config['sharpe_ratio'] - PHASE2_BASELINE_SHARPE
            pct_improvement = (improvement / PHASE2_BASELINE_SHARPE) * 100
            print(f"\n   🎯 WINNER: {best_config['weight']}x weight "
                  f"(Sharpe={best_config['sharpe_ratio']:.3f}, +{pct_improvement:.0f}%)")
        elif best_config['beats_baseline'] and not best_config['statistically_valid']:
            print(f"\n   ⚠️  Best is {best_config['weight']}x but INVALID (only {int(best_config['total_trades'])} trades, need ≥{MIN_TRADES_THRESHOLD})")
        else:
            print(f"\n   ❌ Best is {best_config['weight']}x but doesn't beat baseline")

    print("\n" + "="*80)
    print("RECOMMENDATIONS")
    print("="*80)

    # Find all configs that beat baseline AND are statistically valid
    winners = results_df[
        (results_df['beats_baseline'] == True) &
        (results_df['statistically_valid'] == True)
    ].sort_values('sharpe_ratio', ascending=False)

    # Count invalid results that beat baseline
    invalid_winners = results_df[
        (results_df['beats_baseline'] == True) &
        (results_df['statistically_valid'] == False)
    ]

    if len(invalid_winners) > 0:
        print(f"\n⚠️  {len(invalid_winners)} configuration(s) beat baseline but INVALID (<{MIN_TRADES_THRESHOLD} trades):")
        for _, row in invalid_winners.iterrows():
            indicator_name = PHASE3E_Q1_INDICATORS[row['indicator']]
            print(f"   - {indicator_name} at {row['weight']}x "
                  f"(Sharpe: {row['sharpe_ratio']:.3f}, only {int(row['total_trades'])} trades - statistically unreliable)")

    if len(winners) == 0:
        print("\n❌ No VALID configurations beat the Phase 2 baseline")
        print("   Recommendation: Do NOT deploy any Q1 indicators")
        print("   Proceed to Quarter 2 testing")
    else:
        print(f"\n✓ {len(winners)} VALID configuration(s) beat baseline:\n")
        for idx, (_, row) in enumerate(winners.iterrows(), 1):
            indicator_name = PHASE3E_Q1_INDICATORS[row['indicator']]
            improvement = row['sharpe_ratio'] - PHASE2_BASELINE_SHARPE
            pct_improvement = (improvement / PHASE2_BASELINE_SHARPE) * 100
            print(f"  {idx}. {indicator_name} at {row['weight']}x "
                  f"(Sharpe: {row['sharpe_ratio']:.3f}, +{pct_improvement:.0f}%, "
                  f"Win: {row['win_rate']:.1%}, Trades: {int(row['total_trades'])})")

        print("\n   Recommendation: Note these winners and proceed to Q2")
        print("   Deploy all Phase 3E winners together after Q4 completes")

    print("\n" + "="*80)


def main():
    print("\n" + "#"*80)
    print("# PHASE 3E QUARTER 1 RESULTS ANALYSIS")
    print("# ADX (Average Directional Index) + Stochastic Oscillator")
    print("#"*80)
    print()

    # Parse test log to build date-to-config mapping
    log_path = 'src/logs/phase3e_q1.log'
    print("Parsing test log to extract configurations...")
    config_map = parse_test_log(log_path)
    print(f"✓ Mapped {len(config_map)} test dates to configurations\n")

    # Load and segment CSV data
    csv_path = 'src/logs/phase3a_backtest_log.csv'
    df = load_and_segment_data(csv_path, config_map)

    if len(df) == 0:
        print("❌ No data to analyze")
        return

    print()

    # Analyze each configuration
    results = []
    for indicator in PHASE3E_Q1_INDICATORS.keys():
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
    output_file = 'src/logs/phase3e_q1_analysis.csv'
    results_df.to_csv(output_file, index=False)
    print(f"\n✓ Detailed results saved to: {output_file}\n")


if __name__ == '__main__':
    main()
