#!/usr/bin/env python3
"""
Phase 3A: Isolated Indicator Testing

Tests each of the 8 Phase 3 indicators in isolation at multiple weight levels
to determine standalone performance and optimal weights.

Uses random sample of 1,000 symbols per backtest for statistical significance
while maintaining reasonable execution time.

Usage:
    python src/run_phase3_testing.py --indicator RS --weight 1.0 --runs 20
    python src/run_phase3_testing.py --indicator all --runs 20
"""

import sys
import os
import json
import argparse
import subprocess
import random
from datetime import datetime, timedelta
from pathlib import Path
from pymongo import MongoClient

# Phase 3 indicator configurations
PHASE3_INDICATORS = {
    'RS': {
        'category': 'momentum',
        'multiplier': 'RS_MULTIPLIER',
        'name': 'Relative Strength vs SPY',
        'weights': [0.5, 1.0, 1.5, 2.0]
    },
    'GAP': {
        'category': 'price_action',
        'multiplier': 'GAP_MULTIPLIER',
        'name': 'Gap Analysis',
        'weights': [0.5, 1.0, 1.5, 2.0]
    },
    'VWAP': {
        'category': 'volume',
        'multiplier': 'VWAP_MULTIPLIER',
        'name': 'VWAP',
        'weights': [0.5, 1.0, 1.5, 2.0]
    },
    'TTM': {
        'category': 'trend',
        'multiplier': 'TTM_SQUEEZE_MULTIPLIER',
        'name': 'TTM Squeeze',
        'weights': [0.5, 1.0, 1.5, 2.0]
    },
    'AROON': {
        'category': 'trend',
        'multiplier': 'AROON_MULTIPLIER',
        'name': 'Aroon Indicator',
        'weights': [0.5, 1.0, 1.5, 2.0]
    },
    'KELTNER': {
        'category': 'trend',
        'multiplier': 'KELTNER_MULTIPLIER',
        'name': 'Keltner Channels',
        'weights': [0.5, 1.0, 1.5, 2.0]
    },
    'FORCE': {
        'category': 'volume',
        'multiplier': 'FORCE_INDEX_MULTIPLIER',
        'name': 'Elder\'s Force Index',
        'weights': [0.5, 1.0, 1.5, 2.0]
    },
    'AD': {
        'category': 'volume',
        'multiplier': 'AD_LINE_MULTIPLIER',
        'name': 'A/D Line',
        'weights': [0.5, 1.0, 1.5, 2.0]
    }
}

# Zero config template
ZERO_CONFIG = {
    "trend": {
        "ADX_MULTIPLIER": 0.0,
        "STOCHASTIC_MULTIPLIER": 0.0,
        "ICHIMOKU_MULTIPLIER": 0.0,
        "PSAR_MULTIPLIER": 0.0,
        "HEIKEN_ASHI_MULTIPLIER": 0.0,
        "DONCHIAN_MULTIPLIER": 0.0,
        "SUPERTREND_MULTIPLIER": 0.0,
        "TTM_SQUEEZE_MULTIPLIER": 0.0,
        "AROON_MULTIPLIER": 0.0,
        "KELTNER_MULTIPLIER": 0.0
    },
    "momentum": {
        "RSI_MULTIPLIER": 0.0,
        "ROC_MULTIPLIER": 0.0,
        "MACD_MULTIPLIER": 0.0,
        "MACD_SIGNAL_MULTIPLIER": 0.0,
        "BB_MULTIPLIER": 0.0,
        "WILLIAMS_R_MULTIPLIER": 0.0,
        "CCI_MULTIPLIER": 0.0,
        "RS_MULTIPLIER": 0.0
    },
    "volume": {
        "OBV_MULTIPLIER": 0.0,
        "CMF_MULTIPLIER": 0.0,
        "ATR_BAND_MULTIPLIER": 0.0,
        "ATR_SPIKE_MULTIPLIER": 0.0,
        "MFI_MULTIPLIER": 0.0,
        "VWAP_MULTIPLIER": 0.0,
        "FORCE_INDEX_MULTIPLIER": 0.0,
        "AD_LINE_MULTIPLIER": 0.0
    },
    "candlestick": {
        "RISE_FALL_3_METHODS_MULTIPLIER": 0.0,
        "THREE_WHITE_SOLDIERS_MULTIPLIER": 0.0,
        "MARUBOZU_MULTIPLIER": 0.0,
        "BELT_HOLD_MULTIPLIER": 0.0
    },
    "mean_reversion": {
        "RSI_MULTIPLIER": 0.0,
        "BB_MULTIPLIER": 0.0,
        "MA_DIST_MULTIPLIER": 0.0,
        "CANDLESTICK_MULTIPLIER": 0.0
    },
    "price_action": {
        "GAP_MULTIPLIER": 0.0
    }
}


def create_test_config(indicator_code, weight):
    """Create a weights.json config with only one indicator enabled."""
    config = json.loads(json.dumps(ZERO_CONFIG))  # Deep copy

    indicator_info = PHASE3_INDICATORS[indicator_code]
    category = indicator_info['category']
    multiplier = indicator_info['multiplier']

    config[category][multiplier] = weight

    return config


def get_random_symbols(sample_size=1000):
    """Get random sample of symbols from MongoDB."""
    # Use the container's internal MongoDB connection
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://mongo:27017')
    mongo_db = os.getenv('MONGO_DB', 'bluehorseshoe')

    client = MongoClient(mongo_uri)
    db = client[mongo_db]

    # Get all symbols from the symbols collection
    all_symbols = list(db.symbols.find({}, {'symbol': 1, '_id': 0}))
    symbol_list = [s['symbol'] for s in all_symbols]

    client.close()

    # Return random sample
    if len(symbol_list) <= sample_size:
        return symbol_list
    return random.sample(symbol_list, sample_size)


