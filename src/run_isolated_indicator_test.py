#!/usr/bin/env python3
"""
Phase 1: Isolated Indicator Testing

Tests a single indicator in isolation by zeroing out all other indicator multipliers.
Runs multiple backtests and tracks results for comparison.

Usage:
    # Test RSI alone with current settings
    python src/run_isolated_indicator_test.py --indicator RSI --runs 20

    # Test RSI with custom multiplier
    python src/run_isolated_indicator_test.py --indicator RSI --multiplier 2.0 --runs 20

    # Test with a specific name for tracking
    python src/run_isolated_indicator_test.py --indicator RSI --name rsi_boost_2x --multiplier 2.0 --runs 20
"""

import sys
import os
import json
import logging
import random
from datetime import datetime
from pathlib import Path
import pandas as pd
import numpy as np
from bluehorseshoe.core.container import create_app_container
from bluehorseshoe.data.historical_data import load_historical_data
from bluehorseshoe.analysis.backtest import Backtester, BacktestOptions, BacktestConfig
from bluehorseshoe.analysis.market_regime import MarketRegime

# Ensure experiments directory exists
EXPERIMENTS_DIR = Path("/workspaces/BlueHorseshoe/src/experiments")
EXPERIMENTS_DIR.mkdir(exist_ok=True)
(EXPERIMENTS_DIR / "results").mkdir(exist_ok=True)

def create_isolated_weights(indicator_name: str, multiplier: float = 1.0) -> dict:
    """
    Create a weights config with only the specified indicator active.

    Args:
        indicator_name: Name of indicator to test (e.g., 'RSI', 'ADX', 'MACD')
        multiplier: Multiplier value for the active indicator

    Returns:
        Dict with all multipliers zeroed except the target indicator
    """
    # Start with all zeros
    weights = {
        "trend": {
            "ADX_MULTIPLIER": 0.0,
            "STOCHASTIC_MULTIPLIER": 0.0,
            "ICHIMOKU_MULTIPLIER": 0.0,
            "PSAR_MULTIPLIER": 0.0,
            "HEIKEN_ASHI_MULTIPLIER": 0.0,
            "DONCHIAN_MULTIPLIER": 0.0,
            "SUPERTREND_MULTIPLIER": 0.0
        },
        "momentum": {
            "RSI_MULTIPLIER": 0.0,
            "ROC_MULTIPLIER": 0.0,
            "MACD_MULTIPLIER": 0.0,
            "MACD_SIGNAL_MULTIPLIER": 0.0,
            "BB_MULTIPLIER": 0.0,
            "WILLIAMS_R_MULTIPLIER": 0.0,
            "CCI_MULTIPLIER": 0.0
        },
        "volume": {
            "OBV_MULTIPLIER": 0.0,
            "CMF_MULTIPLIER": 0.0,
            "ATR_BAND_MULTIPLIER": 0.0,
            "ATR_SPIKE_MULTIPLIER": 0.0,
            "MFI_MULTIPLIER": 0.0
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
        }
    }

    # Activate the target indicator
    indicator_key = f"{indicator_name.upper()}_MULTIPLIER"
    found = False

    for category in weights.values():
        if indicator_key in category:
            category[indicator_key] = multiplier
            found = True
            break

    if not found:
        raise ValueError(f"Indicator '{indicator_name}' not found in weights config")

    return weights


def get_valid_dates(database, min_history_days=100, min_future_days=7):
    """Get valid trading dates from SPY data."""
    spy_data = load_historical_data("SPY", database=database)
    if not spy_data or 'days' not in spy_data:
        raise ValueError("Could not load SPY data to determine dates")

    df = pd.DataFrame(spy_data['days'])
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')

    # Filter: need history before and future after
    valid_dates = df.iloc[min_history_days:-min_future_days]['date'].tolist()

    if not valid_dates:
        raise ValueError("Not enough data points for valid date range")

    return valid_dates


