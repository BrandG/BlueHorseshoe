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

    def __init__(self, target_profit_factor: float = 1.01, stop_loss_factor: float = 0.98, hold_days: int = 3, use_trailing_stop: bool = False, trailing_multiplier: float = 2.0):
        self.trader = SwingTrader()
        self.target_profit_factor = target_profit_factor
        self.stop_loss_factor = stop_loss_factor
        self.hold_days = hold_days
        self.use_trailing_stop = use_trailing_stop
        self.trailing_multiplier = trailing_multiplier

    def evaluate_prediction(self, prediction: Dict, target_date: str) -> Dict:
        """
        Evaluates a single prediction against the price action of the following trading days.
        Uses structural entry, stop, and target from the prediction metadata.
        """
        symbol = prediction['symbol']
        target_entry = prediction['entry_price']
        target_stop = prediction['stop_loss']
        target_exit = prediction['take_profit']

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

        # 1. Entry check: Did we ever hit the entry price?
        # Simulation: If Open is below target_entry, we buy at Open.
        # If Open is above target_entry, but Low is below target_entry, we buy at target_entry.
        entry_found = False
        actual_entry = None
        entry_date = None
        remaining_data = None

        for i, day in future_data.iterrows():
            if day['open'] <= target_entry:
                actual_entry = day['open']
                entry_found = True
            elif day['low'] <= target_entry:
                actual_entry = target_entry
                entry_found = True

            if entry_found:
                entry_date = day['date']
                # Trade continues from this day onwards
                remaining_data = future_data.loc[i:]
                break

        if not entry_found:
            return {'symbol': symbol, 'status': 'no_entry'}

        status = 'hold'
        exit_date = None
        exit_price = None
        current_stop = target_stop

        for _, day in remaining_data.iterrows():
            high = day['high']
            low = day['low']
            open_price = day['open']

            # Update trailing stop if enabled
            if self.use_trailing_stop:
                atr = day.get('atr_14')
                if atr and not pd.isna(atr):
                    # Trail 2.0 * ATR from the high
                    new_stop = high - (self.trailing_multiplier * atr)
                    if new_stop > current_stop:
                        current_stop = new_stop

            # Check for Gap Up Success
            if open_price >= target_exit:
                status = 'success'
                exit_price = open_price # Sold at open for even more profit
                exit_date = day['date'].strftime('%Y-%m-%d')
                break

            # Check for Gap Down Failure
            if open_price <= current_stop:
                status = 'failure'
                exit_price = open_price # Sold at open for a larger loss
                exit_date = day['date'].strftime('%Y-%m-%d')
                break

            # Check for success during the day
            if high >= target_exit:
                status = 'success'
                exit_price = target_exit
                exit_date = day['date'].strftime('%Y-%m-%d')
                break

            # Check for failure during the day
            if low <= current_stop:
                status = 'failure'
                exit_price = current_stop
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
            'target': target_exit,
            'stop': target_stop,
            'final_stop': current_stop,
            'exit_price': exit_price,
            'exit_date': exit_date,
            'days_held': len(future_data[(future_data['date'] >= entry_date) & (future_data['date'] <= pd.to_datetime(exit_date))]) if exit_date else self.hold_days
        }

    def run_backtest(self, target_date: str, strategy: str = "baseline", top_n: int = 10, enabled_indicators: Optional[list[str]] = None, aggregation: str = "sum", symbols: Optional[List[str]] = None):
        """Runs a backtest for a specific historical date and returns results."""
        indicator_str = f" | Indicators: {', '.join(enabled_indicators)}" if enabled_indicators else ""
        ReportSingleton().write(f"\n--- {strategy.title()} Backtest Report for {target_date} (Hold: {self.hold_days} days){indicator_str} | Agg: {aggregation} ---")

        if not symbols:
            print("  > Loading symbols from database...", end="", flush=True)
            symbols = get_symbol_name_list()
            print(f" Done ({len(symbols)} symbols).", flush=True)

        max_workers = min(8, os.cpu_count() or 4)

        logging.info("Generating %s predictions for %s...", strategy, target_date)
        predictions = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            process_func = partial(self.trader.process_symbol, target_date=target_date, enabled_indicators=enabled_indicators, aggregation=aggregation)
            future_to_symbol = {executor.submit(process_func, sym): sym for sym in symbols}

            processed_count = 0
            total_symbols = len(symbols)
            for future in concurrent.futures.as_completed(future_to_symbol):
                processed_count += 1
                try:
                    result = future.result()
                    predictions.append(result)
                except Exception as e:
                    logging.error("Exception during prediction: %s", e)

                if processed_count % 500 == 0 or processed_count == total_symbols:
                    print(f"  > Progress: {processed_count}/{total_symbols} symbols analyzed ({ (processed_count/total_symbols)*100:.1f}%)", flush=True)

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
            # Flatten strategy-specific setup for evaluate_prediction
            setup_key = "baseline_setup" if strategy == "baseline" else "mr_setup"
            setup = pred.get(setup_key, {})
            pred['entry_price'] = setup.get('entry_price')
            pred['stop_loss'] = setup.get('stop_loss')
            pred['take_profit'] = setup.get('take_profit')

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

    def run_range_backtest(self, start_date: str, end_date: str, interval_days: int = 7, top_n: int = 10, strategy: str = "baseline", enabled_indicators: Optional[list[str]] = None, aggregation: str = "sum", symbols: Optional[List[str]] = None):
        """Runs backtests over a range of dates at set intervals."""
        start_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date)

        current_ts = start_ts
        all_results = []

        # Calculate total steps for progress tracking
        total_days = (end_ts - start_ts).days
        total_steps = (total_days // interval_days) + 1
        current_step = 1

        indicator_str = f" | Indicators: {', '.join(enabled_indicators)}" if enabled_indicators else "ALL"
        ReportSingleton().write(f"\n==========================================")
        ReportSingleton().write(f"STRESS TEST: {start_date} to {end_date} | Strategy: {strategy}")
        ReportSingleton().write(f"Interval: {interval_days} days | Hold: {self.hold_days} days")
        ReportSingleton().write(f"Indicators: {indicator_str}")
        ReportSingleton().write(f"Aggregation: {aggregation}")
        ReportSingleton().write(f"Target: {self.target_profit_factor} | Stop: {self.stop_loss_factor}")
        ReportSingleton().write(f"==========================================\n")

        if not symbols:
            print(f"  > Fetching symbols...", end="", flush=True)
            symbols = get_symbol_name_list()
            print(f" Done ({len(symbols)} symbols).", flush=True)

        while current_ts <= end_ts:
            date_str = current_ts.strftime('%Y-%m-%d')
            print(f"\n--- Processing Step {current_step}/{total_steps}: {date_str} ---", flush=True)
            day_results = self.run_backtest(date_str, strategy=strategy, top_n=top_n, enabled_indicators=enabled_indicators, aggregation=aggregation, symbols=symbols)
            all_results.extend(day_results)
            current_ts += pd.Timedelta(days=interval_days)
            current_step += 1

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
