"""
backtest.py

This module provides functionality for backtesting the swing trading strategy.
It allows for historical performance evaluation by simulating trades based on
past data and verifying results against subsequent price action.
"""

import logging
import os
import csv
from pathlib import Path
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
    max_workers: Optional[int] = None  # Thread pool size for predictions; None = auto

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

@dataclass
class SplitExitConfig:
    """Configuration for split-exit (two-tranche) mode."""
    mode: str = 'fixed_pct'       # 'fixed_pct' (Plan A) or 'atr_tiered' (Plan B)
    t1_profit_pct: float = 0.02   # Plan A: 2% first tranche target
    t1_atr_multiple: float = 1.0  # Plan B: 1x ATR first tranche
    t2_atr_multiple: float = 2.0  # Plan B: 2x ATR second tranche
    tranche_weight: float = 0.5   # 50/50 split


@dataclass
class SplitTradeState:
    """Mutable state for a two-tranche trade simulation."""
    # pylint: disable=too-many-instance-attributes
    # Shared
    entry_price: float
    original_stop: float
    actual_entry: Optional[float] = None
    entry_idx: int = -1
    phase: str = 'pre_entry'  # 'pre_entry', 'both_active', 't1_exited', 'complete'
    # Tranche 1
    t1_target: float = 0.0
    t1_status: str = 'pending'  # 'pending', 'profit', 'stopped', 'time_exit'
    t1_exit_price: Optional[float] = None
    t1_exit_date: Optional[pd.Timestamp] = None
    # Tranche 2
    t2_target: float = 0.0
    t2_stop: float = 0.0       # starts at original_stop, moves to t1 level after T1 exit
    t2_status: str = 'pending'  # 'pending', 'profit', 'stopped', 'time_exit'
    t2_exit_price: Optional[float] = None
    t2_exit_date: Optional[pd.Timestamp] = None


