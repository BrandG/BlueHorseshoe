import sys
import random
import logging
import pandas as pd
from bluehorseshoe.core.globals import get_mongo_client
from bluehorseshoe.data.historical_data import load_historical_data
from bluehorseshoe.analysis.backtest import Backtester, BacktestOptions, BacktestConfig

# Full list of all sub-indicators available in the system
ALL_INDICATORS = [
    # Trend
    "trend:stochastic", "trend:ichimoku", "trend:psar", "trend:heiken_ashi", 
    "trend:adx", "trend:donchian", "trend:supertrend",
    # Volume
    "volume:obv", "volume:cmf", "volume:atr_band", "volume:atr_spike", 
    "volume:avg_volume", "volume:mfi",
    # Momentum
    "momentum:macd", "momentum:roc", "momentum:rsi", "momentum:bb_position", 
    "momentum:williams_r", "momentum:cci",
    # Moving Average
    "moving_average:ma_score", "moving_average:crossovers",
    # Candlestick
    "candlestick:soldiers", "candlestick:methods", "candlestick:marubozu", "candlestick:belt_hold",
    # Limit
    "limit:pivot", "limit:52_week"
]

def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
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
    valid_dates = df.iloc[100:-7]['date'].tolist()

    if not valid_dates:
        print("Not enough data points to pick a random date.")
        sys.exit(1)

    num_runs_per_indicator = 10
    results_data = []

    # Initialize Backtester
    backtest_config = BacktestConfig(hold_days=5)
    tester = Backtester(config=backtest_config)

    print(f"Starting indicator analysis. Each of the {len(ALL_INDICATORS)} indicators will be tested with {num_runs_per_indicator} backtests.")

    for indicator in ALL_INDICATORS:
        print(f"\n--- Testing Indicator: {indicator} ---")
        
        options = BacktestOptions(
            strategy="baseline",
            top_n=3,
            enabled_indicators=[indicator],
            aggregation="sum"
        )
        
        total_trades = 0
        total_profit = 0.0
        winning_trades = 0

        for i in range(num_runs_per_indicator):
            target_date = random.choice(valid_dates).strftime('%Y-%m-%d')
            print(f"  Run {i+1}/{num_runs_per_indicator} on date {target_date}...")
            
            run_results = tester.run_backtest(target_date, options=options)
            
            if run_results:
                for res in run_results:
                    if res.get('entry') is not None and res.get('exit_price') is not None:
                        total_trades += 1
                        pnl = ((res['exit_price'] / res['entry']) - 1) * 100
                        total_profit += pnl
                        if res['status'] in ['success', 'closed_profit']:
                            winning_trades += 1
        
        # Aggregate results for the indicator
        win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
        avg_pnl = total_profit / total_trades if total_trades > 0 else 0
        
        results_data.append({
            "Indicator": indicator,
            "TotalTrades": total_trades,
            "WinRate": f"{win_rate:.2f}%",
            "AvgPnL": f"{avg_pnl:.2f}%",
            "TotalPnL": f"{total_profit:.2f}%"
        })

    # Save report to CSV
    report_df = pd.DataFrame(results_data)
    report_path = "src/logs/indicator_analysis_report.csv"
    report_df.to_csv(report_path, index=False)
    
    print(f"\n\n##########################################")
    print(f"       INDICATOR ANALYSIS COMPLETE")
    print(f"##########################################")
    print(f"Report saved to {report_path}")
    print(report_df.to_string())

if __name__ == "__main__":
    main()