def run_experiment(
    indicator_name: str,
    multiplier: float,
    num_runs: int,
    experiment_name: str = None,
    strategy: str = "baseline"
) -> dict:
    """
    Run an isolated indicator experiment.

    Args:
        indicator_name: Indicator to test
        multiplier: Multiplier value
        num_runs: Number of random backtest runs
        experiment_name: Optional name for tracking (auto-generated if not provided)
        strategy: Strategy to use ('baseline' or 'mean_reversion')

    Returns:
        Dict with experiment results
    """
    # Generate experiment name if not provided
    if experiment_name is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        experiment_name = f"{indicator_name.lower()}_m{multiplier}_{timestamp}"

    print("=" * 70)
    print(f"ISOLATED INDICATOR TEST: {indicator_name}")
    print("=" * 70)
    print(f"Experiment Name: {experiment_name}")
    print(f"Multiplier: {multiplier}")
    print(f"Strategy: {strategy}")
    print(f"Number of Runs: {num_runs}")
    print("=" * 70)
    print()

    # Create isolated weights config
    isolated_weights = create_isolated_weights(indicator_name, multiplier)

    # Save config temporarily
    temp_config_path = EXPERIMENTS_DIR / "results" / f"{experiment_name}_config.json"
    with open(temp_config_path, 'w') as f:
        json.dump(isolated_weights, f, indent=2)

    print(f"Created isolated config: {temp_config_path}")

    # Temporarily override weights.json
    original_weights_path = Path("/workspaces/BlueHorseshoe/src/weights.json")
    backup_weights_path = Path("/workspaces/BlueHorseshoe/src/weights.json.backup")

    # Backup original weights
    import shutil
    shutil.copy(original_weights_path, backup_weights_path)

    try:
        # Write isolated weights
        with open(original_weights_path, 'w') as f:
            json.dump(isolated_weights, f, indent=2)

        print("✓ Temporarily using isolated weights")
        print()

        # Setup database
        container = create_app_container()
        database = container.get_database()

        # Get valid dates
        valid_dates = get_valid_dates(database)

        # Initialize backtester
        config = BacktestConfig(
            target_profit_factor=1.05,
            stop_loss_factor=0.95,
            hold_days=5
        )

        tester = Backtester(config=config, database=database)

        # Load all symbols once
        from bluehorseshoe.core.symbols import get_symbol_name_list
        all_symbols = get_symbol_name_list(database=database)
        print(f"Loaded {len(all_symbols)} total symbols from database")
        print(f"Will sample 1,000 random symbols per run for faster testing")
        print()

        # Track results
        all_trades = []
        total_trades = 0
        winning_trades = 0
        total_pnl = 0.0
        pnl_per_trade = []

        # Run experiments
        for i in range(num_runs):
            print(f"\n--- Run {i+1}/{num_runs} ---")

            # Pick random date
            current_date = random.choice(valid_dates)
            date_str = current_date.strftime('%Y-%m-%d')
            print(f"Date: {date_str}")

            # Check market regime
            regime = MarketRegime.get_market_health(target_date=date_str, database=database)
            print(f"Regime: {regime['status']} ({regime['multiplier']}x)")

            # Sample 1,000 random symbols for this run
            sample_size = min(1000, len(all_symbols))
            sampled_symbols = random.sample(all_symbols, sample_size)
            print(f"Sampled {sample_size} symbols for backtest")

            # Run backtest
            options = BacktestOptions(strategy=strategy, top_n=5, symbols=sampled_symbols)
            results = tester.run_backtest(date_str, options=options)

            # Process results
            if results:
                for res in results:
                    if res.get('entry') is not None and res.get('exit_price') is not None:
                        pnl = ((res['exit_price'] / res['entry']) - 1) * 100
                        is_win = res['status'] in ['success', 'closed_profit']

                        total_trades += 1
                        total_pnl += pnl
                        pnl_per_trade.append(pnl)

                        if is_win:
                            winning_trades += 1

                        all_trades.append({
                            'run': i + 1,
                            'date': date_str,
                            'symbol': res.get('symbol', 'UNKNOWN'),
                            'entry': res['entry'],
                            'exit': res['exit_price'],
                            'pnl_pct': pnl,
                            'status': res['status'],
                            'regime': regime['status']
                        })

                print(f"Trades: {len(results)}")
            else:
                print("No trades")

        # Calculate statistics
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0

        # Calculate Sharpe Ratio (annualized, assuming ~252 trading days)
        sharpe_ratio = 0.0
        if len(pnl_per_trade) > 1:
            std_pnl = np.std(pnl_per_trade, ddof=1)
            if std_pnl > 0:
                sharpe_ratio = (avg_pnl / std_pnl) * np.sqrt(252 / 5)  # 5-day holds

        # Calculate max drawdown
        max_drawdown = 0.0
        if pnl_per_trade:
            cumulative = np.cumsum(pnl_per_trade)
            running_max = np.maximum.accumulate(cumulative)
            drawdown = running_max - cumulative
            max_drawdown = np.max(drawdown) if len(drawdown) > 0 else 0.0

        # Compile results
        experiment_results = {
            'experiment_name': experiment_name,
            'indicator': indicator_name,
            'multiplier': multiplier,
            'strategy': strategy,
            'timestamp': datetime.now().isoformat(),
            'runs': num_runs,
            'metrics': {
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'win_rate': win_rate,
                'avg_pnl': avg_pnl,
                'total_pnl': total_pnl,
                'sharpe_ratio': sharpe_ratio,
                'max_drawdown': max_drawdown,
                'pnl_std': np.std(pnl_per_trade, ddof=1) if len(pnl_per_trade) > 1 else 0.0
            },
            'trades': all_trades
        }

        # Save results
        results_path = EXPERIMENTS_DIR / "results" / f"{experiment_name}.json"
        with open(results_path, 'w') as f:
            json.dump(experiment_results, f, indent=2)

        print("\n" + "=" * 70)
        print("EXPERIMENT RESULTS")
        print("=" * 70)
        print(f"Total Trades: {total_trades}")
        print(f"Win Rate: {win_rate:.2f}% ({winning_trades}/{total_trades})")
        print(f"Average PnL: {avg_pnl:.2f}%")
        print(f"Total PnL: {total_pnl:.2f}%")
        print(f"Sharpe Ratio: {sharpe_ratio:.3f}")
        print(f"Max Drawdown: {max_drawdown:.2f}%")
        print(f"PnL Std Dev: {experiment_results['metrics']['pnl_std']:.2f}%")
        print("=" * 70)
        print(f"\n✓ Results saved: {results_path}")

        container.close()

        return experiment_results

    finally:
        # Restore original weights if backup exists
        if backup_weights_path.exists():
            shutil.move(backup_weights_path, original_weights_path)
            print("\n✓ Restored original weights.json")
        else:
            # Backup not found (race condition from parallel tests) - restore to safe default
            print("\n⚠ Warning: Backup weights file not found, restoring to default (all zeros)")
            default_weights = {
                "trend": {
                    "ADX_MULTIPLIER": 0.0,
                    "STOCHASTIC_MULTIPLIER": 0.0,
                    "ICHIMOKU_MULTIPLIER": 0.0,
                    "PSAR_MULTIPLIER": 0.0,
                    "HEIKEN_ASHI_MULTIPLIER": 0.0,
                    "DONCHIAN_MULTIPLIER": 0.0,
                    "SUPERTREND_MULTIPLIER": 0.0
                },
                "momentum": {
                    "RSI_MULTIPLIER": 0.0,
                    "ROC_MULTIPLIER": 0.0,
                    "MACD_MULTIPLIER": 0.0,
                    "MACD_SIGNAL_MULTIPLIER": 0.0,
                    "BB_MULTIPLIER": 0.0,
                    "WILLIAMS_R_MULTIPLIER": 0.0,
                    "CCI_MULTIPLIER": 0.0
                },
                "volume": {
                    "OBV_MULTIPLIER": 0.0,
                    "CMF_MULTIPLIER": 0.0,
                    "ATR_BAND_MULTIPLIER": 0.0,
                    "ATR_SPIKE_MULTIPLIER": 0.0,
                    "MFI_MULTIPLIER": 0.0
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
                }
            }
            with open(original_weights_path, 'w') as f:
                json.dump(default_weights, f, indent=2)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Phase 1: Test a single indicator in isolation"
    )
    parser.add_argument(
        '--indicator',
        required=True,
        help='Indicator to test (e.g., RSI, ADX, MACD)'
    )
    parser.add_argument(
        '--multiplier',
        type=float,
        default=1.0,
        help='Multiplier value for the indicator (default: 1.0)'
    )
    parser.add_argument(
        '--runs',
        type=int,
        default=20,
        help='Number of backtest runs (default: 20)'
    )
    parser.add_argument(
        '--name',
        help='Experiment name (auto-generated if not provided)'
    )
    parser.add_argument(
        '--strategy',
        default='baseline',
        choices=['baseline', 'mean_reversion'],
        help='Strategy to use (default: baseline)'
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(level=logging.WARNING, format='%(message)s')

    # Run experiment
    run_experiment(
        indicator_name=args.indicator,
        multiplier=args.multiplier,
        num_runs=args.runs,
        experiment_name=args.name,
        strategy=args.strategy
    )


if __name__ == "__main__":
    main()
