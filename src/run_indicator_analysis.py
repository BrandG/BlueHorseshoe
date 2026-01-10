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
from bluehorseshoe.analysis.backtest import Backtester

def main():
    available_indicators = {
        "momentum": ["macd", "rsi", "roc", "bb_position"],
        "trend": ["stochastic", "ichimoku", "psar", "heiken_ashi", "adx"],
        "volume": ["obv", "cmf", "atr_band", "atr_spike", "avg_volume"],
        "limit": ["pivot", "52_week"],
        "candlestick": ["soldiers", "methods", "marubozu", "belt_hold"],
        "moving_average": ["ma_score", "crossovers"]
    }

    parser = argparse.ArgumentParser(description='Run Single-Factor Indicator Analysis')
    parser.add_argument('--indicators', type=str, help='Comma-separated list of indicators (e.g., momentum:macd,trend)')
    parser.add_argument('--all', action='store_true', help='Test all main groups individually')
    parser.add_argument('--list', action='store_true', help='List all available indicators and sub-indicators')
    parser.add_argument('--months', type=int, default=1, help='Number of months to backtest (default: 1)')
    parser.add_argument('--interval', type=int, default=7, help='Days between backtest runs (default: 7)')
    parser.add_argument('--top_n', type=int, default=10, help='Number of top candidates to trade per interval (default: 10)')
    parser.add_argument('--convergence', action='store_true', help='Use multiplication (convergence) instead of summation for indicator scores')
    parser.add_argument('--combine', action='store_true', help='Combine all specified indicators into a single test case')
    parser.add_argument('--random', action='store_true', help='Pick a random start date within the last 18 months')

    args = parser.parse_args()

    if args.list:
        print("\nAvailable Indicator Groups and Sub-Indicators:")
        print("Format: group:sub_indicator or just 'group' for the whole set\n")
        for group, subs in available_indicators.items():
            print(f"[{group}]")
            for sub in subs:
                print(f"  - {group}:{sub}")
        return

    indicators_to_test = []
    if args.all:
        indicators_to_test = list(available_indicators.keys())
    elif args.indicators:
        if args.convergence or args.combine:
            # Test the entire list as a single combined unit
            indicators_to_test = [args.indicators]
        else:
            # Test them one by one
            indicators_to_test = [i.strip() for i in args.indicators.split(",")]

        # Validate all mentioned indicators
        for i in indicators_to_test:
            for sub_i in i.split(","):
                group = sub_i.strip().split(":")[0]
                if group not in available_indicators:
                    print(f"Error: Indicator '{sub_i}' is not recognized. Use --list to see options.")
                    return
    else:
        print("Error: Please specify --indicators, --all, or --list")
        return

    # Set up date range
    if args.random:
        # Pick a random start date between 18 months ago and (1 month + requested duration) ago
        # Max end date is 2025-12-30
        latest_possible_end = datetime(2025, 12, 30)
        earliest_possible_start = latest_possible_end - timedelta(days=18 * 30)

        # Calculate max possible start to allow for the requested duration
        max_start = latest_possible_end - timedelta(days=args.months * 30)

        delta = max_start - earliest_possible_start
        random_days = random.randint(0, delta.days)

        start_date = earliest_possible_start + timedelta(days=random_days)
        end_date = start_date + timedelta(days=args.months * 30)
    else:
        # Default to the most recent period
        end_date = datetime(2025, 12, 30)
        start_date = end_date - timedelta(days=args.months * 30)

    start_date_str = start_date.strftime('%Y-%m-%d')
    end_date_str = end_date.strftime('%Y-%m-%d')

    print(f"\nStarting Indicator Analysis for period: {start_date_str} to {end_date_str}", flush=True)

    print("Initializing Backtester...", end="", flush=True)
    backtester = Backtester(target_profit_factor=1.02, stop_loss_factor=0.97, hold_days=5)
    print(" Done.", flush=True)

    print(f"Hold Period: {backtester.hold_days} days | Interval: {args.interval} days\n", flush=True)

    aggregation = "product" if args.convergence else "sum"

    total_indicators = len(indicators_to_test)
    for idx, indicator in enumerate(indicators_to_test, 1):
        label = indicator.upper()
        current_enabled = [i.strip() for i in indicator.split(",")]

        print(f"\n[{idx}/{total_indicators}] >>> TESTING INDICATOR: {label} (Agg: {aggregation}) <<<", flush=True)
        backtester.run_range_backtest(
            start_date=start_date_str,
            end_date=end_date_str,
            interval_days=args.interval,
            top_n=args.top_n,
            strategy="baseline",
            enabled_indicators=current_enabled,
            aggregation=aggregation
        )

if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR) # Keep logs quiet for cleaner report
    main()
