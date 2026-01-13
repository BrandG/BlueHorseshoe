"""
Script to analyze trading failures and identify patterns.
"""
import os
import logging
import concurrent.futures
from functools import partial
from typing import List, Dict, Optional
import pandas as pd
from bluehorseshoe.analysis.backtest import Backtester, BacktestConfig
from bluehorseshoe.core.symbols import get_symbol_name_list
from bluehorseshoe.data.historical_data import load_historical_data

def _get_predictions(date_str: str, tester: Backtester, symbols: List[str], score_key: str) -> List[Dict]:
    """Handles parallel processing of symbols to get predictions."""
    predictions = []
    max_workers = min(8, os.cpu_count() or 4)
    total_symbols = len(symbols)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        process_func = partial(tester.trader.process_symbol, target_date=date_str)
        future_to_symbol = {executor.submit(process_func, sym): sym for sym in symbols}

        for i, future in enumerate(concurrent.futures.as_completed(future_to_symbol), 1):
            if i % 500 == 0 or i == total_symbols:
                print(f"  Progress: {i}/{total_symbols} symbols ({(i/total_symbols)*100:.1f}%)", flush=True)

            try:
                result = future.result()
                if result and result.get(score_key, 0) > 0:
                    # Map the specific score to a generic 'score' key for the analysis
                    result['score'] = result[score_key]
                    predictions.append(result)
            except Exception as e: # pylint: disable=broad-exception-caught
                logging.error("Error processing %s: %s", future_to_symbol[future], e)
    return predictions

def _extract_failure_metrics(symbol: str, date_str: str, score: float, status: str) -> Optional[Dict]:
    """Extracts technical metrics for a specific failure."""
    price_data = load_historical_data(symbol)
    if not price_data or 'days' not in price_data:
        return None

    df = pd.DataFrame(price_data['days'])
    df['date'] = pd.to_datetime(df['date'])
    df = df[df['date'] <= pd.to_datetime(date_str)]

    if df.empty:
        return None

    last_row = df.iloc[-1]
    return {
        'date': date_str,
        'symbol': symbol,
        'score': score,
        'rsi': last_row.get('rsi_14'),
        'vol_ratio': last_row['volume'] / last_row.get('avg_volume_20', 1),
        'dist_ema9': (last_row['close'] / df['close'].ewm(span=9).mean().iloc[-1]) - 1,
        'dist_ema21': (last_row['close'] / df['close'].ewm(span=21).mean().iloc[-1]) - 1,
        'status': status
    }

def _evaluate_and_collect_failures(date_str: str, tester: Backtester, predictions: List[Dict], strategy: str) -> List[Dict]:
    """Evaluates top predictions and collects data for failures."""
    date_failures = []
    setup_key = "baseline_setup" if strategy == "baseline" else "mr_setup"

    for pred in predictions:
        # Flatten setup dict for evaluate_prediction
        setup = pred.get(setup_key, {})
        pred.update({
            'entry_price': setup.get('entry_price'),
            'stop_loss': setup.get('stop_loss'),
            'take_profit': setup.get('take_profit')
        })

        eval_res = tester.evaluate_prediction(pred, date_str)
        if eval_res['status'] in ['failure', 'closed_loss']:
            failure_data = _extract_failure_metrics(pred['symbol'], date_str, pred['score'], eval_res['status'])
            if failure_data:
                date_failures.append(failure_data)
    return date_failures

def process_date(date_str, tester, strategy="mean_reversion", top_n=10):
    """
    Processes a single date, identifies top predictions, and evaluates their outcomes.
    """
    print(f"Analyzing {date_str} for strategy {strategy}...", flush=True)
    symbols = get_symbol_name_list()
    score_key = "mr_score" if strategy == "mean_reversion" else "baseline_score"

    predictions = _get_predictions(date_str, tester, symbols, score_key)
    valid_predictions = sorted(predictions, key=lambda x: x['score'], reverse=True)[:top_n]

    return _evaluate_and_collect_failures(date_str, tester, valid_predictions, strategy)

def analyze_failures(start_date, end_date, strategy="mean_reversion", interval_days=7):
    """
    Analyzes trading failures over a given period.
    """
    config = BacktestConfig(target_profit_factor=1.02, stop_loss_factor=0.98, hold_days=3)
    tester = Backtester(config)

    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date)
    current_ts = start_ts

    failures = []
    while current_ts <= end_ts:
        date_str = current_ts.strftime('%Y-%m-%d')
        failures.extend(process_date(date_str, tester, strategy=strategy))
        current_ts += pd.Timedelta(days=interval_days)

    df_failures = pd.DataFrame(failures)
    print(f"\n--- Failure Analysis Data for {strategy} ---", flush=True)
    if not df_failures.empty:
        print(df_failures.to_string(), flush=True)
        df_failures.to_csv(f'src/logs/failure_analysis_{strategy}.csv', index=False)

        print("\nAverages for Failures:", flush=True)
        print(df_failures[['score', 'rsi', 'vol_ratio', 'dist_ema9', 'dist_ema21']].mean(), flush=True)
    else:
        print("No failures found in the specified range.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-11-10")
    parser.add_argument("--end", default="2025-12-15")
    parser.add_argument("--strategy", default="mean_reversion")
    args = parser.parse_args()

    print(f"Script started for {args.strategy}...", flush=True)
    try:
        analyze_failures(args.start, args.end, strategy=args.strategy)
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"Error occurred: {e}", flush=True)
        import traceback
        traceback.print_exc()