class Backtester:
    """Class for orchestrating historical backtests of the trading strategy."""

    def __init__(self, config: BacktestConfig = None, database=None):
        """
        Initialize Backtester with optional dependency injection.

        Args:
            config: BacktestConfig instance
            database: MongoDB database instance. If None, uses global singleton.
        """
        if config is None:
            config = BacktestConfig()
        self.database = database
        self.trader = SwingTrader(database=database)
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

    def evaluate_prediction(self, prediction: Dict, target_date: str,
                            price_df: Optional[pd.DataFrame] = None) -> Dict:
        """
        Simulates a trade based on the prediction using future data.

        Args:
            prediction: The prediction dictionary containing entry/exit parameters.
            target_date: The date the prediction was made (trade starts the next day).
            price_df: Optional pre-loaded DataFrame with 'date' already parsed.
                      If provided, skips MongoDB load.

        Returns:
            A dictionary containing the trade outcome (status, PnL, exit details).
        """
        symbol = prediction['symbol']
        entry_price = prediction.get('entry_price')
        stop_loss = prediction.get('stop_loss')
        take_profit = prediction.get('take_profit')

        if price_df is not None:
            df = price_df
        else:
            price_data = load_historical_data(symbol, database=self.database)
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

        # Mark-to-market if trade is still active but ran out of data
        if state.status == 'active' and state.actual_entry is not None:
            state.exit_price = row['close']
            state.exit_date = row['date']
            if state.exit_price > state.actual_entry:
                state.status = 'closed_profit'
            else:
                state.status = 'closed_loss'

        return {
            'symbol': symbol,
            'status': state.status,
            'entry': state.actual_entry,
            'exit_price': state.exit_price,
            'exit_date': state.exit_date,
            'days_held': (i - state.entry_idx) if state.entry_idx != -1 else 0
        }

    def _check_split_entry(self, row, i, state):
        """Check entry for split-exit trade. Handles slippage and intraday stop/T1/T2."""
        if row['low'] <= state.entry_price:
            state.phase = 'both_active'
            state.entry_idx = i

            # Slippage/Gap Logic
            if row['open'] < state.entry_price:
                state.actual_entry = row['open']
            else:
                state.actual_entry = state.entry_price

            # Immediate intraday stop check (both tranches)
            if row['low'] <= state.original_stop:
                stop_px = state.original_stop
                if row['open'] < state.original_stop:
                    stop_px = row['open']
                state.t1_status = 'stopped'
                state.t1_exit_price = stop_px
                state.t1_exit_date = row['date']
                state.t2_status = 'stopped'
                state.t2_exit_price = stop_px
                state.t2_exit_date = row['date']
                state.phase = 'complete'
                return

            # Intraday T1 target check
            if row['high'] >= state.t1_target:
                t1_px = state.t1_target
                if row['open'] > state.t1_target:
                    t1_px = row['open']
                state.t1_status = 'profit'
                state.t1_exit_price = t1_px
                state.t1_exit_date = row['date']
                state.phase = 't1_exited'
                # Move T2 stop to T1 level (breakeven+)
                state.t2_stop = state.t1_target

                # Check T2 on same bar
                if row['high'] >= state.t2_target:
                    t2_px = state.t2_target
                    if row['open'] > state.t2_target:
                        t2_px = row['open']
                    state.t2_status = 'profit'
                    state.t2_exit_price = t2_px
                    state.t2_exit_date = row['date']
                    state.phase = 'complete'
                return

        elif i >= self.hold_days:
            # Never entered within hold window
            state.phase = 'complete'
            state.t1_status = 'no_entry'
            state.t2_status = 'no_entry'

    def _check_split_active(self, row, current_idx, state):
        """State machine for active split-exit trade."""
        days_in_trade = current_idx - state.entry_idx

        if state.phase == 'both_active':
            # Stop check (exits both tranches)
            if row['low'] <= state.original_stop:
                stop_px = state.original_stop
                if row['open'] < state.original_stop:
                    stop_px = row['open']
                state.t1_status = 'stopped'
                state.t1_exit_price = stop_px
                state.t1_exit_date = row['date']
                state.t2_status = 'stopped'
                state.t2_exit_price = stop_px
                state.t2_exit_date = row['date']
                state.phase = 'complete'
                return

            # T1 target check
            if row['high'] >= state.t1_target:
                t1_px = state.t1_target
                if row['open'] > state.t1_target:
                    t1_px = row['open']
                state.t1_status = 'profit'
                state.t1_exit_price = t1_px
                state.t1_exit_date = row['date']
                state.phase = 't1_exited'
                state.t2_stop = state.t1_target  # Move T2 stop to T1 level

                # Check T2 on same bar
                if row['high'] >= state.t2_target:
                    t2_px = state.t2_target
                    if row['open'] > state.t2_target:
                        t2_px = row['open']
                    state.t2_status = 'profit'
                    state.t2_exit_price = t2_px
                    state.t2_exit_date = row['date']
                    state.phase = 'complete'
                return

            # Time exit (both)
            if days_in_trade >= self.hold_days:
                state.t1_status = 'time_exit'
                state.t1_exit_price = row['close']
                state.t1_exit_date = row['date']
                state.t2_status = 'time_exit'
                state.t2_exit_price = row['close']
                state.t2_exit_date = row['date']
                state.phase = 'complete'
                return

        elif state.phase == 't1_exited':
            # T2 stop check (at T1 level)
            if row['low'] <= state.t2_stop:
                stop_px = state.t2_stop
                if row['open'] < state.t2_stop:
                    stop_px = row['open']
                state.t2_status = 'stopped'
                state.t2_exit_price = stop_px
                state.t2_exit_date = row['date']
                state.phase = 'complete'
                return

            # T2 target check
            if row['high'] >= state.t2_target:
                t2_px = state.t2_target
                if row['open'] > state.t2_target:
                    t2_px = row['open']
                state.t2_status = 'profit'
                state.t2_exit_price = t2_px
                state.t2_exit_date = row['date']
                state.phase = 'complete'
                return

            # Time exit (T2 only)
            if days_in_trade >= self.hold_days:
                state.t2_status = 'time_exit'
                state.t2_exit_price = row['close']
                state.t2_exit_date = row['date']
                state.phase = 'complete'
                return

    def _build_split_result(self, symbol, state, split_config, last_row):
        """Compute blended P&L and build result dict for split-exit trade."""
        entry = state.actual_entry

        # Handle no-entry case
        if entry is None or state.t1_status == 'no_entry':
            return {
                'symbol': symbol,
                'status': 'no_entry',
                'entry': None,
                'exit_price': None,
                'exit_date': None,
                'days_held': 0,
                'exit_mode': 'split_exit',
            }

        # Handle incomplete trade (ran out of data before hold period ended)
        if last_row is not None:
            if state.t1_exit_price is None:
                state.t1_exit_price = last_row['close']
                state.t1_exit_date = last_row['date']
                state.t1_status = 'time_exit'
            if state.t2_exit_price is None:
                state.t2_exit_price = last_row['close']
                state.t2_exit_date = last_row['date']
                state.t2_status = 'time_exit'

        w = split_config.tranche_weight
        t1_pnl = ((state.t1_exit_price / entry) - 1) * 100
        t2_pnl = ((state.t2_exit_price / entry) - 1) * 100
        blended_pnl = w * t1_pnl + (1 - w) * t2_pnl

        # Determine overall status
        if state.t1_status == 'profit' and state.t2_status == 'profit':
            status = 'split_full_profit'
        elif state.t1_status == 'profit' and state.t2_status in ('stopped', 'time_exit'):
            status = 'split_partial_profit'
        elif state.t1_status == 'stopped' and state.t2_status == 'stopped':
            status = 'stopped_out'
        elif blended_pnl > 0:
            status = 'closed_profit'
        else:
            status = 'closed_loss'

        # Synthetic exit_price so ((exit_price / entry) - 1) * 100 == blended_pnl
        synthetic_exit = entry * (1 + blended_pnl / 100)

        # Exit date = last tranche to exit
        exit_date = state.t2_exit_date or state.t1_exit_date

        # Days held = from entry to last exit
        days_held = 0
        if exit_date is not None and state.entry_idx >= 0:
            # We use the stored exit date for reporting
            pass

        return {
            'symbol': symbol,
            'status': status,
            'entry': entry,
            'exit_price': synthetic_exit,
            'exit_date': exit_date,
            'days_held': 0,  # Will be filled below
            'blended_pnl_pct': blended_pnl,
            'tranche1_exit_price': state.t1_exit_price,
            'tranche1_status': state.t1_status,
            'tranche1_pnl_pct': t1_pnl,
            'tranche2_exit_price': state.t2_exit_price,
            'tranche2_status': state.t2_status,
            'tranche2_pnl_pct': t2_pnl,
            'exit_mode': 'split_exit',
        }

    def evaluate_prediction_split(self, prediction: Dict, target_date: str,
                                   split_config: SplitExitConfig,
                                   price_df: Optional[pd.DataFrame] = None) -> Dict:
        """
        Simulates a split-exit (two-tranche) trade.

        Args:
            prediction: Dict with 'symbol', 'entry_price', 'stop_loss', 'take_profit'.
                        Optionally 'atr' for Plan B.
            target_date: Date the prediction was made.
            split_config: SplitExitConfig controlling tranche targets.
            price_df: Optional pre-loaded DataFrame with 'date' already parsed.
                      If provided, skips MongoDB load.

        Returns:
            Result dict with blended P&L, per-tranche details, and synthetic exit_price.
        """
        symbol = prediction['symbol']
        entry_price = prediction.get('entry_price')
        stop_loss = prediction.get('stop_loss')
        take_profit = prediction.get('take_profit')

        if price_df is not None:
            df = price_df
        else:
            price_data = load_historical_data(symbol, database=self.database)
            if not price_data or 'days' not in price_data:
                return {'symbol': symbol, 'status': 'data_error', 'exit_mode': 'split_exit'}

            df = pd.DataFrame(price_data['days'])
            if df.empty:
                return {'symbol': symbol, 'status': 'data_error', 'exit_mode': 'split_exit'}

            df['date'] = pd.to_datetime(df['date'])

        start_date = pd.to_datetime(target_date)
        future_data = df[df['date'] > start_date].sort_values('date').reset_index(drop=True)

        if future_data.empty:
            return {'symbol': symbol, 'status': 'no_future_data', 'exit_mode': 'split_exit'}

        # Compute T1/T2 targets
        if split_config.mode == 'atr_tiered':
            atr = prediction.get('atr')
            if atr is None or atr <= 0:
                # Compute ATR from pre-trade data
                pre_data = df[df['date'] <= start_date].tail(14)
                if len(pre_data) >= 2:
                    tr = (pre_data['high'] - pre_data['low']).abs()
                    atr = tr.mean()
                else:
                    atr = abs(entry_price - stop_loss) / 2  # fallback
            t1_target = entry_price + (split_config.t1_atr_multiple * atr)
            t2_target = entry_price + (split_config.t2_atr_multiple * atr)
        else:
            # fixed_pct (Plan A)
            t1_target = entry_price * (1 + split_config.t1_profit_pct)
            t2_target = take_profit  # Original take profit

        state = SplitTradeState(
            entry_price=entry_price,
            original_stop=stop_loss,
            t1_target=t1_target,
            t2_target=t2_target,
            t2_stop=stop_loss,
        )

        last_row = None
        for i, row in future_data.iterrows():
            last_row = row
            if state.phase == 'pre_entry':
                self._check_split_entry(row, i, state)
            elif state.phase in ('both_active', 't1_exited'):
                self._check_split_active(row, i, state)

            if state.phase == 'complete':
                break

        result = self._build_split_result(symbol, state, split_config, last_row)

        # Fill days_held from index
        if state.entry_idx >= 0 and state.phase == 'complete':
            result['days_held'] = i - state.entry_idx

        return result

    def _print_backtest_header(self, target_date: str, options: BacktestOptions) -> None:
        indicator_str = f" | Indicators: {', '.join(options.enabled_indicators)}" if options.enabled_indicators else ""
        header = (
            f"\n--- {options.strategy.title()} Backtest Report for {target_date} "
            f"(Hold: {self.hold_days} days){indicator_str} | Agg: {options.aggregation} ---"
        )
        ReportSingleton().write(header)

    def _load_symbols(self) -> List[str]:
        print("  > Loading symbols from database...", end="", flush=True)
        symbols = get_symbol_name_list(database=self.database, active_only=True)
        print(f" Done ({len(symbols)} symbols).", flush=True)
        return symbols

    def _generate_predictions(self, symbols: List[str], target_date: str, options: BacktestOptions) -> List[Dict]:
        import gc
        max_workers = options.max_workers or min(8, os.cpu_count() or 4)
        chunk_size = 500
        logging.info("Generating %s predictions for %s...", options.strategy, target_date)
        predictions = []

        ctx = StrategyContext(
            target_date=target_date,
            enabled_indicators=options.enabled_indicators,
            aggregation=options.aggregation
        )

        total_symbols = len(symbols)
        processed_count = 0

        for chunk_start in range(0, total_symbols, chunk_size):
            chunk = symbols[chunk_start:chunk_start + chunk_size]

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                process_func = partial(self.trader.process_symbol, ctx=ctx)
                future_to_symbol = {executor.submit(process_func, sym): sym for sym in chunk}

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

            gc.collect()

        return predictions

    def _filter_and_sort_predictions(self, predictions: List[Dict], options: BacktestOptions) -> List[Dict]:
        score_key = "baseline_score" if options.strategy == "baseline" else "mr_score"
        valid_predictions = sorted(
            (p for p in predictions if p is not None and p.get(score_key, 0.0) > 0),
            key=lambda x: x.get(score_key, 0.0),
            reverse=True
        )
        return valid_predictions[:options.top_n]

    def _evaluate_candidates(self, top_predictions: List[Dict], target_date: str,
                             options: BacktestOptions, split_config: 'Optional[SplitExitConfig]' = None) -> List[Dict]:
        results = []
        score_key = "baseline_score" if options.strategy == "baseline" else "mr_score"
        setup_key = "baseline_setup" if options.strategy == "baseline" else "mr_setup"
        ml_prob_key = "baseline_ml_prob" if options.strategy == "baseline" else "mr_ml_prob"

        for pred in top_predictions:
            # Flatten strategy-specific setup for evaluate_prediction
            setup = pred.get(setup_key, {})
            pred['entry_price'] = setup.get('entry_price')
            pred['stop_loss'] = setup.get('stop_loss')
            pred['take_profit'] = setup.get('take_profit')

            if split_config is not None:
                eval_result = self.evaluate_prediction_split(pred, target_date, split_config)
            else:
                eval_result = self.evaluate_prediction(pred, target_date)

            # Add prediction metadata to result for CSV logging
            eval_result[score_key] = pred.get(score_key, 0.0)
            eval_result[ml_prob_key] = pred.get(ml_prob_key, 0.0)

            results.append(eval_result)

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
            win_statuses = ['success', 'closed_profit', 'split_full_profit', 'split_partial_profit']
            success_count = sum(1 for r in valid_results if r['status'] in win_statuses)
            win_rate = (success_count / len(valid_results)) * 100
            ReportSingleton().write(f"Summary: {success_count}/{len(valid_results)} profitable ({win_rate:.2f}%) | Avg PnL: {avg_pnl:.2f}%")

    def _log_results_to_csv(self, results: List[Dict], target_date: str, options: BacktestOptions) -> None:
        """Log backtest results to CSV file for analysis."""
        log_path = Path('src/logs/backtest_log.csv')
        file_exists = log_path.exists()

        # Ensure logs directory exists
        log_path.parent.mkdir(parents=True, exist_ok=True)

        score_key = "baseline_score" if options.strategy == "baseline" else "mr_score"
        ml_prob_key = "baseline_ml_prob" if options.strategy == "baseline" else "mr_ml_prob"

        with open(log_path, 'a', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'date', 'symbol', 'strategy', 'score', 'ml_prob',
                'entry', 'stop_loss', 'take_profit', 'exit_price',
                'exit_date', 'days_held', 'status', 'outcome', 'profit_loss'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            if not file_exists:
                writer.writeheader()

            for result in results:
                # Calculate outcome and P&L
                if result.get('entry') and result.get('exit_price'):
                    pnl = ((result['exit_price'] / result['entry']) - 1) * 100
                    win_statuses = ['success', 'closed_profit', 'split_full_profit', 'split_partial_profit']
                    loss_statuses = ['stopped_out', 'closed_loss']
                    if result['status'] in win_statuses:
                        outcome = 'WIN'
                    elif result['status'] in loss_statuses:
                        outcome = 'LOSS'
                    else:
                        outcome = 'TIMEOUT'
                else:
                    pnl = 0.0
                    outcome = 'NO_ENTRY'

                row_data = {
                    'date': target_date,
                    'symbol': result.get('symbol', ''),
                    'strategy': options.strategy,
                    'score': result.get(score_key, 0.0),
                    'ml_prob': result.get(ml_prob_key, 0.0),
                    'entry': result.get('entry', ''),
                    'stop_loss': result.get('stop_loss', ''),
                    'take_profit': result.get('take_profit', ''),
                    'exit_price': result.get('exit_price', ''),
                    'exit_date': result.get('exit_date', ''),
                    'days_held': result.get('days_held', 0),
                    'status': result.get('status', ''),
                    'outcome': outcome,
                    'profit_loss': round(pnl, 2)
                }

                # Add split-exit columns when present
                if result.get('exit_mode') == 'split_exit':
                    row_data['t1_status'] = result.get('tranche1_status', '')
                    row_data['t1_pnl'] = round(result.get('tranche1_pnl_pct', 0.0), 2)
                    row_data['t2_status'] = result.get('tranche2_status', '')
                    row_data['t2_pnl'] = round(result.get('tranche2_pnl_pct', 0.0), 2)

                writer.writerow(row_data)

    def run_backtest(self, target_date: str, options: BacktestOptions = None,
                     split_config: 'Optional[SplitExitConfig]' = None):
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

        results = self._evaluate_candidates(top_predictions, target_date, options, split_config=split_config)

        self._print_summary(results)

        # Log results to CSV for analysis
        self._log_results_to_csv(results, target_date, options)

        return results

    def _summarize_range_results(self, all_results):
        """Summarize aggregated backtest results."""
        valid_all = [r for r in all_results if 'entry' in r and 'exit_price' in r]
        if not valid_all:
            ReportSingleton().write("\nNo valid trades in range.")
            return

        total_trades = len(valid_all)
        win_statuses = ['success', 'closed_profit', 'split_full_profit', 'split_partial_profit']
        profitable_trades = sum(1 for r in valid_all if r['status'] in win_statuses)
        total_pnl = sum(((r['exit_price'] / r['entry']) - 1) * 100 for r in valid_all)
        avg_pnl = total_pnl / total_trades
        win_rate = (profitable_trades / total_trades) * 100

        ReportSingleton().write("\n--- FINAL STRESS TEST SUMMARY ---")
        ReportSingleton().write(f"Total Trades Evaluated: {total_trades}")
        ReportSingleton().write(f"Overall Win Rate: {win_rate:.2f}%")
        ReportSingleton().write(f"Overall Average PnL: {avg_pnl:.2f}%")
        ReportSingleton().write(f"Total Cumulative PnL: {total_pnl:.2f}%")
        ReportSingleton().write("---------------------------------")

    def run_range_backtest(self, start_date: str, end_date: str, interval_days: int = 7,
                          options: BacktestOptions = None, split_config: 'Optional[SplitExitConfig]' = None):
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
            symbols = get_symbol_name_list(database=self.database, active_only=True)
            print(f" Done ({len(symbols)} symbols).", flush=True)
            # Update options with loaded symbols to pass down
            options.symbols = symbols

        while current_ts <= end_ts:
            date_str = current_ts.strftime('%Y-%m-%d')
            print(f"\n--- Processing Step {current_step}/{total_steps}: {date_str} ---", flush=True)
            day_results = self.run_backtest(date_str, options=options, split_config=split_config)
            all_results.extend(day_results)
            current_ts += pd.Timedelta(days=interval_days)
            current_step += 1

        # Aggregate Summary
        self._summarize_range_results(all_results)
