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
from bluehorseshoe.analysis.strategy import SwingTrader, StrategyContext
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

@dataclass
class TradeState:
    """Mutable state for a single trade simulation."""
    # pylint: disable=too-many-instance-attributes
    entry_price: float
    take_profit: float
    current_stop: float
    status: str = 'no_entry'
    actual_entry: Optional[float] = None
    exit_price: Optional[float] = None
    exit_date: Optional[pd.Timestamp] = None
    entry_idx: int = -1

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

    def _check_entry(self, row, i, state):
        """Check if entry conditions are met."""
        if row['low'] <= state.entry_price:
            state.status = 'active'
            state.entry_idx = i

            # Slippage/Gap Logic
            if row['open'] < state.entry_price:
                state.actual_entry = row['open']
            else:
                state.actual_entry = state.entry_price

            # Immediate Stop/Target Check (Intraday)
            if row['low'] <= state.current_stop:
                state.status = 'stopped_out'
                state.exit_price = state.current_stop
                if row['open'] < state.current_stop:
                    state.exit_price = row['open']
                state.exit_date = row['date']
                return

            if row['high'] >= state.take_profit:
                state.status = 'success'
                state.exit_price = state.take_profit
                if row['open'] > state.take_profit:
                    state.exit_price = row['open']
                state.exit_date = row['date']
                return

        elif i >= self.hold_days:
            state.status = 'limit_expired'

    def _check_active_trade(self, row, current_idx, state, future_data):
        """Check for exit conditions in an active trade."""
        # Stop Loss
        if row['low'] <= state.current_stop:
            state.status = 'stopped_out'
            state.exit_price = state.current_stop
            if row['open'] < state.current_stop:
                state.exit_price = row['open']
            state.exit_date = row['date']
            return

        # Take Profit
        if row['high'] >= state.take_profit:
            state.status = 'success'
            state.exit_price = state.take_profit
            if row['open'] > state.take_profit:
                state.exit_price = row['open']
            state.exit_date = row['date']
            return

        # Time Exit
        days_in_trade = current_idx - state.entry_idx
        if days_in_trade >= self.hold_days:
            state.status = 'time_exit'
            state.exit_price = row['close']
            state.exit_date = row['date']
            if state.exit_price > state.actual_entry:
                state.status = 'closed_profit'
            else:
                state.status = 'closed_loss'

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

        state = TradeState(
            entry_price=entry_price,
            take_profit=take_profit,
            current_stop=stop_loss
        )

        for i, row in future_data.iterrows():
            # If we haven't entered yet
            if state.status == 'no_entry':
                self._check_entry(row, i, state)
            # If we are in a trade
            elif state.status == 'active':
                self._check_active_trade(row, i, state, future_data)

            if state.status in ['stopped_out', 'success', 'limit_expired', 'time_exit', 'closed_profit', 'closed_loss']:
                break

        return {
            'symbol': symbol,
            'status': state.status,
            'entry': state.actual_entry,
            'exit_price': state.exit_price,
            'exit_date': state.exit_date,
            'days_held': (i - state.entry_idx) if state.entry_idx != -1 else 0
        }

    def _print_backtest_header(self, target_date: str, options: BacktestOptions) -> None:
        indicator_str = f" | Indicators: {', '.join(options.enabled_indicators)}" if options.enabled_indicators else ""
        header = (
            f"\n--- {options.strategy.title()} Backtest Report for {target_date} "
            f"(Hold: {self.hold_days} days){indicator_str} | Agg: {options.aggregation} ---"
        )
        ReportSingleton().write(header)

    def _load_symbols(self) -> List[str]:
        print("  > Loading symbols from database...", end="", flush=True)
        symbols = get_symbol_name_list()
        print(f" Done ({len(symbols)} symbols).", flush=True)
        return symbols

    def _generate_predictions(self, symbols: List[str], target_date: str, options: BacktestOptions) -> List[Dict]:
        max_workers = min(8, os.cpu_count() or 4)
        logging.info("Generating %s predictions for %s...", options.strategy, target_date)
        predictions = []

        ctx = StrategyContext(
            target_date=target_date,
            enabled_indicators=options.enabled_indicators,
            aggregation=options.aggregation
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            process_func = partial(self.trader.process_symbol, ctx=ctx)
            future_to_symbol = {executor.submit(process_func, sym): sym for sym in symbols}

            processed_count = 0
            total_symbols = len(symbols)
            for future in concurrent.futures.as_completed(future_to_symbol):
                processed_count += 1
                try:
                    result = future.result()
                    predictions.append(result)
                except Exception as e: # pylint: disable=broad-exception-caught
                    logging.error("Exception during prediction: %s", e)

                if processed_count % 500 == 0 or processed_count == total_symbols:
                    print(
                        f"  > Progress: {processed_count}/{total_symbols} symbols analyzed "
                        f"({(processed_count / total_symbols) * 100:.1f}%)",
                        flush=True
                    )
        return predictions

    def _filter_and_sort_predictions(self, predictions: List[Dict], options: BacktestOptions) -> List[Dict]:
        score_key = "baseline_score" if options.strategy == "baseline" else "mr_score"
        valid_predictions = sorted(
            (p for p in predictions if p is not None and p.get(score_key, 0.0) > 0),
            key=lambda x: x.get(score_key, 0.0),
            reverse=True
        )
        return valid_predictions[:options.top_n]

    def _evaluate_candidates(self, top_predictions: List[Dict], target_date: str, options: BacktestOptions) -> List[Dict]:
        results = []
        score_key = "baseline_score" if options.strategy == "baseline" else "mr_score"
        setup_key = "baseline_setup" if options.strategy == "baseline" else "mr_setup"

        for pred in top_predictions:
            # Flatten strategy-specific setup for evaluate_prediction
            setup = pred.get(setup_key, {})
            pred['entry_price'] = setup.get('entry_price')
            pred['stop_loss'] = setup.get('stop_loss')
            pred['take_profit'] = setup.get('take_profit')

            eval_result = self.evaluate_prediction(pred, target_date)
            results.append(eval_result)

            score_key = "baseline_score" if options.strategy == "baseline" else "mr_score"
            setup_key = "baseline_setup" if options.strategy == "baseline" else "mr_setup"
            ml_prob_key = "baseline_ml_prob" if options.strategy == "baseline" else "mr_ml_prob"
            
            score_val = pred.get(score_key, 0.0)
            ml_prob = pred.get(ml_prob_key, 0.0)

            msg = f"{pred['symbol']} (Score: {score_val:.2f} | ML: {ml_prob*100:.1f}%): {eval_result['status']}"
            if eval_result.get('entry') is not None and eval_result.get('exit_price') is not None:
                pnl = ((eval_result['exit_price'] / eval_result['entry']) - 1) * 100
                msg += f" | PnL: {pnl:.2f}% (Entry: {eval_result['entry']:.2f}, Exit: {eval_result['exit_price']:.2f}, Held: {eval_result['days_held']} days)"
            ReportSingleton().write(msg)
        return results

    def _print_summary(self, results: List[Dict]) -> None:
        valid_results = [r for r in results if r.get('entry') is not None and r.get('exit_price') is not None]
        if valid_results:
            avg_pnl = sum(((r['exit_price'] / r['entry']) - 1) * 100 for r in valid_results) / len(valid_results)
            success_count = sum(1 for r in valid_results if r['status'] in ['success', 'closed_profit'])
            win_rate = (success_count / len(valid_results)) * 100
            ReportSingleton().write(f"Summary: {success_count}/{len(valid_results)} profitable ({win_rate:.2f}%) | Avg PnL: {avg_pnl:.2f}%")

    def run_backtest(self, target_date: str, options: BacktestOptions = None):
        """Runs a backtest for a specific historical date and returns results."""
        if options is None:
            options = BacktestOptions()

        self._print_backtest_header(target_date, options)

        symbols = options.symbols
        if not symbols:
            symbols = self._load_symbols()

        predictions = self._generate_predictions(symbols, target_date, options)

        top_predictions = self._filter_and_sort_predictions(predictions, options)

        if not top_predictions:
            ReportSingleton().write("No valid signals found for this date.")
            return []

        results = self._evaluate_candidates(top_predictions, target_date, options)

        self._print_summary(results)

        return results

    def _summarize_range_results(self, all_results):
        """Summarize aggregated backtest results."""
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

    def run_range_backtest(self, start_date: str, end_date: str, interval_days: int = 7, options: BacktestOptions = None):
        """Runs backtests over a range of dates at set intervals."""
        if options is None:
            options = BacktestOptions()

        current_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date)
        all_results = []

        # Calculate total steps for progress tracking
        total_days = (end_ts - current_ts).days
        total_steps = (total_days // interval_days) + 1
        current_step = 1

        indicator_str = f" | Indicators: {', '.join(options.enabled_indicators)}" if options.enabled_indicators else "ALL"
        ReportSingleton().write("\n==========================================")
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
        self._summarize_range_results(all_results)
