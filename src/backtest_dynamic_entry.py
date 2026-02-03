#!/usr/bin/env python
"""
Backtest Analysis for Dynamic Entry Strategy

This script runs backtests across multiple historical dates and analyzes:
1. Fill rates by signal strength tier
2. Win rates by signal strength tier
3. Average PnL by signal strength tier
4. Overall performance improvements

Usage:
    python src/backtest_dynamic_entry.py --start 2025-10-01 --end 2025-12-31 --interval 7
    python src/backtest_dynamic_entry.py --dates 2025-11-01,2025-11-15,2025-12-01
"""
import argparse
import sys
import logging
from collections import defaultdict
from typing import List, Dict, Any
import pandas as pd

from bluehorseshoe.analysis.backtest import Backtester, BacktestConfig, BacktestOptions
from bluehorseshoe.analysis.strategy import SwingTrader, StrategyContext
from bluehorseshoe.core.container import create_app_container
from bluehorseshoe.core.scores import ScoreManager

logging.basicConfig(level=logging.WARNING)


class DynamicEntryBacktester:
    """Extended backtester for dynamic entry strategy analysis."""

    def __init__(self, database):
        """Initialize with database connection."""
        self.database = database
        self.trader = SwingTrader(database=database)
        self.backtester = Backtester(database=database)
        self.score_manager = ScoreManager(database=database)

    def analyze_date(self, target_date: str, top_n: int = 50) -> Dict[str, Any]:
        """
        Run backtest for a single date and analyze by signal strength.

        Args:
            target_date: Date to backtest (YYYY-MM-DD)
            top_n: Number of top candidates to test

        Returns:
            Dictionary with results by signal strength tier
        """
        print(f"\n{'='*70}")
        print(f"Backtesting: {target_date}")
        print(f"{'='*70}")

        # Generate predictions for this date
        print("  > Generating predictions...")
        ctx = StrategyContext(target_date=target_date)

        # Get symbols (limit for speed)
        from bluehorseshoe.core.symbols import get_symbol_name_list
        all_symbols = get_symbol_name_list(database=self.database)

        # Process all symbols to get predictions
        predictions = []
        processed = 0
        total = len(all_symbols)

        for symbol in all_symbols:
            try:
                result = self.trader.process_symbol(symbol, ctx)
                if result:
                    predictions.append(result)
                processed += 1

                if processed % 1000 == 0:
                    print(f"    Progress: {processed}/{total} ({processed/total*100:.1f}%)")
            except Exception as e:
                logging.error(f"Error processing {symbol}: {e}")
                continue

        # Filter baseline predictions with positive scores
        baseline_predictions = [
            p for p in predictions
            if p and p.get('baseline_score', 0) > 0
        ]

        # Sort by score and take top N
        baseline_predictions.sort(key=lambda x: x.get('baseline_score', 0), reverse=True)
        top_predictions = baseline_predictions[:top_n]

        print(f"  > Found {len(baseline_predictions)} baseline candidates, testing top {len(top_predictions)}")

        if not top_predictions:
            print("  > No valid predictions found.")
            return {}

        # Analyze each prediction
        results_by_tier = defaultdict(lambda: {
            'total': 0,
            'filled': 0,
            'wins': 0,
            'losses': 0,
            'pnl_sum': 0.0,
            'scores': [],
            'trades': []
        })

        for pred in top_predictions:
            # Extract metadata
            setup = pred.get('baseline_setup', {})
            score = pred.get('baseline_score', 0)
            signal_strength = setup.get('signal_strength', 'UNKNOWN')
            atr_discount = setup.get('atr_discount_used', 0.20)

            # Flatten for backtest
            pred['entry_price'] = setup.get('entry_price')
            pred['stop_loss'] = setup.get('stop_loss')
            pred['take_profit'] = setup.get('take_profit')

            # Evaluate trade
            result = self.backtester.evaluate_prediction(pred, target_date)

            # Track by tier
            tier = signal_strength
            results_by_tier[tier]['total'] += 1
            results_by_tier[tier]['scores'].append(score)

            # Check if filled
            is_filled = result.get('entry') is not None
            if is_filled:
                results_by_tier[tier]['filled'] += 1

                # Calculate PnL if exited
                if result.get('exit_price') is not None:
                    entry = result['entry']
                    exit_price = result['exit_price']
                    pnl = ((exit_price / entry) - 1) * 100

                    results_by_tier[tier]['pnl_sum'] += pnl

                    # Track win/loss
                    if result['status'] in ['success', 'closed_profit']:
                        results_by_tier[tier]['wins'] += 1
                    else:
                        results_by_tier[tier]['losses'] += 1

                    # Store trade details
                    results_by_tier[tier]['trades'].append({
                        'symbol': pred['symbol'],
                        'score': score,
                        'atr_discount': atr_discount,
                        'entry': entry,
                        'exit': exit_price,
                        'pnl': pnl,
                        'status': result['status']
                    })

        return dict(results_by_tier)

    def print_tier_summary(self, tier: str, data: Dict, total_candidates: int):
        """Print summary for a single tier."""
        total = data['total']
        filled = data['filled']
        wins = data['wins']
        losses = data['losses']
        pnl_sum = data['pnl_sum']

        if total == 0:
            return

        fill_rate = (filled / total * 100) if total > 0 else 0
        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
        avg_pnl = (pnl_sum / (wins + losses)) if (wins + losses) > 0 else 0
        avg_score = sum(data['scores']) / len(data['scores']) if data['scores'] else 0
        pct_of_total = (total / total_candidates * 100) if total_candidates > 0 else 0

        print(f"\n  {tier}:")
        print(f"    Candidates: {total} ({pct_of_total:.1f}% of top {total_candidates})")
        print(f"    Avg Score: {avg_score:.1f}")
        print(f"    Fill Rate: {filled}/{total} ({fill_rate:.1f}%)")
        if filled > 0:
            print(f"    Completed Trades: {wins + losses}")
            print(f"    Win Rate: {wins}/{wins + losses} ({win_rate:.1f}%)")
            print(f"    Avg PnL: {avg_pnl:.2f}%")
            print(f"    Total PnL: {pnl_sum:.2f}%")

    def aggregate_results(self, all_date_results: List[Dict[str, Dict]]) -> Dict:
        """Aggregate results across all dates."""
        aggregated = defaultdict(lambda: {
            'total': 0,
            'filled': 0,
            'wins': 0,
            'losses': 0,
            'pnl_sum': 0.0,
            'scores': []
        })

        for date_result in all_date_results:
            for tier, data in date_result.items():
                aggregated[tier]['total'] += data['total']
                aggregated[tier]['filled'] += data['filled']
                aggregated[tier]['wins'] += data['wins']
                aggregated[tier]['losses'] += data['losses']
                aggregated[tier]['pnl_sum'] += data['pnl_sum']
                aggregated[tier]['scores'].extend(data['scores'])

        return dict(aggregated)

    def print_final_summary(self, aggregated: Dict):
        """Print final aggregated summary."""
        print(f"\n{'='*70}")
        print("AGGREGATED RESULTS ACROSS ALL DATES")
        print(f"{'='*70}")

        # Calculate totals
        total_candidates = sum(d['total'] for d in aggregated.values())
        total_filled = sum(d['filled'] for d in aggregated.values())
        total_wins = sum(d['wins'] for d in aggregated.values())
        total_losses = sum(d['losses'] for d in aggregated.values())
        total_pnl = sum(d['pnl_sum'] for d in aggregated.values())

        # Print by tier in order
        tier_order = ['EXTREME', 'HIGH', 'MEDIUM', 'LOW', 'WEAK', 'UNKNOWN']
        for tier in tier_order:
            if tier in aggregated:
                self.print_tier_summary(tier, aggregated[tier], total_candidates)

        # Overall summary
        print(f"\n{'='*70}")
        print("OVERALL SUMMARY")
        print(f"{'='*70}")
        print(f"  Total Candidates: {total_candidates}")
        print(f"  Total Filled: {total_filled}/{total_candidates} ({total_filled/total_candidates*100:.1f}%)")
        print(f"  Total Completed Trades: {total_wins + total_losses}")
        print(f"  Overall Win Rate: {total_wins}/{total_wins + total_losses} ({total_wins/(total_wins + total_losses)*100:.1f}%)")
        print(f"  Overall Avg PnL: {total_pnl/(total_wins + total_losses):.2f}%")
        print(f"  Overall Total PnL: {total_pnl:.2f}%")

        # Key insights
        print(f"\n{'='*70}")
        print("KEY INSIGHTS")
        print(f"{'='*70}")

        # Compare fill rates
        if 'EXTREME' in aggregated and aggregated['EXTREME']['total'] > 0:
            extreme_fill = aggregated['EXTREME']['filled'] / aggregated['EXTREME']['total'] * 100
            print(f"  ✓ EXTREME signals fill rate: {extreme_fill:.1f}%")

        if 'HIGH' in aggregated and aggregated['HIGH']['total'] > 0:
            high_fill = aggregated['HIGH']['filled'] / aggregated['HIGH']['total'] * 100
            print(f"  ✓ HIGH signals fill rate: {high_fill:.1f}%")

        if 'MEDIUM' in aggregated and aggregated['MEDIUM']['total'] > 0:
            medium_fill = aggregated['MEDIUM']['filled'] / aggregated['MEDIUM']['total'] * 100
            print(f"  ✓ MEDIUM signals fill rate: {medium_fill:.1f}% (baseline)")

        if 'WEAK' in aggregated and aggregated['WEAK']['total'] > 0:
            weak_fill = aggregated['WEAK']['filled'] / aggregated['WEAK']['total'] * 100
            print(f"  ✓ WEAK signals fill rate: {weak_fill:.1f}%")

        # Compare win rates
        print()
        for tier in tier_order:
            if tier in aggregated:
                data = aggregated[tier]
                if data['wins'] + data['losses'] > 0:
                    win_rate = data['wins'] / (data['wins'] + data['losses']) * 100
                    avg_pnl = data['pnl_sum'] / (data['wins'] + data['losses'])
                    print(f"  {tier}: Win Rate {win_rate:.1f}%, Avg PnL {avg_pnl:.2f}%")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(description='Backtest Dynamic Entry Strategy')
    parser.add_argument('--start', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--interval', type=int, default=7, help='Days between backtests')
    parser.add_argument('--dates', type=str, help='Comma-separated list of dates')
    parser.add_argument('--top-n', type=int, default=50, help='Number of top candidates to test')

    args = parser.parse_args()

    # Determine dates to backtest
    dates = []
    if args.dates:
        dates = [d.strip() for d in args.dates.split(',')]
    elif args.start and args.end:
        current = pd.to_datetime(args.start)
        end = pd.to_datetime(args.end)
        while current <= end:
            dates.append(current.strftime('%Y-%m-%d'))
            current += pd.Timedelta(days=args.interval)
    else:
        print("Error: Must provide either --dates or --start/--end")
        return 1

    print(f"{'='*70}")
    print("DYNAMIC ENTRY STRATEGY BACKTEST")
    print(f"{'='*70}")
    print(f"Dates to test: {len(dates)}")
    print(f"Top candidates per date: {args.top_n}")
    print(f"Dates: {', '.join(dates)}")

    # Initialize
    container = create_app_container()
    try:
        backtester = DynamicEntryBacktester(database=container.get_database())

        # Run backtests
        all_results = []
        for date in dates:
            try:
                results = backtester.analyze_date(date, top_n=args.top_n)
                if results:
                    all_results.append(results)

                    # Print date summary
                    print(f"\n  Summary for {date}:")
                    total = sum(d['total'] for d in results.values())
                    filled = sum(d['filled'] for d in results.values())
                    print(f"    Fill Rate: {filled}/{total} ({filled/total*100:.1f}%)")
            except Exception as e:
                print(f"  Error processing {date}: {e}")
                continue

        # Aggregate and print final results
        if all_results:
            aggregated = backtester.aggregate_results(all_results)
            backtester.print_final_summary(aggregated)
        else:
            print("\nNo results to aggregate.")

        return 0
    finally:
        container.close()


if __name__ == '__main__':
    sys.exit(main())
