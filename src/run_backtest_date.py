import sys
import os
import random
import logging
import pandas as pd
import numpy as np
from bluehorseshoe.core.globals import get_mongo_client
from bluehorseshoe.data.historical_data import load_historical_data
from bluehorseshoe.analysis.backtest import Backtester, BacktestOptions, BacktestConfig

def main():
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    # Initialize Mongo
    if get_mongo_client() is None:
        print("Failed to connect to MongoDB.")
        sys.exit(1)

    print("Fetching valid trading dates from SPY...")
    spy_data = load_historical_data("SPY")
    if not spy_data or 'days' not in spy_data:
        print("Could not load SPY data to determine dates.")
        sys.exit(1)

    df = pd.DataFrame(spy_data['days'])
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')

    # Filter dates:
    # 1. Must have at least 100 days of history before (for indicators).
    # 2. Must have at least 7 days of history after (for evaluation).
    valid_dates = df.iloc[100:-7]['date'].tolist()

    if not valid_dates:
        print("Not enough data points to pick a random date.")
        sys.exit(1)

    num_runs = 1
    target_date_arg = None

    if len(sys.argv) > 1:
        arg1 = sys.argv[1]
        try:
            # Try parsing as integer (Number of Random Runs)
            num_runs = int(arg1)
            print(f"Running {num_runs} random backtests.")
        except ValueError:
            # Not an int, assume it is a Date
            target_date_arg = arg1
            print(f"Running backtest for specific date: {target_date_arg}")

    # Initialize Backtester Config
    options = BacktestOptions(
        strategy="baseline",
        top_n=5,
        enabled_indicators=None, # Use default
        aggregation="sum"
    )

    config = BacktestConfig(
        target_profit_factor=1.05, 
        stop_loss_factor=0.95,
        hold_days=5
    )

    tester = Backtester(config=config)
    
    # Aggregators
    total_trades = 0
    total_profit = 0.0
    winning_trades = 0
    
    from bluehorseshoe.analysis.market_regime import MarketRegime

    for i in range(num_runs):
        print(f"\n\n==========================================")
        print(f"          RUN {i+1} OF {num_runs}")
        print(f"==========================================")

        current_date = None
        if target_date_arg:
            try:
                requested_date = pd.to_datetime(target_date_arg)
                if valid_dates[0] <= requested_date <= valid_dates[-1]:
                    current_date = requested_date
                else:
                    print(f"Date {target_date_arg} out of valid range.")
                    continue
            except ValueError:
                print("Invalid date format.")
                sys.exit(1)
        else:
            current_date = random.choice(valid_dates)
            
        date_str = current_date.strftime('%Y-%m-%d')
        print(f">>> Target Date: {date_str} <<< ")
        
        # Check Regime
        regime = MarketRegime.get_market_health(target_date=date_str)
        print(f"Market Regime: {regime['status']} (Multiplier: {regime['multiplier']}x)")

        # Reset strategy for each run based on regime? 
        # For consistency, we stick to logic: Try Baseline, if fails & Bearish -> Try MeanRev.
        options.strategy = "baseline"
        
        print(f"Running Baseline backtest...")
        results = tester.run_backtest(date_str, options=options)
        
        if not results and regime['status'] in ['Bearish', 'Volatile']:
            print("\nNo Baseline candidates found. Attempting Mean Reversion strategy due to regime...")
            options.strategy = "mean_reversion"
            results = tester.run_backtest(date_str, options=options)
            
        # Accumulate stats
        if results:
            for res in results:
                if res.get('entry') is not None and res.get('exit_price') is not None:
                    total_trades += 1
                    pnl = ((res['exit_price'] / res['entry']) - 1) * 100
                    total_profit += pnl
                    if res['status'] in ['success', 'closed_profit']:
                        winning_trades += 1

    # Final Report
    if num_runs > 1:
        print(f"\n\n##########################################")
        print(f"           AGGREGATE REPORT")
        print(f"##########################################")
        print(f"Total Runs: {num_runs}")
        print(f"Total Trades: {total_trades}")
        if total_trades > 0:
            avg_pnl = total_profit / total_trades
            win_rate = (winning_trades / total_trades) * 100
            print(f"Win Rate: {win_rate:.2f}% ({winning_trades}/{total_trades})")
            print(f"Average PnL: {avg_pnl:.2f}%")
            print(f"Total PnL: {total_profit:.2f}%")
        else:
            print("No trades executed.")
        print(f"##########################################")

if __name__ == "__main__":
    main()