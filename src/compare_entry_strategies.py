#!/usr/bin/env python
"""
Compare Dynamic vs Fixed Entry Strategy

This script tests the same date with dynamic entry ON and OFF to show
the direct impact of the new strategy.

Usage:
    python src/compare_entry_strategies.py --date 2026-01-30 --symbols 100
"""
import argparse
import sys
from collections import defaultdict
from typing import Dict

from bluehorseshoe.analysis.backtest import Backtester
from bluehorseshoe.analysis.strategy import SwingTrader, StrategyContext
from bluehorseshoe.analysis import constants
from bluehorseshoe.core.container import create_app_container
from bluehorseshoe.core.symbols import get_symbol_name_list


def test_strategy(database, test_date: str, enable_dynamic: bool, sample_symbols: list):
    """Test with dynamic entry enabled or disabled."""

    # Temporarily override the flag
    original_flag = constants.ENABLE_DYNAMIC_ENTRY
    constants.ENABLE_DYNAMIC_ENTRY = enable_dynamic

    try:
        trader = SwingTrader(database=database)
        backtester = Backtester(database=database)

        print(f"\n  Testing with ENABLE_DYNAMIC_ENTRY = {enable_dynamic}")
        print(f"  Processing {len(sample_symbols)} symbols...")

        # Generate predictions
        ctx = StrategyContext(target_date=test_date)
        predictions = []

        for i, symbol in enumerate(sample_symbols):
            try:
                result = trader.process_symbol(symbol, ctx)
                if result:
                    predictions.append(result)
                if (i + 1) % 50 == 0:
                    print(f"    Progress: {i + 1}/{len(sample_symbols)}")
            except Exception:
                continue

        # Filter baseline predictions
        baseline_predictions = [
            p for p in predictions
            if p and p.get('baseline_score', 0) > 0
        ]

        print(f"  Found {len(baseline_predictions)} baseline candidates")

        if not baseline_predictions:
            return None

        # Sort by score and categorize
        baseline_predictions.sort(key=lambda x: x.get('baseline_score', 0), reverse=True)

        # Categorize by what the score WOULD be (for fair comparison)
        thresholds = constants.SIGNAL_STRENGTH_THRESHOLDS
        results = {
            'total': 0,
            'filled': 0,
            'wins': 0,
            'trades': 0,
            'pnl_sum': 0.0,
            'by_score_range': {
                f'EXTREME ({thresholds["EXTREME"]}+)': {'total': 0, 'filled': 0, 'wins': 0, 'trades': 0, 'pnl': 0},
                f'HIGH ({thresholds["HIGH"]}-{thresholds["EXTREME"]})': {'total': 0, 'filled': 0, 'wins': 0, 'trades': 0, 'pnl': 0},
                f'MEDIUM ({thresholds["MEDIUM"]}-{thresholds["HIGH"]})': {'total': 0, 'filled': 0, 'wins': 0, 'trades': 0, 'pnl': 0},
                f'LOW ({thresholds["LOW"]}-{thresholds["MEDIUM"]})': {'total': 0, 'filled': 0, 'wins': 0, 'trades': 0, 'pnl': 0},
                f'WEAK (<{thresholds["LOW"]})': {'total': 0, 'filled': 0, 'wins': 0, 'trades': 0, 'pnl': 0},
            }
        }

        for pred in baseline_predictions:
            setup = pred.get('baseline_setup', {})
            score = pred.get('baseline_score', 0)

            # Classify by score using actual thresholds (not by metadata, for fair comparison)
            thresholds = constants.SIGNAL_STRENGTH_THRESHOLDS
            if score >= thresholds['EXTREME']:
                score_range = f'EXTREME ({thresholds["EXTREME"]}+)'
            elif score >= thresholds['HIGH']:
                score_range = f'HIGH ({thresholds["HIGH"]}-{thresholds["EXTREME"]})'
            elif score >= thresholds['MEDIUM']:
                score_range = f'MEDIUM ({thresholds["MEDIUM"]}-{thresholds["HIGH"]})'
            elif score >= thresholds['LOW']:
                score_range = f'LOW ({thresholds["LOW"]}-{thresholds["MEDIUM"]})'
            else:
                score_range = f'WEAK (<{thresholds["LOW"]})'

            # Flatten for backtest
            pred['entry_price'] = setup.get('entry_price')
            pred['stop_loss'] = setup.get('stop_loss')
            pred['take_profit'] = setup.get('take_profit')

            if not pred['entry_price']:
                continue

            # Evaluate
            result = backtester.evaluate_prediction(pred, test_date)

            results['total'] += 1
            results['by_score_range'][score_range]['total'] += 1

            # Check if filled
            if result.get('entry') is not None:
                results['filled'] += 1
                results['by_score_range'][score_range]['filled'] += 1

                # Check if completed
                if result.get('exit_price') is not None:
                    entry = result['entry']
                    exit_price = result['exit_price']
                    pnl = ((exit_price / entry) - 1) * 100

                    results['trades'] += 1
                    results['pnl_sum'] += pnl
                    results['by_score_range'][score_range]['trades'] += 1
                    results['by_score_range'][score_range]['pnl'] += pnl

                    if result['status'] in ['success', 'closed_profit']:
                        results['wins'] += 1
                        results['by_score_range'][score_range]['wins'] += 1

        return results

    finally:
        # Restore original flag
        constants.ENABLE_DYNAMIC_ENTRY = original_flag


