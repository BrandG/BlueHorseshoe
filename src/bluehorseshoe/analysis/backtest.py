"""
backtest.py

This module provides functionality for backtesting the swing trading strategy.
It allows for historical performance evaluation by simulating trades based on 
past data and verifying results against subsequent price action.
"""

import logging
import pandas as pd
import concurrent.futures
from typing import List, Optional, Dict
from functools import partial
from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.core.symbols import get_symbol_name_list
from bluehorseshoe.data.historical_data import load_historical_data
from bluehorseshoe.reporting.report_generator import ReportSingleton

class Backtester:
    """Class for orchestrating historical backtests of the trading strategy."""

    def __init__(self, target_profit_factor: float = 1.01, stop_loss_factor: float = 0.98, hold_days: int = 3):
        self.trader = SwingTrader()
        self.target_profit_factor = target_profit_factor
        self.stop_loss_factor = stop_loss_factor
        self.hold_days = hold_days

    def evaluate_prediction(self, prediction: Dict, target_date: str) -> Dict:
        """
        Evaluates a single prediction against the price action of the following trading days.
        
        Logic:
        1. Assume entry at 'Open' of the first trading day AFTER target_date.
        2. Track the trade for up to self.hold_days.
        3. Check if take_profit or stop_loss is hit.
        """
        symbol = prediction['symbol']
        
        price_data = load_historical_data(symbol)
        if not price_data or 'days' not in price_data:
            return {'symbol': symbol, 'status': 'no_data'}

        df = pd.DataFrame(price_data['days'])
        df['date'] = pd.to_datetime(df['date'])
        target_ts = pd.to_datetime(target_date)
        
        # Get data after target_date
        future_data = df[df['date'] > target_ts].sort_values('date').head(self.hold_days)
        if future_data.empty:
            return {'symbol': symbol, 'status': 'no_future_data'}

        # Entry logic: Buy at Open of the first available day
        entry_day = future_data.iloc[0]
        actual_entry = entry_day['open']
        
        # Targets based on actual entry
        actual_take_profit = actual_entry * self.target_profit_factor
        actual_stop_loss = actual_entry * self.stop_loss_factor

        status = 'hold'
        exit_date = None
        exit_price = None

        for _, day in future_data.iterrows():
            high = day['high']
            low = day['low']
            
            # Check for success first (priority to profit in same-day volatility)
            if high >= actual_take_profit:
                status = 'success'
                exit_price = actual_take_profit
                exit_date = day['date'].strftime('%Y-%m-%d')
                break
            
            # Check for failure
            if low <= actual_stop_loss:
                status = 'failure'
                exit_price = actual_stop_loss
                exit_date = day['date'].strftime('%Y-%m-%d')
                break

        if status == 'hold':
            # If still holding after hold_days, exit at the last day's Close
            last_day = future_data.iloc[-1]
            exit_price = last_day['close']
            exit_date = last_day['date'].strftime('%Y-%m-%d')
            if exit_price > actual_entry:
                status = 'closed_profit'
            else:
                status = 'closed_loss'

        return {
            'symbol': symbol,
            'status': status,
            'entry': actual_entry,
            'target': actual_take_profit,
            'stop': actual_stop_loss,
            'exit_price': exit_price,
            'exit_date': exit_date,
            'days_held': len(future_data[future_data['date'] <= pd.to_datetime(exit_date)]) if exit_date else self.hold_days
        }

    def run_backtest(self, target_date: str, strategy: str = "baseline", top_n: int = 10, enabled_indicators: Optional[list[str]] = None, aggregation: str = "sum"):
        """Runs a backtest for a specific historical date and returns results."""
        indicator_str = f" | Indicators: {', '.join(enabled_indicators)}" if enabled_indicators else ""
        ReportSingleton().write(f"\n--- {strategy.title()} Backtest Report for {target_date} (Hold: {self.hold_days} days){indicator_str} | Agg: {aggregation} ---")
        
        symbols = get_symbol_name_list()
        max_workers = min(8, os.cpu_count() or 4)
        
        logging.info("Generating %s predictions for %s...", strategy, target_date)
        predictions = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            process_func = partial(self.trader.process_symbol, target_date=target_date, enabled_indicators=enabled_indicators, aggregation=aggregation)
            future_to_symbol = {executor.submit(process_func, sym): sym for sym in symbols}
            
            for future in concurrent.futures.as_completed(future_to_symbol):
                try:
                    result = future.result()
                    predictions.append(result)
                except Exception as e:
                    logging.error("Exception during prediction: %s", e)

        # Use strategy-specific score key
        score_key = "baseline_score" if strategy == "baseline" else "mr_score"
        
        # Filter out scores <= 0 to avoid noise
        valid_predictions = sorted(
            (p for p in predictions if p is not None and p.get(score_key, 0.0) > 0),
            key=lambda x: x.get(score_key, 0.0),
            reverse=True
        )

        if not valid_predictions:
            ReportSingleton().write("No valid signals found for this date.")
            return []

        top_predictions = valid_predictions[:top_n]
        results = []
        for pred in top_predictions:
            eval_result = self.evaluate_prediction(pred, target_date)
            results.append(eval_result)
            
            pnl = 0.0
            if 'entry' in eval_result and 'exit_price' in eval_result:
                pnl = ((eval_result['exit_price'] / eval_result['entry']) - 1) * 100
            
            score_val = pred.get(score_key, 0.0)
            msg = f"{pred['symbol']} (Score: {score_val:.2f}): {eval_result['status']}"
            if 'entry' in eval_result:
                msg += f" | PnL: {pnl:.2f}%"
            ReportSingleton().write(msg)

        valid_results = [r for r in results if 'entry' in r and 'exit_price' in r]
        if valid_results:
            avg_pnl = sum(((r['exit_price'] / r['entry']) - 1) * 100 for r in valid_results) / len(valid_results)
            success_count = sum(1 for r in valid_results if r['status'] in ['success', 'closed_profit'])
            win_rate = (success_count / len(valid_results)) * 100
            ReportSingleton().write(f"Summary: {success_count}/{len(valid_results)} profitable ({win_rate:.2f}%) | Avg PnL: {avg_pnl:.2f}%")
        
        return results

    def run_range_backtest(self, start_date: str, end_date: str, interval_days: int = 7, top_n: int = 10, strategy: str = "baseline", enabled_indicators: Optional[list[str]] = None, aggregation: str = "sum"):
        """Runs backtests over a range of dates at set intervals."""
        start_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date)
        
        current_ts = start_ts
        all_results = []
        
        indicator_str = f" | Indicators: {', '.join(enabled_indicators)}" if enabled_indicators else "ALL"
        ReportSingleton().write(f"\n==========================================")
        ReportSingleton().write(f"STRESS TEST: {start_date} to {end_date} | Strategy: {strategy}")
        ReportSingleton().write(f"Interval: {interval_days} days | Hold: {self.hold_days} days")
        ReportSingleton().write(f"Indicators: {indicator_str}")
        ReportSingleton().write(f"Aggregation: {aggregation}")
        ReportSingleton().write(f"Target: {self.target_profit_factor} | Stop: {self.stop_loss_factor}")
        ReportSingleton().write(f"==========================================\n")

        while current_ts <= end_ts:
            date_str = current_ts.strftime('%Y-%m-%d')
            day_results = self.run_backtest(date_str, strategy=strategy, top_n=top_n, enabled_indicators=enabled_indicators, aggregation=aggregation)
            all_results.extend(day_results)
            current_ts += pd.Timedelta(days=interval_days)

        # Aggregate Summary
        valid_all = [r for r in all_results if 'entry' in r and 'exit_price' in r]
        if not valid_all:
            ReportSingleton().write("\nNo valid trades in range.")
            return

        total_trades = len(valid_all)
        profitable_trades = sum(1 for r in valid_all if r['status'] in ['success', 'closed_profit'])
        total_pnl = sum(((r['exit_price'] / r['entry']) - 1) * 100 for r in valid_all)
        avg_pnl = total_pnl / total_trades
        win_rate = (profitable_trades / total_trades) * 100

        ReportSingleton().write(f"\n--- FINAL STRESS TEST SUMMARY ---")
        ReportSingleton().write(f"Total Trades Evaluated: {total_trades}")
        ReportSingleton().write(f"Overall Win Rate: {win_rate:.2f}%")
        ReportSingleton().write(f"Overall Average PnL: {avg_pnl:.2f}%")
        ReportSingleton().write(f"Total Cumulative PnL: {total_pnl:.2f}%")
        ReportSingleton().write(f"---------------------------------")

import os
