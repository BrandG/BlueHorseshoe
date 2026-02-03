#!/usr/bin/env python
"""
Quick Backtest Validation for Dynamic Entry Strategy

This script runs a quick validation test on a small date range to verify
the dynamic entry strategy is working correctly and showing improved fill rates.

Usage:
    python src/quick_backtest_validation.py
"""
import sys
from collections import defaultdict
from typing import Dict, List
import pandas as pd

from bluehorseshoe.analysis.backtest import Backtester
from bluehorseshoe.analysis.strategy import SwingTrader, StrategyContext
from bluehorseshoe.core.container import create_app_container
from bluehorseshoe.core.symbols import get_symbol_name_list


def quick_test(database, test_date: str, sample_size: int = 500):
    """
    Run a quick test on a sample of symbols.

    Args:
        database: MongoDB database instance
        test_date: Date to test
        sample_size: Number of symbols to sample
    """
    print(f"\n{'='*70}")
    print(f"Quick Validation Test: {test_date}")
    print(f"{'='*70}")

    trader = SwingTrader(database=database)
    backtester = Backtester(database=database)

    # Get a sample of symbols (focus on liquid names for faster processing)
    all_symbols = get_symbol_name_list(database=database)
    # Prioritize common/liquid symbols
    priority_symbols = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN', 'GOOGL', 'META', 'NFLX',
                        'AMD', 'INTC', 'QCOM', 'AVGO', 'TXN', 'MU', 'AMAT', 'LRCX',
                        'JPM', 'BAC', 'WFC', 'C', 'GS', 'MS', 'AXP', 'BLK',
                        'JNJ', 'UNH', 'PFE', 'ABBV', 'MRK', 'TMO', 'LLY', 'ABT']

    # Combine priority + random sample
    sample_symbols = []
    for sym in priority_symbols:
        if sym in all_symbols:
            sample_symbols.append(sym)

    # Add more random symbols to reach sample_size
    import random
    remaining = [s for s in all_symbols if s not in sample_symbols]
    random.shuffle(remaining)
    sample_symbols.extend(remaining[:sample_size - len(sample_symbols)])

    print(f"  Testing {len(sample_symbols)} symbols...")

    # Generate predictions
    ctx = StrategyContext(target_date=test_date)
    predictions = []

    print("  > Generating predictions...")
    for i, symbol in enumerate(sample_symbols):
        try:
            result = trader.process_symbol(symbol, ctx)
            if result:
                predictions.append(result)

            if (i + 1) % 100 == 0:
                print(f"    Progress: {i + 1}/{len(sample_symbols)}")
        except Exception as e:
            continue

    # Filter baseline predictions
    baseline_predictions = [
        p for p in predictions
        if p and p.get('baseline_score', 0) > 0
    ]

    print(f"  > Found {len(baseline_predictions)} baseline candidates")

    if not baseline_predictions:
        print("  No valid predictions to test.")
        return None

    # Sort by score
    baseline_predictions.sort(key=lambda x: x.get('baseline_score', 0), reverse=True)

    # Analyze by signal strength
    results_by_tier = defaultdict(lambda: {
        'total': 0,
        'filled': 0,
        'wins': 0,
        'total_trades': 0,
        'pnl_sum': 0.0
    })

    print(f"\n  Evaluating {len(baseline_predictions)} predictions...")

    for pred in baseline_predictions:
        setup = pred.get('baseline_setup', {})
        signal_strength = setup.get('signal_strength', 'UNKNOWN')
        atr_discount = setup.get('atr_discount_used', 0.20)

        # Flatten for backtest
        pred['entry_price'] = setup.get('entry_price')
        pred['stop_loss'] = setup.get('stop_loss')
        pred['take_profit'] = setup.get('take_profit')

        if not pred['entry_price']:
            continue

        # Evaluate
        result = backtester.evaluate_prediction(pred, test_date)

        tier = signal_strength
        results_by_tier[tier]['total'] += 1

        # Check if filled
        if result.get('entry') is not None:
            results_by_tier[tier]['filled'] += 1

            # Check if completed
            if result.get('exit_price') is not None:
                entry = result['entry']
                exit_price = result['exit_price']
                pnl = ((exit_price / entry) - 1) * 100

                results_by_tier[tier]['total_trades'] += 1
                results_by_tier[tier]['pnl_sum'] += pnl

                if result['status'] in ['success', 'closed_profit']:
                    results_by_tier[tier]['wins'] += 1

    return dict(results_by_tier)


