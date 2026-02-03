#!/usr/bin/env python
"""
A/B Test: Dynamic Entry vs Fixed Entry

Runs the SAME backtest twice:
1. With ENABLE_DYNAMIC_ENTRY = True (new strategy)
2. With ENABLE_DYNAMIC_ENTRY = False (baseline 0.20 for all)

Compares PnL, fill rates, and win rates to determine if dynamic entry
actually improves performance.

Usage:
    python src/ab_test_dynamic_entry.py --dates 2025-08-06,2025-08-20,2025-08-26
"""
import argparse
import sys
import importlib
from collections import defaultdict
from typing import List, Dict, Tuple

from bluehorseshoe.analysis.backtest import Backtester
from bluehorseshoe.analysis.strategy import SwingTrader, StrategyContext
from bluehorseshoe.analysis import constants
from bluehorseshoe.core.container import create_app_container
from bluehorseshoe.core.symbols import get_symbol_name_list


def run_backtest_with_setting(
    database,
    test_dates: List[str],
    sample_symbols: List[str],
    enable_dynamic: bool
) -> Dict:
    """
    Run backtest with specific dynamic entry setting.

    Returns:
        Aggregated results
    """
    # Store original setting
    original_setting = constants.ENABLE_DYNAMIC_ENTRY

    # Set the flag
    constants.ENABLE_DYNAMIC_ENTRY = enable_dynamic

    # Need to reload the module to pick up the change
    # This is a hack but necessary for the comparison
    import bluehorseshoe.analysis.strategy as strategy_module
    importlib.reload(strategy_module)

    try:
        trader = SwingTrader(database=database)
        backtester = Backtester(database=database)

        all_results = []

        for test_date in test_dates:
            print(f"  Testing {test_date}...")

            ctx = StrategyContext(target_date=test_date)

            # Generate predictions
            predictions = []
            for symbol in sample_symbols:
                try:
                    result = trader.process_symbol(symbol, ctx)
                    if result:
                        predictions.append(result)
                except Exception:
                    continue

            # Filter baseline predictions
            baseline_predictions = [
                p for p in predictions
                if p and p.get('baseline_score', 0) > 0
            ]

            if not baseline_predictions:
                continue

            # Evaluate trades
            date_results = {
                'total': 0,
                'filled': 0,
                'wins': 0,
                'losses': 0,
                'pnl_sum': 0.0,
                'pnl_list': []
            }

            for pred in baseline_predictions:
                setup = pred.get('baseline_setup', {})

                pred['entry_price'] = setup.get('entry_price')
                pred['stop_loss'] = setup.get('stop_loss')
                pred['take_profit'] = setup.get('take_profit')

                if not pred['entry_price']:
                    continue

                result = backtester.evaluate_prediction(pred, test_date)

                date_results['total'] += 1

                if result.get('entry') is not None:
                    date_results['filled'] += 1

                    if result.get('exit_price') is not None:
                        entry = result['entry']
                        exit_price = result['exit_price']
                        pnl = ((exit_price / entry) - 1) * 100

                        date_results['pnl_sum'] += pnl
                        date_results['pnl_list'].append(pnl)

                        if result['status'] in ['success', 'closed_profit']:
                            date_results['wins'] += 1
                        else:
                            date_results['losses'] += 1

            all_results.append(date_results)

            filled = date_results['filled']
            total = date_results['total']
            fill_rate = (filled / total * 100) if total > 0 else 0
            print(f"    Candidates: {total}, Filled: {filled} ({fill_rate:.1f}%)")

        # Aggregate
        aggregated = {
            'total': sum(r['total'] for r in all_results),
            'filled': sum(r['filled'] for r in all_results),
            'wins': sum(r['wins'] for r in all_results),
            'losses': sum(r['losses'] for r in all_results),
            'pnl_sum': sum(r['pnl_sum'] for r in all_results),
            'pnl_list': [pnl for r in all_results for pnl in r['pnl_list']]
        }

        return aggregated

    finally:
        # Restore original setting
        constants.ENABLE_DYNAMIC_ENTRY = original_setting
        importlib.reload(strategy_module)


