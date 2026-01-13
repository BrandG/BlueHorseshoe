"""
run_indicator_analysis.py

CLI tool to run backtests on specific technical indicators over a 6-month period.
This helps in identifying the predictive power of individual factors and
optimizing strategy weights.

Usage:
    python src/run_indicator_analysis.py --indicators momentum,trend
    python src/run_indicator_analysis.py --all
"""

import argparse
import logging
import random
from datetime import datetime, timedelta
from bluehorseshoe.analysis.backtest import Backtester, BacktestConfig, BacktestOptions

AVAILABLE_INDICATORS = {
    "momentum": ["macd", "rsi", "roc", "bb_position"],
    "trend": ["stochastic", "ichimoku", "psar", "heiken_ashi", "adx"],
    "volume": ["obv", "cmf", "atr_band", "atr_spike", "avg_volume"],
    "limit": ["pivot", "52_week"],
    "candlestick": ["soldiers", "methods", "marubozu", "belt_hold"],
    "moving_average": ["ma_score", "crossovers"]
}

def get_args():
    """Parses and returns CLI arguments."""
    parser = argparse.ArgumentParser(description='Run Single-Factor Indicator Analysis')
    parser.add_argument('--indicators', type=str, help='Comma-separated list of indicators')
    parser.add_argument('--all', action='store_true', help='Test all main groups individually')
    parser.add_argument('--list', action='store_true', help='List available indicators')
    parser.add_argument('--months', type=int, default=1, help='Months to backtest')
    parser.add_argument('--interval', type=int, default=7, help='Days between runs')
    parser.add_argument('--top_n', type=int, default=10, help='Top candidates per interval')
    parser.add_argument('--convergence', action='store_true', help='Use multiplication')
    parser.add_argument('--combine', action='store_true', help='Combine all specified indicators')
    parser.add_argument('--random', action='store_true', help='Pick random start date')
    return parser.parse_args()

def list_indicators():
    """Prints all available indicators."""
    print("\nAvailable Indicator Groups and Sub-Indicators:")
    print("Format: group:sub_indicator or just 'group' for the whole set\n")
    for group, subs in AVAILABLE_INDICATORS.items():
        print(f"[{group}]")
        for sub in subs:
            print(f"  - {group}:{sub}")

def get_indicators_to_test(args):
    """Determines the list of indicators to test based on arguments."""
    if args.all:
        return list(AVAILABLE_INDICATORS.keys())

    if not args.indicators:
        return []

    if args.convergence or args.combine:
        indicators = [args.indicators]
    else:
        indicators = [i.strip() for i in args.indicators.split(",")]

    # Validate
    for item in indicators:
        for sub_item in item.split(","):
            group = sub_item.strip().split(":")[0]
            if group not in AVAILABLE_INDICATORS:
                print(f"Error: Indicator '{sub_item}' is not recognized.")
                return None
    return indicators

def get_date_range(args):
    """Calculates start and end dates."""
    if args.random:
        latest_possible_end = datetime(2025, 12, 30)
        earliest_possible_start = latest_possible_end - timedelta(days=18 * 30)
        max_start = latest_possible_end - timedelta(days=args.months * 30)
        delta = max_start - earliest_possible_start
        random_days = random.randint(0, delta.days)
        start_date = earliest_possible_start + timedelta(days=random_days)
        end_date = start_date + timedelta(days=args.months * 30)
    else:
        end_date = datetime(2025, 12, 30)
        start_date = end_date - timedelta(days=args.months * 30)
    return start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')

def main():
    """Main entry point."""
    args = get_args()

    if args.list:
        list_indicators()
        return

    indicators_to_test = get_indicators_to_test(args)
    if not indicators_to_test:
        if indicators_to_test is not None:
            print("Error: Please specify --indicators, --all, or --list")
        return

    start_date_str, end_date_str = get_date_range(args)
    print(f"\nStarting Indicator Analysis: {start_date_str} to {end_date_str}", flush=True)

    backtester = Backtester(config=BacktestConfig(target_profit_factor=1.02,
                                                stop_loss_factor=0.97,
                                                hold_days=5))

    aggregation = "product" if args.convergence else "sum"
    total = len(indicators_to_test)

    for idx, indicator in enumerate(indicators_to_test, 1):
        print(f"\n[{idx}/{total}] >>> TESTING INDICATOR: {indicator.upper()} ({aggregation}) <<<",
              flush=True)
        options = BacktestOptions(
            strategy="baseline",
            top_n=args.top_n,
            enabled_indicators=[i.strip() for i in indicator.split(",")],
            aggregation=aggregation
        )
        backtester.run_range_backtest(
            start_date=start_date_str,
            end_date=end_date_str,
            interval_days=args.interval,
            options=options
        )

if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR) # Keep logs quiet for cleaner report
    main()
