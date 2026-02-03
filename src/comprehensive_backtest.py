#!/usr/bin/env python
"""
Comprehensive Backtest Across Random Dates

This script tests the dynamic entry strategy across multiple randomized dates
to get statistically significant results.

Usage:
    python src/comprehensive_backtest.py --num-dates 20 --symbols-per-date 300
"""
import argparse
import sys
import random
from collections import defaultdict
from typing import List, Dict, Tuple
import pandas as pd

from bluehorseshoe.analysis.backtest import Backtester
from bluehorseshoe.analysis.strategy import SwingTrader, StrategyContext
from bluehorseshoe.analysis.constants import SIGNAL_STRENGTH_THRESHOLDS
from bluehorseshoe.core.container import create_app_container
from bluehorseshoe.core.symbols import get_symbol_name_list


def get_available_dates(database) -> List[str]:
    """Get list of dates with good data coverage."""
    # Query for dates that have SPY data (proxy for market days)
    result = database.historical_prices.find_one(
        {'symbol': 'SPY'},
        {'days.date': 1}
    )

    if not result or 'days' not in result:
        return []

    dates = [d['date'] for d in result['days']]
    # Filter to recent dates (last 6 months)
    recent_dates = [d for d in dates if d >= '2025-08-01' and d <= '2026-02-02']
    return sorted(recent_dates)


def test_single_date(
    database,
    test_date: str,
    sample_symbols: List[str],
    trader: SwingTrader,
    backtester: Backtester
) -> Dict:
    """
    Test a single date and return results by tier.

    Returns:
        Dict with results by signal strength tier
    """
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
        return {}

    # Analyze by signal strength
    results_by_tier = defaultdict(lambda: {
        'total': 0,
        'filled': 0,
        'wins': 0,
        'losses': 0,
        'pnl_sum': 0.0,
        'pnl_list': []
    })

    for pred in baseline_predictions:
        setup = pred.get('baseline_setup', {})
        signal_strength = setup.get('signal_strength', 'UNKNOWN')

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

                results_by_tier[tier]['pnl_sum'] += pnl
                results_by_tier[tier]['pnl_list'].append(pnl)

                if result['status'] in ['success', 'closed_profit']:
                    results_by_tier[tier]['wins'] += 1
                else:
                    results_by_tier[tier]['losses'] += 1

    return dict(results_by_tier)


def aggregate_results(all_results: List[Dict]) -> Dict:
    """Aggregate results across all dates."""
    aggregated = defaultdict(lambda: {
        'total': 0,
        'filled': 0,
        'wins': 0,
        'losses': 0,
        'pnl_sum': 0.0,
        'pnl_list': []
    })

    for result in all_results:
        for tier, data in result.items():
            aggregated[tier]['total'] += data['total']
            aggregated[tier]['filled'] += data['filled']
            aggregated[tier]['wins'] += data['wins']
            aggregated[tier]['losses'] += data['losses']
            aggregated[tier]['pnl_sum'] += data['pnl_sum']
            aggregated[tier]['pnl_list'].extend(data['pnl_list'])

    return dict(aggregated)