def print_results(results: Dict):
    """Print test results."""
    if not results:
        return

    print(f"\n{'='*70}")
    print("RESULTS BY SIGNAL STRENGTH")
    print(f"{'='*70}")

    tier_order = ['EXTREME', 'HIGH', 'MEDIUM', 'LOW', 'WEAK', 'UNKNOWN']

    # Calculate totals
    total_candidates = sum(d['total'] for d in results.values())
    total_filled = sum(d['filled'] for d in results.values())

    for tier in tier_order:
        if tier not in results or results[tier]['total'] == 0:
            continue

        data = results[tier]
        total = data['total']
        filled = data['filled']
        total_trades = data['total_trades']
        wins = data['wins']
        pnl_sum = data['pnl_sum']

        fill_rate = (filled / total * 100) if total > 0 else 0
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        avg_pnl = (pnl_sum / total_trades) if total_trades > 0 else 0
        pct_of_total = (total / total_candidates * 100) if total_candidates > 0 else 0

        print(f"\n{tier}:")
        print(f"  Candidates: {total} ({pct_of_total:.1f}%)")
        print(f"  Fill Rate: {filled}/{total} ({fill_rate:.1f}%)")
        if total_trades > 0:
            print(f"  Completed: {total_trades} trades")
            print(f"  Win Rate: {wins}/{total_trades} ({win_rate:.1f}%)")
            print(f"  Avg PnL: {avg_pnl:.2f}%")

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"Total Candidates: {total_candidates}")
    print(f"Overall Fill Rate: {total_filled}/{total_candidates} ({total_filled/total_candidates*100:.1f}%)")

    total_trades = sum(d['total_trades'] for d in results.values())
    total_wins = sum(d['wins'] for d in results.values())
    total_pnl = sum(d['pnl_sum'] for d in results.values())

    if total_trades > 0:
        print(f"Total Completed Trades: {total_trades}")
        print(f"Overall Win Rate: {total_wins}/{total_trades} ({total_wins/total_trades*100:.1f}%)")
        print(f"Overall Avg PnL: {total_pnl/total_trades:.2f}%")


def main():
    """Main execution."""
    print("="*70)
    print("DYNAMIC ENTRY QUICK VALIDATION TEST")
    print("="*70)

    # Use recent dates that have data
    test_dates = ['2026-01-30', '2026-02-02']  # Recent dates with data

    print(f"\nTesting {len(test_dates)} dates with ~500 symbols each")
    print("This will take approximately 5-10 minutes...\n")

    container = create_app_container()
    try:
        all_results = []

        for date in test_dates:
            try:
                results = quick_test(container.get_database(), date, sample_size=500)
                if results:
                    all_results.append(results)
                    print_results(results)
            except Exception as e:
                print(f"Error testing {date}: {e}")
                import traceback
                traceback.print_exc()
                continue

        # Aggregate results
        if len(all_results) > 1:
            print(f"\n{'='*70}")
            print("AGGREGATED RESULTS")
            print(f"{'='*70}")

            aggregated = defaultdict(lambda: {
                'total': 0,
                'filled': 0,
                'wins': 0,
                'total_trades': 0,
                'pnl_sum': 0.0
            })

            for result in all_results:
                for tier, data in result.items():
                    aggregated[tier]['total'] += data['total']
                    aggregated[tier]['filled'] += data['filled']
                    aggregated[tier]['wins'] += data['wins']
                    aggregated[tier]['total_trades'] += data['total_trades']
                    aggregated[tier]['pnl_sum'] += data['pnl_sum']

            print_results(dict(aggregated))

        print(f"\n{'='*70}")
        print("✓ Validation Complete!")
        print(f"{'='*70}\n")

        return 0
    finally:
        container.close()


if __name__ == '__main__':
    sys.exit(main())
