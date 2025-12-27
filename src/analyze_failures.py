
import pandas as pd
from bluehorseshoe.analysis.backtest import Backtester
from bluehorseshoe.core.symbols import get_symbol_name_list
from bluehorseshoe.data.historical_data import load_historical_data
import logging

import pandas as pd
from bluehorseshoe.analysis.backtest import Backtester
from bluehorseshoe.core.symbols import get_symbol_name_list
from bluehorseshoe.data.historical_data import load_historical_data
import logging
import concurrent.futures
from functools import partial
import os

def process_date(date_str, tester, top_n=10):
    print(f"Analyzing {date_str}...", flush=True)
    symbols = get_symbol_name_list()
    predictions = []
    
    max_workers = min(8, os.cpu_count() or 4)
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        process_func = partial(tester.trader.process_symbol, target_date=date_str)
        future_to_symbol = {executor.submit(process_func, sym): sym for sym in symbols}
        
        for future in concurrent.futures.as_completed(future_to_symbol):
            try:
                result = future.result()
                if result:
                    predictions.append(result)
            except Exception:
                pass
                
    valid_predictions = sorted(predictions, key=lambda x: x['score'], reverse=True)[:top_n]
    
    date_failures = []
    for pred in valid_predictions:
        eval_res = tester.evaluate_prediction(pred, date_str)
        if eval_res['status'] == 'failure':
            symbol = pred['symbol']
            price_data = load_historical_data(symbol)
            df = pd.DataFrame(price_data['days'])
            df['date'] = pd.to_datetime(df['date'])
            df = df[df['date'] <= pd.to_datetime(date_str)]
            
            last_row = df.iloc[-1]
            failure_data = {
                'date': date_str,
                'symbol': symbol,
                'score': pred['score'],
                'rsi': last_row.get('rsi_14'),
                'vol_ratio': last_row['volume'] / last_row.get('avg_volume_20', 1),
                'dist_ema9': (last_row['close'] / df['close'].ewm(span=9).mean().iloc[-1]) - 1,
                'dist_ema21': (last_row['close'] / df['close'].ewm(span=21).mean().iloc[-1]) - 1,
            }
            date_failures.append(failure_data)
    return date_failures

def analyze_failures(start_date, end_date, interval_days=7):
    tester = Backtester(target_profit_factor=1.02, stop_loss_factor=0.98, hold_days=5)
    dates = ['2025-11-10', '2025-12-15']
    
    failures = []
    for date_str in dates:
        failures.extend(process_date(date_str, tester))
    
    df_failures = pd.DataFrame(failures)
    print("\n--- Failure Analysis Data ---", flush=True)
    print(df_failures, flush=True)
    df_failures.to_csv('src/logs/failure_analysis.csv', index=False)
    
    if not df_failures.empty:
        print("\nAverages for Failures:", flush=True)
        print(df_failures[['score', 'rsi', 'vol_ratio', 'dist_ema9', 'dist_ema21']].mean(), flush=True)
    
    df_failures = pd.DataFrame(failures)
    print("\n--- Failure Analysis Data ---")
    print(df_failures)
    df_failures.to_csv('src/logs/failure_analysis.csv', index=False)
    
    if not df_failures.empty:
        print("\nAverages for Failures:")
        print(df_failures[['score', 'rsi', 'vol_ratio', 'dist_ema9', 'dist_ema21']].mean())

if __name__ == "__main__":
    print("Script started...", flush=True)
    try:
        analyze_failures('2025-11-10', '2025-12-15')
    except Exception as e:
        print(f"Error occurred: {e}", flush=True)
        import traceback
        traceback.print_exc()