def print_comparison(dynamic_results: Dict, fixed_results: Dict):
    """Print side-by-side comparison."""
    print(f"\n{'='*70}")
    print("A/B TEST RESULTS: DYNAMIC vs FIXED ENTRY")
    print(f"{'='*70}")

    # Extract metrics
    metrics = {}
    for name, results in [('Dynamic', dynamic_results), ('Fixed', fixed_results)]:
        total = results['total']
        filled = results['filled']
        wins = results['wins']
        losses = results['losses']
        pnl_sum = results['pnl_sum']
        pnl_list = results['pnl_list']

        fill_rate = (filled / total * 100) if total > 0 else 0
        trades = wins + losses
        win_rate = (wins / trades * 100) if trades > 0 else 0
        avg_pnl = (pnl_sum / trades) if trades > 0 else 0

        metrics[name] = {
            'total': total,
            'filled': filled,
            'fill_rate': fill_rate,
            'trades': trades,
            'wins': wins,
            'win_rate': win_rate,
            'pnl_sum': pnl_sum,
            'avg_pnl': avg_pnl,
            'pnl_list': pnl_list
        }

    # Print comparison table
    print(f"\n{'Metric':<25} {'Dynamic Entry':<20} {'Fixed (0.20)':<20} {'Difference':<15}")
    print("-" * 80)

    # Candidates
    print(f"{'Total Candidates':<25} {metrics['Dynamic']['total']:<20} "
          f"{metrics['Fixed']['total']:<20} "
          f"{metrics['Dynamic']['total'] - metrics['Fixed']['total']:<15}")

    # Fill Rate
    dyn_fill = metrics['Dynamic']['fill_rate']
    fix_fill = metrics['Fixed']['fill_rate']
    fill_diff = dyn_fill - fix_fill
    print(f"{'Fill Rate':<25} {dyn_fill:.1f}%{'':<15} "
          f"{fix_fill:.1f}%{'':<15} "
          f"{fill_diff:+.1f}%{'':<10}")

    # Filled trades
    print(f"{'Filled Trades':<25} {metrics['Dynamic']['filled']:<20} "
          f"{metrics['Fixed']['filled']:<20} "
          f"{metrics['Dynamic']['filled'] - metrics['Fixed']['filled']:<15}")

    # Completed trades
    print(f"{'Completed Trades':<25} {metrics['Dynamic']['trades']:<20} "
          f"{metrics['Fixed']['trades']:<20} "
          f"{metrics['Dynamic']['trades'] - metrics['Fixed']['trades']:<15}")

    # Win Rate
    dyn_win = metrics['Dynamic']['win_rate']
    fix_win = metrics['Fixed']['win_rate']
    win_diff = dyn_win - fix_win
    print(f"{'Win Rate':<25} {dyn_win:.1f}%{'':<15} "
          f"{fix_win:.1f}%{'':<15} "
          f"{win_diff:+.1f}%{'':<10}")

    # Avg PnL
    dyn_avg = metrics['Dynamic']['avg_pnl']
    fix_avg = metrics['Fixed']['avg_pnl']
    avg_diff = dyn_avg - fix_avg
    print(f"{'Avg PnL per Trade':<25} {dyn_avg:.2f}%{'':<15} "
          f"{fix_avg:.2f}%{'':<15} "
          f"{avg_diff:+.2f}%{'':<10}")

    # Total PnL
    dyn_total = metrics['Dynamic']['pnl_sum']
    fix_total = metrics['Fixed']['pnl_sum']
    total_diff = dyn_total - fix_total
    print(f"{'Total PnL':<25} {dyn_total:.2f}%{'':<15} "
          f"{fix_total:.2f}%{'':<15} "
          f"{total_diff:+.2f}%{'':<10}")

    # Key insights
    print(f"\n{'='*70}")
    print("KEY INSIGHTS")
    print(f"{'='*70}")

    # Fill rate impact
    print(f"\n1. FILL RATE IMPACT:")
    if abs(fill_diff) < 1.0:
        print(f"   ≈ No significant difference ({fill_diff:+.1f}%)")
    elif fill_diff > 0:
        print(f"   ✓ Dynamic entry INCREASES fill rate by {fill_diff:+.1f}%")
    else:
        print(f"   ✗ Dynamic entry DECREASES fill rate by {fill_diff:.1f}%")

    # Win rate impact
    print(f"\n2. WIN RATE IMPACT:")
    if abs(win_diff) < 2.0:
        print(f"   ✓ Win rate maintained ({win_diff:+.1f}%)")
    elif win_diff > 0:
        print(f"   ✓ Win rate IMPROVED by {win_diff:+.1f}%")
    else:
        print(f"   ✗ Win rate DECREASED by {win_diff:.1f}%")

    # PnL impact
    print(f"\n3. PnL IMPACT:")
    if abs(avg_diff) < 0.1:
        print(f"   ≈ No significant difference in avg PnL ({avg_diff:+.2f}%)")
    elif avg_diff > 0:
        print(f"   ✓ Avg PnL IMPROVED by {avg_diff:+.2f}%")
    else:
        print(f"   ✗ Avg PnL DECREASED by {avg_diff:.2f}%")

    print(f"\n   Total PnL difference: {total_diff:+.2f}%")
    if abs(total_diff) < 5.0:
        print(f"   → Minimal impact on total returns")
    elif total_diff > 0:
        print(f"   → Dynamic entry adds {total_diff:.2f}% in total returns")
    else:
        print(f"   → Dynamic entry reduces total returns by {abs(total_diff):.2f}%")

    # Final verdict
    print(f"\n{'='*70}")
    print("FINAL VERDICT")
    print(f"{'='*70}\n")

    # Decision criteria
    is_better_pnl = avg_diff > 0
    is_maintained_win_rate = abs(win_diff) < 3.0
    is_positive_total = total_diff > 0

    if is_better_pnl and is_maintained_win_rate:
        print("✅ RECOMMENDATION: DEPLOY DYNAMIC ENTRY")
        print("   - Improved or maintained PnL")
        print("   - Win rate stable")
        print("   - Clear benefit from dynamic strategy")
    elif is_maintained_win_rate and abs(avg_diff) < 0.1:
        print("⚠️  RECOMMENDATION: NEUTRAL - Monitor Further")
        print("   - No significant PnL improvement yet")
        print("   - Win rate maintained")
        print("   - May benefit when EXTREME/HIGH signals appear")
    else:
        print("❌ RECOMMENDATION: DO NOT DEPLOY")
        print("   - PnL or win rate degradation detected")
        print("   - Requires investigation and fixes")

    print(f"\n{'='*70}\n")


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(description='A/B Test Dynamic Entry')
    parser.add_argument('--dates', type=str, required=True,
                        help='Comma-separated list of dates to test')
    parser.add_argument('--symbols', type=int, default=200,
                        help='Number of symbols to test')

    args = parser.parse_args()

    # Parse dates
    test_dates = [d.strip() for d in args.dates.split(',')]

    print("="*70)
    print("A/B TEST: DYNAMIC ENTRY vs FIXED ENTRY (0.20)")
    print("="*70)
    print(f"\nDates to test: {len(test_dates)}")
    print(f"Symbols per date: {args.symbols}")
    print(f"Test dates: {', '.join(test_dates)}\n")

    container = create_app_container()
    try:
        database = container.get_database()

        # Get symbol pool
        all_symbols = get_symbol_name_list(database=database)

        # Use same symbols for both tests
        priority = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA']
        sample_symbols = [s for s in priority if s in all_symbols]

        import random
        random.seed(42)  # Same seed for reproducibility
        remaining = [s for s in all_symbols if s not in sample_symbols]
        random.shuffle(remaining)
        sample_symbols.extend(remaining[:args.symbols - len(sample_symbols)])

        print(f"Using {len(sample_symbols)} symbols for both tests\n")

        # Test 1: Dynamic Entry
        print("="*70)
        print("TEST 1: DYNAMIC ENTRY (ENABLED)")
        print("="*70)
        dynamic_results = run_backtest_with_setting(
            database, test_dates, sample_symbols, enable_dynamic=True
        )

        # Test 2: Fixed Entry
        print(f"\n{'='*70}")
        print("TEST 2: FIXED ENTRY (0.20 ATR for all)")
        print("="*70)
        fixed_results = run_backtest_with_setting(
            database, test_dates, sample_symbols, enable_dynamic=False
        )

        # Compare results
        print_comparison(dynamic_results, fixed_results)

        return 0

    finally:
        container.close()


if __name__ == '__main__':
    sys.exit(main())