def print_tier_results(tier: str, data: Dict, total_candidates: int):
    """Print results for a single tier."""
    total = data['total']
    filled = data['filled']
    wins = data['wins']
    losses = data['losses']
    pnl_sum = data['pnl_sum']
    pnl_list = data['pnl_list']

    if total == 0:
        return

    fill_rate = (filled / total * 100) if total > 0 else 0
    trades_completed = wins + losses
    win_rate = (wins / trades_completed * 100) if trades_completed > 0 else 0
    avg_pnl = (pnl_sum / trades_completed) if trades_completed > 0 else 0

    print(f"\n{tier}:")
    print(f"  Candidates: {total} ({total/total_candidates*100:.1f}% of total)")
    print(f"  Fill Rate: {filled}/{total} ({fill_rate:.1f}%)")

    if trades_completed > 0:
        print(f"  Completed Trades: {trades_completed}")
        print(f"  Win Rate: {wins}/{trades_completed} ({win_rate:.1f}%)")
        print(f"  Avg PnL: {avg_pnl:.2f}%")
        print(f"  Total PnL: {pnl_sum:.2f}%")

        if len(pnl_list) > 0:
            median_pnl = sorted(pnl_list)[len(pnl_list)//2]
            print(f"  Median PnL: {median_pnl:.2f}%")


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(description='Comprehensive Backtest')
    parser.add_argument('--num-dates', type=int, default=20, help='Number of random dates to test')
    parser.add_argument('--symbols-per-date', type=int, default=300, help='Symbols per date')
    parser.add_argument('--seed', type=int, default=42, help='Random seed for reproducibility')

    args = parser.parse_args()

    print("="*70)
    print("COMPREHENSIVE DYNAMIC ENTRY BACKTEST")
    print("="*70)
    print(f"\nParameters:")
    print(f"  Dates to test: {args.num_dates}")
    print(f"  Symbols per date: {args.symbols_per_date}")
    print(f"  Random seed: {args.seed}")

    random.seed(args.seed)

    container = create_app_container()
    try:
        database = container.get_database()

        # Get available dates
        print(f"\nFinding available dates...")
        available_dates = get_available_dates(database)
        print(f"  Found {len(available_dates)} dates with data")

        if len(available_dates) < args.num_dates:
            print(f"  Warning: Only {len(available_dates)} dates available, using all")
            test_dates = available_dates
        else:
            test_dates = random.sample(available_dates, args.num_dates)

        test_dates.sort()
        print(f"\nSelected dates: {test_dates[0]} to {test_dates[-1]}")

        # Get symbol pool
        print(f"\nPreparing symbol pool...")
        all_symbols = get_symbol_name_list(database=database)

        # Prioritize liquid symbols
        priority_symbols = [
            'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'NFLX',
            'AMD', 'INTC', 'QCOM', 'AVGO', 'TXN', 'MU', 'AMAT', 'LRCX',
            'JPM', 'BAC', 'WFC', 'C', 'GS', 'MS', 'AXP', 'BLK',
            'JNJ', 'UNH', 'PFE', 'ABBV', 'MRK', 'TMO', 'LLY', 'ABT',
            'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'PXD', 'MPC', 'VLO'
        ]

        # Create symbol pool with priority + random
        sample_symbols = [s for s in priority_symbols if s in all_symbols]
        remaining = [s for s in all_symbols if s not in sample_symbols]
        random.shuffle(remaining)
        sample_symbols.extend(remaining[:args.symbols_per_date - len(sample_symbols)])

        print(f"  Symbol pool size: {len(sample_symbols)}")

        # Initialize trader and backtester
        trader = SwingTrader(database=database)
        backtester = Backtester(database=database)

        # Run tests
        print(f"\n{'='*70}")
        print("RUNNING BACKTESTS")
        print("="*70)

        all_results = []
        date_summaries = []

        for i, test_date in enumerate(test_dates, 1):
            print(f"\n[{i}/{len(test_dates)}] Testing {test_date}...")

            try:
                results = test_single_date(
                    database, test_date, sample_symbols, trader, backtester
                )

                if results:
                    all_results.append(results)

                    # Quick summary
                    total = sum(d['total'] for d in results.values())
                    filled = sum(d['filled'] for d in results.values())
                    fill_rate = (filled / total * 100) if total > 0 else 0

                    date_summaries.append({
                        'date': test_date,
                        'candidates': total,
                        'filled': filled,
                        'fill_rate': fill_rate
                    })

                    print(f"  Candidates: {total}, Filled: {filled} ({fill_rate:.1f}%)")
                else:
                    print(f"  No valid predictions")

            except Exception as e:
                print(f"  Error: {e}")
                continue

        # Aggregate and print results
        if not all_results:
            print("\nNo results to aggregate.")
            return 1

        print(f"\n{'='*70}")
        print("AGGREGATED RESULTS")
        print("="*70)

        aggregated = aggregate_results(all_results)

        # Print by tier
        tier_order = ['EXTREME', 'HIGH', 'MEDIUM', 'LOW', 'WEAK', 'UNKNOWN']
        total_candidates = sum(d['total'] for d in aggregated.values())

        for tier in tier_order:
            if tier in aggregated:
                print_tier_results(tier, aggregated[tier], total_candidates)

        # Overall summary
        print(f"\n{'='*70}")
        print("OVERALL SUMMARY")
        print("="*70)

        total_filled = sum(d['filled'] for d in aggregated.values())
        total_trades = sum(d['wins'] + d['losses'] for d in aggregated.values())
        total_wins = sum(d['wins'] for d in aggregated.values())
        total_pnl = sum(d['pnl_sum'] for d in aggregated.values())

        print(f"\nDates Tested: {len(all_results)}")
        print(f"Total Candidates: {total_candidates}")
        print(f"Total Filled: {total_filled} ({total_filled/total_candidates*100:.1f}%)")
        print(f"Completed Trades: {total_trades}")
        print(f"Win Rate: {total_wins}/{total_trades} ({total_wins/total_trades*100:.1f}%)")
        print(f"Avg PnL per Trade: {total_pnl/total_trades:.2f}%")
        print(f"Total PnL: {total_pnl:.2f}%")

        # Date-by-date summary
        print(f"\n{'='*70}")
        print("DATE-BY-DATE SUMMARY")
        print("="*70)
        print(f"\n{'Date':<12} {'Candidates':<12} {'Filled':<12} {'Fill Rate':<12}")
        print("-" * 50)
        for summary in date_summaries:
            print(f"{summary['date']:<12} {summary['candidates']:<12} "
                  f"{summary['filled']:<12} {summary['fill_rate']:.1f}%")

        print(f"\n{'='*70}")
        print("✓ Comprehensive Backtest Complete!")
        print("="*70)

        return 0

    finally:
        container.close()


if __name__ == '__main__':
    sys.exit(main())
