#!/usr/bin/env python3
"""
Phase 3A Results Analysis

Analyzes backtest results from Phase 3A isolated indicator testing to determine:
1. Which indicators show positive Sharpe ratios
2. Optimal weight multipliers for each indicator
3. Comparison against Phase 2 baseline (Sharpe: 0.310)
4. Best candidates for Phase 3B combination testing
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

# Phase 3 indicators with their configurations
PHASE3_INDICATORS = {
    'RS_MULTIPLIER': {'name': 'Relative Strength vs SPY', 'category': 'momentum'},
    'GAP_MULTIPLIER': {'name': 'Gap Analysis', 'category': 'price_action'},
    'VWAP_MULTIPLIER': {'name': 'VWAP', 'category': 'volume'},
    'TTM_SQUEEZE_MULTIPLIER': {'name': 'TTM Squeeze', 'category': 'trend'},
    'AROON_MULTIPLIER': {'name': 'Aroon Indicator', 'category': 'trend'},
    'KELTNER_MULTIPLIER': {'name': 'Keltner Channels', 'category': 'trend'},
    'FORCE_INDEX_MULTIPLIER': {'name': "Elder's Force Index", 'category': 'volume'},
    'AD_LINE_MULTIPLIER': {'name': 'A/D Line', 'category': 'volume'}
}

PHASE2_BASELINE_SHARPE = 0.310


def load_backtest_log(log_path='src/logs/backtest_log.csv'):
    """Load backtest results from CSV."""
    if not Path(log_path).exists():
        print(f"❌ Backtest log not found: {log_path}")
        return None

    df = pd.read_csv(log_path)
    print(f"✓ Loaded {len(df)} backtest records")
    return df


def parse_config_from_log(df):
    """Parse weight configurations from backtest log notes or metadata."""
    # Assuming the log has configuration info - adjust based on actual format
    # For now, we'll need to match by date ranges and infer from test sequence
    return df


def calculate_sharpe_ratio(returns):
    """Calculate Sharpe ratio from returns series."""
    if len(returns) == 0 or returns.std() == 0:
        return 0.0

    mean_return = returns.mean()
    std_return = returns.std()

    # Annualized Sharpe ratio (assuming daily returns)
    sharpe = (mean_return / std_return) * np.sqrt(252)
    return sharpe


def analyze_indicator_performance(df, indicator_code, weight):
    """Analyze performance for a specific indicator at a specific weight."""
    # Filter data for this indicator/weight combo
    # This assumes we can identify which rows belong to which test
    # You may need to adjust based on actual log format

    indicator_data = df  # Placeholder - filter appropriately

    if len(indicator_data) == 0:
        return None

    total_trades = len(indicator_data)
    wins = len(indicator_data[indicator_data['outcome'] == 'WIN'])
    losses = len(indicator_data[indicator_data['outcome'] == 'LOSS'])
    timeouts = len(indicator_data[indicator_data['outcome'] == 'TIMEOUT'])

    win_rate = wins / total_trades if total_trades > 0 else 0

    # Calculate returns
    returns = indicator_data['profit_loss'].values
    sharpe = calculate_sharpe_ratio(pd.Series(returns))

    total_pnl = returns.sum()
    avg_win = indicator_data[indicator_data['outcome'] == 'WIN']['profit_loss'].mean() if wins > 0 else 0
    avg_loss = indicator_data[indicator_data['outcome'] == 'LOSS']['profit_loss'].mean() if losses > 0 else 0

    return {
        'indicator': indicator_code,
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
    """Generate summary report of Phase 3A testing."""
    print("\n" + "="*80)
    print("PHASE 3A RESULTS SUMMARY")
    print("="*80)
    print(f"Baseline (Phase 2): Sharpe Ratio = {PHASE2_BASELINE_SHARPE:.3f}")
    print("="*80)
    print()

    # Group by indicator
    for indicator_code, info in PHASE3_INDICATORS.items():
        indicator_name = info['name']
        indicator_results = results_df[results_df['indicator'] == indicator_code]

        if len(indicator_results) == 0:
            print(f"\n{indicator_name}: No data")
            continue

        print(f"\n{indicator_name} ({info['category']}):")
        print("-" * 60)

        best_config = indicator_results.loc[indicator_results['sharpe_ratio'].idxmax()]

        for _, row in indicator_results.iterrows():
            weight = row['weight']
            sharpe = row['sharpe_ratio']
            win_rate = row['win_rate']
            beats = "✓" if row['beats_baseline'] else "✗"

            marker = "⭐" if row.name == best_config.name else "  "

            print(f"{marker} {weight}x: Sharpe={sharpe:6.3f} | Win Rate={win_rate:5.1%} | "
                  f"PnL=${row['total_pnl']:7.2f} | Beats Baseline: {beats}")

        if best_config['beats_baseline']:
            print(f"\n   🎯 WINNER: {best_config['weight']}x weight "
                  f"(Sharpe={best_config['sharpe_ratio']:.3f})")

    print("\n" + "="*80)
    print("PHASE 3B RECOMMENDATIONS")
    print("="*80)

    # Find all configs that beat baseline
    winners = results_df[results_df['beats_baseline'] == True].sort_values('sharpe_ratio', ascending=False)

    if len(winners) == 0:
        print("\n❌ No indicators beat the Phase 2 baseline")
        print("   Recommendation: Keep current 3-indicator configuration")
    else:
        print(f"\n✓ {len(winners)} configurations beat baseline:")
        print()
        for idx, row in winners.head(5).iterrows():
            indicator_name = PHASE3_INDICATORS[row['indicator']]['name']
            print(f"  {idx+1}. {indicator_name} at {row['weight']}x "
                  f"(Sharpe: {row['sharpe_ratio']:.3f}, +{(row['sharpe_ratio']-PHASE2_BASELINE_SHARPE):.3f})")

        print("\n   Recommendation: Test top performers in Phase 3B combination testing")

    print("\n" + "="*80)


def main():
    print("\n" + "#"*80)
    print("# PHASE 3A RESULTS ANALYSIS")
    print("#"*80)
    print()

    # Load data
    df = load_backtest_log()
    if df is None:
        return

    # Analyze each indicator at each weight
    results = []

    for indicator_code in PHASE3_INDICATORS.keys():
        for weight in [0.5, 1.0, 1.5, 2.0]:
            result = analyze_indicator_performance(df, indicator_code, weight)
            if result:
                results.append(result)

    if not results:
        print("❌ No results to analyze")
        return

    results_df = pd.DataFrame(results)

    # Generate reports
    generate_summary_report(results_df)

    # Save detailed results
    output_file = 'src/logs/phase3a_analysis.csv'
    results_df.to_csv(output_file, index=False)
    print(f"\n✓ Detailed results saved to: {output_file}")


if __name__ == '__main__':
    main()