def print_comparison(dynamic_results: Dict, fixed_results: Dict):
    """Print side-by-side comparison."""
    print(f"\n{'='*70}")
    print("COMPARISON: DYNAMIC vs FIXED ENTRY")
    print(f"{'='*70}")

    if not dynamic_results or not fixed_results:
        print("Insufficient data for comparison")
        return

    # Overall comparison
    print(f"\n{'Strategy':<20} {'Candidates':<12} {'Fill Rate':<15} {'Win Rate':<15} {'Avg PnL':<10}")
    print("-" * 70)

    for name, results in [('Dynamic Entry', dynamic_results), ('Fixed Entry (0.20)', fixed_results)]:
        total = results['total']
        filled = results['filled']
        trades = results['trades']
        wins = results['wins']
        pnl_sum = results['pnl_sum']

        fill_rate = f"{filled}/{total} ({filled/total*100:.1f}%)" if total > 0 else "N/A"
        win_rate = f"{wins}/{trades} ({wins/trades*100:.1f}%)" if trades > 0 else "N/A"
        avg_pnl = f"{pnl_sum/trades:.2f}%" if trades > 0 else "N/A"

        print(f"{name:<20} {total:<12} {fill_rate:<15} {win_rate:<15} {avg_pnl:<10}")

    # By score range
    print(f"\n{'='*70}")
    print("FILL RATES BY SCORE RANGE")
    print(f"{'='*70}")
    print(f"\n{'Score Range':<25} {'Dynamic':<20} {'Fixed':<20} {'Improvement':<15}")
    print("-" * 80)

    # Get actual threshold labels
    from bluehorseshoe.analysis import constants as c
    thresholds = c.SIGNAL_STRENGTH_THRESHOLDS
    score_ranges = [
        f'EXTREME ({thresholds["EXTREME"]}+)',
        f'HIGH ({thresholds["HIGH"]}-{thresholds["EXTREME"]})',
        f'MEDIUM ({thresholds["MEDIUM"]}-{thresholds["HIGH"]})',
        f'LOW ({thresholds["LOW"]}-{thresholds["MEDIUM"]})',
        f'WEAK (<{thresholds["LOW"]})'
    ]

    for score_range in score_ranges:
        if score_range not in dynamic_results['by_score_range']:
            continue
        dyn_data = dynamic_results['by_score_range'][score_range]
        fix_data = fixed_results['by_score_range'][score_range]

        if dyn_data['total'] == 0 and fix_data['total'] == 0:
            continue

        dyn_fill_rate = (dyn_data['filled'] / dyn_data['total'] * 100) if dyn_data['total'] > 0 else 0
        fix_fill_rate = (fix_data['filled'] / fix_data['total'] * 100) if fix_data['total'] > 0 else 0
        improvement = dyn_fill_rate - fix_fill_rate

        dyn_str = f"{dyn_data['filled']}/{dyn_data['total']} ({dyn_fill_rate:.1f}%)"
        fix_str = f"{fix_data['filled']}/{fix_data['total']} ({fix_fill_rate:.1f}%)"
        imp_str = f"{improvement:+.1f}%"

        print(f"{score_range:<25} {dyn_str:<20} {fix_str:<20} {imp_str:<15}")

    # Key insights
    print(f"\n{'='*70}")
    print("KEY INSIGHTS")
    print(f"{'='*70}")

    # Overall fill rate improvement
    dyn_overall = (dynamic_results['filled'] / dynamic_results['total'] * 100) if dynamic_results['total'] > 0 else 0
    fix_overall = (fixed_results['filled'] / fixed_results['total'] * 100) if fixed_results['total'] > 0 else 0
    overall_improvement = dyn_overall - fix_overall

    print(f"\n  Overall Fill Rate Improvement: {overall_improvement:+.1f}%")
    print(f"    Dynamic: {dyn_overall:.1f}%")
    print(f"    Fixed:   {fix_overall:.1f}%")

    # Win rate comparison
    dyn_winrate = (dynamic_results['wins'] / dynamic_results['trades'] * 100) if dynamic_results['trades'] > 0 else 0
    fix_winrate = (fixed_results['wins'] / fixed_results['trades'] * 100) if fixed_results['trades'] > 0 else 0
    winrate_diff = dyn_winrate - fix_winrate

    print(f"\n  Win Rate Difference: {winrate_diff:+.1f}%")
    print(f"    Dynamic: {dyn_winrate:.1f}%")
    print(f"    Fixed:   {fix_winrate:.1f}%")

    # Average PnL comparison
    dyn_avg_pnl = (dynamic_results['pnl_sum'] / dynamic_results['trades']) if dynamic_results['trades'] > 0 else 0
    fix_avg_pnl = (fixed_results['pnl_sum'] / fixed_results['trades']) if fixed_results['trades'] > 0 else 0
    pnl_diff = dyn_avg_pnl - fix_avg_pnl

    print(f"\n  Average PnL Difference: {pnl_diff:+.2f}%")
    print(f"    Dynamic: {dyn_avg_pnl:.2f}%")
    print(f"    Fixed:   {fix_avg_pnl:.2f}%")


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(description='Compare Dynamic vs Fixed Entry')
    parser.add_argument('--date', type=str, default='2026-01-30', help='Date to test')
    parser.add_argument('--symbols', type=int, default=200, help='Number of symbols to test')

    args = parser.parse_args()

    print("="*70)
    print("DYNAMIC vs FIXED ENTRY COMPARISON")
    print("="*70)
    print(f"\nTest Date: {args.date}")
    print(f"Sample Size: {args.symbols} symbols")

    container = create_app_container()
    try:
        # Get sample symbols
        all_symbols = get_symbol_name_list(database=container.get_database())

        # Prioritize liquid symbols
        priority = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN', 'GOOGL', 'META', 'NFLX',
                    'AMD', 'INTC', 'AVGO', 'JPM', 'BAC', 'JNJ', 'UNH', 'PFE']
        sample_symbols = [s for s in priority if s in all_symbols]

        import random
        remaining = [s for s in all_symbols if s not in sample_symbols]
        random.shuffle(remaining)
        sample_symbols.extend(remaining[:args.symbols - len(sample_symbols)])

        print(f"Testing {len(sample_symbols)} symbols...")

        # Test with dynamic entry ON
        print(f"\n{'='*70}")
        print("TEST 1: DYNAMIC ENTRY (ENABLED)")
        print(f"{'='*70}")
        dynamic_results = test_strategy(
            container.get_database(),
            args.date,
            enable_dynamic=True,
            sample_symbols=sample_symbols
        )

        # Test with dynamic entry OFF
        print(f"\n{'='*70}")
        print("TEST 2: FIXED ENTRY (0.20 ATR for all)")
        print(f"{'='*70}")
        fixed_results = test_strategy(
            container.get_database(),
            args.date,
            enable_dynamic=False,
            sample_symbols=sample_symbols
        )

        # Compare results
        if dynamic_results and fixed_results:
            print_comparison(dynamic_results, fixed_results)
        else:
            print("\nError: Could not generate results for comparison")
            return 1

        print(f"\n{'='*70}")
        print("✓ Comparison Complete!")
        print(f"{'='*70}\n")

        return 0
    finally:
        container.close()


if __name__ == '__main__':
    sys.exit(main())
