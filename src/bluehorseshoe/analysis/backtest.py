"""
backtest.py

This module provides functionality for backtesting the swing trading strategy.
It allows for historical performance evaluation by simulating trades based on
past data and verifying results against subsequent price action.
"""

import logging
import os
import concurrent.futures
from functools import partial
from dataclasses import dataclass
from typing import Optional, List, Dict
import pandas as pd
from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.core.symbols import get_symbol_name_list
from bluehorseshoe.data.historical_data import load_historical_data
from bluehorseshoe.reporting.report_generator import ReportSingleton


@dataclass
class BacktestConfig:
    """Configuration for backtest parameters."""
    target_profit_factor: float = 1.01
    stop_loss_factor: float = 0.98
    hold_days: int = 3
    use_trailing_stop: bool = False
    trailing_multiplier: float = 2.0

@dataclass
class BacktestOptions:
    """Runtime options for running a backtest."""
    strategy: str = "baseline"
    top_n: int = 10
    enabled_indicators: Optional[List[str]] = None
    aggregation: str = "sum"
    symbols: Optional[List[str]] = None

class Backtester:
    """Class for orchestrating historical backtests of the trading strategy."""

    def __init__(self, config: BacktestConfig = None):
        if config is None:
            config = BacktestConfig()
        self.trader = SwingTrader()
        self.config = config
        # Expose config attributes
        self.hold_days = config.hold_days
        self.use_trailing_stop = config.use_trailing_stop
        self.trailing_multiplier = config.trailing_multiplier
        self.target_profit_factor = config.target_profit_factor
        self.stop_loss_factor = config.stop_loss_factor

    def evaluate_prediction(self, prediction: Dict, target_date: str) -> Dict:
        """
        Simulates a trade based on the prediction using future data.

        Args:
            prediction: The prediction dictionary containing entry/exit parameters.
            target_date: The date the prediction was made (trade starts the next day).

        Returns:
            A dictionary containing the trade outcome (status, PnL, exit details).
        """
        symbol = prediction['symbol']
        entry_price = prediction.get('entry_price')
        stop_loss = prediction.get('stop_loss')
        take_profit = prediction.get('take_profit')

        # Determine strictness of entry (optional, can be passed in config)
        # strict_entry = True # If True, Low must be <= Entry. If False, buy at Open.

        price_data = load_historical_data(symbol)
        if not price_data or 'days' not in price_data:
            return {'symbol': symbol, 'status': 'data_error'}

        df = pd.DataFrame(price_data['days'])
        if df.empty:
            return {'symbol': symbol, 'status': 'data_error'}

        df['date'] = pd.to_datetime(df['date'])

        # Filter for data AFTER the target date
        # target_date is the analysis date. We can enter on target_date (if intraday) or next day.
        # Typically "predictions for target_date" means analysis done on target_date close.
        # So we look at data > target_date.
        start_date = pd.to_datetime(target_date)
        future_data = df[df['date'] > start_date].sort_values('date').reset_index(drop=True)

        if future_data.empty:
            return {'symbol': symbol, 'status': 'no_future_data'}

        status = 'no_entry'
        actual_entry = None
        exit_price = None
        exit_date = None

        # Tracking variables
        target_stop = stop_loss
        target_exit = take_profit
        current_stop = stop_loss

        # 1. Check for Entry
        # We look for entry within the first few days? Or just the immediate next day?
        # A limit order might be valid for X days. Let's assume 1-3 days validity or just 1 day.
        # For this system, let's assume valid for `hold_days` or until filled.

        entry_idx = -1

        for i, row in future_data.iterrows():
            # If we haven't entered yet
            if status == 'no_entry':
                # Check if price hit entry level
                # Assuming Limit Buy at entry_price
                if row['low'] <= entry_price:
                    # Filled
                    status = 'active'
                    actual_entry = entry_price
                    # If Open was lower than limit, we might have got better price,
                    # but let's be conservative and say we got filled at limit.
                    # Unless Open < Entry, then maybe we got Open?
                    # Let's stick to entry_price for consistency.
                    if row['open'] < entry_price:
                        actual_entry = row['open'] # Gap down fill
                    else:
                        actual_entry = entry_price

                    entry_date = row['date']
                    entry_idx = i

                    # Check if we also stopped out or hit profit on the SAME day?
                    # If Low <= Stop, we stopped out.
                    # If High >= Target, we profited.
                    # Sequence matters: Open -> Low/High -> Close.
                    # Approximation: If Low <= Stop, assume stopped out first?
                    # Or look at candle body? Impossible to know intraday path without tick data.
                    # Conservative: If Low <= Stop, we stopped out.

                    if row['low'] <= current_stop:
                        status = 'stopped_out'
                        exit_price = current_stop
                        if row['open'] < current_stop:
                            exit_price = row['open'] # Gap down stop
                        exit_date = row['date']
                        break

                    elif row['high'] >= target_exit:
                        status = 'success'
                        exit_price = target_exit
                        if row['open'] > target_exit:
                            exit_price = row['open'] # Gap up profit
                        exit_date = row['date']
                        break

                # Expiry of limit order?
                if i >= self.hold_days: # If not filled by hold_days, cancel
                    status = 'limit_expired'
                    break

            # If we are in a trade
            elif status == 'active':
                # Check Stop
                if row['low'] <= current_stop:
                    status = 'stopped_out'
                    exit_price = current_stop
                    if row['open'] < current_stop:
                        exit_price = row['open']
                    exit_date = row['date']
                    break

                # Check Target
                elif row['high'] >= target_exit:
                    status = 'success'
                    exit_price = target_exit
                    if row['open'] > target_exit:
                        exit_price = row['open']
                    exit_date = row['date']
                    break

                # Trailing Stop Update
                if self.use_trailing_stop:
                    # If price moves up, move stop up
                    # Simple trailing: defined by ATR or percentage?
                    # Backtester config has trailing_multiplier.
                    # Let's assume trailing based on High - (Multiplier * ATR)?
                    # Or just: new_stop = max(current_stop, row['close'] * (1 - 0.02))?
                    # Let's use the config provided trailing logic if feasible, or simple % trail.
                    # Given `ml_stop_multiplier` is in prediction, maybe use that?
                    pass

                # Time Exit
                days_in_trade = (row['date'] - future_data.iloc[entry_idx]['date']).days
                if days_in_trade >= self.hold_days:
                    status = 'time_exit'
                    exit_price = row['close']
                    exit_date = row['date']
                    # Check if time exit is profitable
                    if exit_price > actual_entry:
                        status = 'closed_profit'
                    else:
                        status = 'closed_loss'
                    break

        return {
            'symbol': symbol,
            'status': status,
            'entry': actual_entry,
            'target': target_exit,
            'stop': target_stop,
            'final_stop': current_stop,
            'exit_price': exit_price,
            'exit_date': exit_date,
            'days_held': (exit_date - future_data.iloc[entry_idx]['date']).days if exit_date and entry_idx != -1 else 0
        }

    def run_backtest(self, target_date: str, options: BacktestOptions = None):
        """Runs a backtest for a specific historical date and returns results."""
        if options is None:
            options = BacktestOptions()

        indicator_str = f" | Indicators: {', '.join(options.enabled_indicators)}" if options.enabled_indicators else ""
        ReportSingleton().write(f"\n--- {options.strategy.title()} Backtest Report for {target_date} (Hold: {self.hold_days} days){indicator_str} | Agg: {options.aggregation} ---")

        symbols = options.symbols
        if not symbols:
            print("  > Loading symbols from database...", end="", flush=True)
            symbols = get_symbol_name_list()
            print(f" Done ({len(symbols)} symbols).", flush=True)

        max_workers = min(8, os.cpu_count() or 4)

        logging.info("Generating %s predictions for %s...", options.strategy, target_date)
        predictions = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            process_func = partial(self.trader.process_symbol, target_date=target_date, enabled_indicators=options.enabled_indicators, aggregation=options.aggregation)
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
        score_key = "baseline_score" if options.strategy == "baseline" else "mr_score"

        # Filter out scores <= 0 to avoid noise
        valid_predictions = sorted(
            (p for p in predictions if p is not None and p.get(score_key, 0.0) > 0),
            key=lambda x: x.get(score_key, 0.0),
            reverse=True
        )

        if not valid_predictions:
            ReportSingleton().write("No valid signals found for this date.")
            return []

        top_predictions = valid_predictions[:options.top_n]
        results = []
        for pred in top_predictions:
            # Flatten strategy-specific setup for evaluate_prediction
            setup_key = "baseline_setup" if options.strategy == "baseline" else "mr_setup"
            setup = pred.get(setup_key, {})
            pred['entry_price'] = setup.get('entry_price')
            pred['stop_loss'] = setup.get('stop_loss')
            pred['take_profit'] = setup.get('take_profit')

            eval_result = self.evaluate_prediction(pred, target_date)
            results.append(eval_result)

            pnl = 0.0
            if eval_result.get('entry') is not None and eval_result.get('exit_price') is not None:
                pnl = ((eval_result['exit_price'] / eval_result['entry']) - 1) * 100

            score_val = pred.get(score_key, 0.0)
            msg = f"{pred['symbol']} (Score: {score_val:.2f}): {eval_result['status']}"
            if eval_result.get('entry') is not None:
                msg += f" | PnL: {pnl:.2f}%"
            ReportSingleton().write(msg)

        valid_results = [r for r in results if r.get('entry') is not None and r.get('exit_price') is not None]
        if valid_results:
            avg_pnl = sum(((r['exit_price'] / r['entry']) - 1) * 100 for r in valid_results) / len(valid_results)
            success_count = sum(1 for r in valid_results if r['status'] in ['success', 'closed_profit'])
            win_rate = (success_count / len(valid_results)) * 100
            ReportSingleton().write(f"Summary: {success_count}/{len(valid_results)} profitable ({win_rate:.2f}%) | Avg PnL: {avg_pnl:.2f}%")

        return results

    def run_range_backtest(self, start_date: str, end_date: str, interval_days: int = 7, options: BacktestOptions = None):
        """Runs backtests over a range of dates at set intervals."""
        if options is None:
            options = BacktestOptions()

        start_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date)

        current_ts = start_ts
        all_results = []

        # Calculate total steps for progress tracking
        total_days = (end_ts - start_ts).days
        total_steps = (total_days // interval_days) + 1
        current_step = 1

        indicator_str = f" | Indicators: {', '.join(options.enabled_indicators)}" if options.enabled_indicators else "ALL"
        ReportSingleton().write("\n==========================================")
        ReportSingleton().write(f"Interval: {interval_days} days | Hold: {self.hold_days} days")
        ReportSingleton().write(f"Interval: {interval_days} days | Hold: {self.hold_days} days")
        ReportSingleton().write(f"Indicators: {indicator_str}")
        ReportSingleton().write(f"Aggregation: {options.aggregation}")
        ReportSingleton().write(f"Target: {self.target_profit_factor} | Stop: {self.stop_loss_factor}")
        ReportSingleton().write("\n==========================================")

        symbols = options.symbols
        if not symbols:
            print(f"  > Fetching symbols...", end="", flush=True)
            symbols = get_symbol_name_list()
            print(f" Done ({len(symbols)} symbols).", flush=True)
            # Update options with loaded symbols to pass down
            options.symbols = symbols

        while current_ts <= end_ts:
            date_str = current_ts.strftime('%Y-%m-%d')
            print(f"\n--- Processing Step {current_step}/{total_steps}: {date_str} ---", flush=True)
            day_results = self.run_backtest(date_str, options=options)
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

        ReportSingleton().write("\n--- FINAL STRESS TEST SUMMARY ---")
        ReportSingleton().write(f"Total Trades Evaluated: {total_trades}")
        ReportSingleton().write(f"Overall Win Rate: {win_rate:.2f}%")
        ReportSingleton().write(f"Overall Average PnL: {avg_pnl:.2f}%")
        ReportSingleton().write(f"Total Cumulative PnL: {total_pnl:.2f}%")
        ReportSingleton().write("---------------------------------")