def generate_random_dates(start_date, end_date, num_dates):
    """Generate random dates between start and end."""
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')

    dates = []
    for _ in range(num_dates):
        random_days = random.randint(0, (end - start).days)
        random_date = start + timedelta(days=random_days)
        dates.append(random_date.strftime('%Y-%m-%d'))

    return dates


def run_backtest(date, symbols):
    """Run a single backtest for the given date with specified symbols."""
    symbols_str = ','.join(symbols)
    cmd = ['python', 'src/main.py', '-t', date, '--symbols', symbols_str]

    try:
        # 30 minutes timeout - backtests can take longer with symbol filtering
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, cwd='/workspaces/BlueHorseshoe')
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"    ⚠️  Backtest timeout for {date}")
        return False


def test_indicator(indicator_code, weight, num_runs, start_date, end_date, sample_size=1000):
    """Test a single indicator at a specific weight."""
    indicator_info = PHASE3_INDICATORS[indicator_code]
    indicator_name = indicator_info['name']

    print(f"\n{'='*80}")
    print(f"Testing: {indicator_name} at {weight}x weight")
    print(f"Runs: {num_runs} | Sample size: {sample_size} symbols")
    print(f"{'='*80}")

    # Create and save test config
    config = create_test_config(indicator_code, weight)
    config_path = Path('/workspaces/BlueHorseshoe/src/weights.json')
    backup_path = Path('/workspaces/BlueHorseshoe/src/weights.json.phase3_backup')

    # Backup current config
    if config_path.exists():
        with open(config_path, 'r') as f:
            backup_config = f.read()
        with open(backup_path, 'w') as f:
            f.write(backup_config)

    # Write test config
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    # Generate random test dates
    test_dates = generate_random_dates(start_date, end_date, num_runs)

    # Get random symbol sample (same symbols for all runs to ensure consistency)
    print(f"Selecting {sample_size} random symbols...", end=' ', flush=True)
    test_symbols = get_random_symbols(sample_size)
    print(f"✓ ({len(test_symbols)} symbols)")

    # Run backtests
    successful_runs = 0
    for i, date in enumerate(test_dates, 1):
        print(f"  Run {i}/{num_runs}: {date}...", end=' ', flush=True)

        if run_backtest(date, test_symbols):
            print("✅")
            successful_runs += 1
        else:
            print("❌")

    # Restore original config
    if backup_path.exists():
        with open(backup_path, 'r') as f:
            original_config = f.read()
        with open(config_path, 'w') as f:
            f.write(original_config)
        backup_path.unlink()

    print(f"\nCompleted: {successful_runs}/{num_runs} successful runs")

    return successful_runs


def main():
    parser = argparse.ArgumentParser(description='Phase 3A Isolated Indicator Testing')
    parser.add_argument('--indicator', type=str, required=True,
                       choices=list(PHASE3_INDICATORS.keys()) + ['all'],
                       help='Indicator to test (or "all" for all indicators)')
    parser.add_argument('--weight', type=float,
                       help='Weight to test (omit to test all weights for indicator)')
    parser.add_argument('--runs', type=int, default=20,
                       help='Number of backtest runs per configuration (default: 20)')
    parser.add_argument('--sample-size', type=int, default=1000,
                       help='Number of random symbols to test per backtest (default: 1000)')
    parser.add_argument('--start-date', type=str, default='2024-01-01',
                       help='Start date for random backtest dates (default: 2024-01-01)')
    parser.add_argument('--end-date', type=str, default='2026-01-27',
                       help='End date for random backtest dates (default: 2026-01-27)')

    args = parser.parse_args()

    # Determine which indicators to test
    if args.indicator == 'all':
        indicators_to_test = list(PHASE3_INDICATORS.keys())
    else:
        indicators_to_test = [args.indicator]

    # Track overall progress
    total_tests = 0
    total_successful = 0

    print(f"\n{'#'*80}")
    print(f"# PHASE 3A: ISOLATED INDICATOR TESTING")
    print(f"#")
    print(f"# Indicators: {len(indicators_to_test)}")
    print(f"# Runs per config: {args.runs}")
    print(f"# Sample size: {args.sample_size} symbols per backtest")
    print(f"# Date range: {args.start_date} to {args.end_date}")
    print(f"{'#'*80}\n")

    # Run tests
    for indicator_code in indicators_to_test:
        indicator_info = PHASE3_INDICATORS[indicator_code]

        # Determine which weights to test
        if args.weight is not None:
            weights_to_test = [args.weight]
        else:
            weights_to_test = indicator_info['weights']

        for weight in weights_to_test:
            successful = test_indicator(
                indicator_code,
                weight,
                args.runs,
                args.start_date,
                args.end_date,
                sample_size=args.sample_size
            )

            total_tests += args.runs
            total_successful += successful

    # Summary
    print(f"\n{'='*80}")
    print(f"PHASE 3A TESTING COMPLETE")
    print(f"{'='*80}")
    print(f"Total backtests run: {total_tests}")
    print(f"Successful: {total_successful}/{total_tests} ({total_successful/total_tests*100:.1f}%)")
    print(f"\nResults saved to: src/logs/backtest_log.csv")
    print(f"\nNext step: Analyze results with Phase 3A analysis script")
    print(f"{'='*80}\n")


if __name__ == '__main__':
    main()
