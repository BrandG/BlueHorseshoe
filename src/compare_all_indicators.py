#!/usr/bin/env python3
"""
Comprehensive Indicator Comparison

Combines Phase 3A and 3B corrected results to show all indicators
ranked by Sharpe ratio performance.
"""

import pandas as pd

PHASE2_BASELINE_SHARPE = 0.310

def main():
    # Load corrected results
    phase3a = pd.read_csv('src/logs/phase3a_analysis_corrected.csv')
    phase3b = pd.read_csv('src/logs/phase3b_analysis_corrected.csv')

    # Combine
    all_results = pd.concat([phase3a, phase3b], ignore_index=True)

    # Map indicator codes to full names
    indicator_names = {
        'RS': 'Relative Strength (RS)',
        'GAP': 'Gap Analysis',
        'VWAP': 'VWAP',
        'TTM': 'TTM Squeeze',
        'AROON': 'Aroon Indicator',
        'KELTNER': 'Keltner Channels',
        'FORCE': "Elder's Force Index",
        'AD': 'A/D Line'
    }

    all_results['indicator_name'] = all_results['indicator'].map(indicator_names)

    print("\n" + "="*80)
    print("COMPREHENSIVE INDICATOR COMPARISON (CORRECTED SHARPE RATIOS)")
    print("="*80)
    print(f"Baseline (Phase 2): Sharpe Ratio = {PHASE2_BASELINE_SHARPE:.3f}")
    print("="*80)
    print()

    # Show all configurations that beat baseline, sorted by Sharpe
    winners = all_results[all_results['beats_baseline'] == True].sort_values('sharpe_ratio', ascending=False)

    print(f"TOP PERFORMERS ({len(winners)} configurations beat baseline):\n")
    print(f"{'Rank':<5} {'Indicator':<25} {'Weight':<8} {'Sharpe':<8} {'Improvement':<12} {'Win%':<8} {'Trades':<8} {'Phase':<8}")
    print("-" * 100)

    for idx, (_, row) in enumerate(winners.iterrows(), 1):
        improvement = row['sharpe_ratio'] - PHASE2_BASELINE_SHARPE
        pct_improvement = (improvement / PHASE2_BASELINE_SHARPE) * 100
        phase = "3A" if row['indicator'] in ['RS', 'GAP', 'VWAP'] else "3B"

        print(f"{idx:<5} {row['indicator_name']:<25} {row['weight']:.1f}x{'':<5} "
              f"{row['sharpe_ratio']:<8.3f} +{pct_improvement:<10.0f}% "
              f"{row['win_rate']:<7.1%} {int(row['total_trades']):<8} {phase:<8}")

    print("\n" + "="*80)
    print("BEST WEIGHT PER INDICATOR")
    print("="*80)
    print()

    # For each indicator, show best weight
    for indicator_code in sorted(all_results['indicator'].unique()):
        indicator_results = all_results[all_results['indicator'] == indicator_code]
        best = indicator_results.loc[indicator_results['sharpe_ratio'].idxmax()]
        indicator_name = indicator_names[indicator_code]
        phase = "3A" if indicator_code in ['RS', 'GAP', 'VWAP'] else "3B"

        status = "✓ Beats baseline" if best['beats_baseline'] else "✗ Below baseline"
        improvement = ((best['sharpe_ratio'] - PHASE2_BASELINE_SHARPE) / PHASE2_BASELINE_SHARPE * 100)

        print(f"{indicator_name:<25} Phase {phase}:")
        print(f"  Best: {best['weight']:.1f}x | Sharpe: {best['sharpe_ratio']:.3f} (+{improvement:+.0f}%) | "
              f"Win: {best['win_rate']:.1%} | Trades: {int(best['total_trades'])} | {status}")
        print()

    print("="*80)
    print("CURRENT PRODUCTION DEPLOYMENT")
    print("="*80)
    print()

    # Show currently deployed weights
    deployed = {
        'RS': 1.0,
        'GAP': 1.5,
        'VWAP': 2.0,
        'TTM': 2.0,
        'AROON': 1.0,
        'KELTNER': 1.5,
        'FORCE': 1.5,
        'AD': 1.0
    }

    deployed_sharpes = []
    for indicator_code, weight in deployed.items():
        result = all_results[(all_results['indicator'] == indicator_code) &
                            (all_results['weight'] == weight)]
        if not result.empty:
            sharpe = result.iloc[0]['sharpe_ratio']
            deployed_sharpes.append(sharpe)
            indicator_name = indicator_names[indicator_code]
            is_best = result.iloc[0]['sharpe_ratio'] == all_results[all_results['indicator'] == indicator_code]['sharpe_ratio'].max()
            marker = "⭐" if is_best else "  "
            print(f"{marker} {indicator_name:<25} {weight:.1f}x | Sharpe: {sharpe:.3f}")

    avg_sharpe = sum(deployed_sharpes) / len(deployed_sharpes)
    print(f"\nAverage Sharpe (deployed indicators): {avg_sharpe:.3f}")
    print(f"vs Baseline: {PHASE2_BASELINE_SHARPE:.3f} (+{((avg_sharpe - PHASE2_BASELINE_SHARPE) / PHASE2_BASELINE_SHARPE * 100):.0f}%)")

    print("\n" + "="*80)


if __name__ == '__main__':
    main()
