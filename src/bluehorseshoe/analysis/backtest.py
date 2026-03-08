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
import numpy as np
import pandas as pd
from bluehorseshoe.analysis.strategy import SwingTrader, StrategyContext
from bluehorseshoe.core.scores import ScoreManager
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
    use_saved_scores: bool = True  # Load from MongoDB; False = recalculate fresh

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

    def __init__(self, config: BacktestConfig = None, database=None, store=None):
        """
        Initialize Backtester with optional dependency injection.

        Args:
            config: BacktestConfig instance
            database: MongoDB database instance. If None, uses global singleton.
            store: DuckDBStore for OHLCV data. If provided, used for bulk price loads.
        """
        if config is None:
            config = BacktestConfig()
        self.database = database
        self.store = store
        self.trader = SwingTrader(database=database, store=store)
        self.score_manager = ScoreManager(database=database) if database is not None else None
        self.config = config
        # Expose config attributes
        self.hold_days = config.hold_days
        self.use_trailing_stop = config.use_trailing_stop
        self.trailing_multiplier = config.trailing_multiplier
        self.target_profit_factor = config.target_profit_factor
        self.stop_loss_factor = config.stop_loss_factor

    def _bulk_load_price_data(self, symbols, target_date):
        """
        Load future price data for multiple symbols.
        Uses DuckDB bulk load when available, otherwise falls back to MongoDB aggregation.

        Args:
            symbols: List of stock symbols to load.
            target_date: Analysis date string; returns data after this date.

        Returns:
            Dict mapping symbol -> DataFrame of future OHLCV data (sorted by date).
        """
        if self.store is None:
            return {}

        bulk = self.store.load_symbols_bulk(symbols, start_date=target_date)
        result = {}
        for sym, df in bulk.items():
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            if not df.empty:
                result[sym] = df
        return result

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
            price_data = load_historical_data(symbol, database=self.database, store=self.store)
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
                # Move T2 stop to entry - 2% (cap max T2 loss)
                state.t2_stop = state.actual_entry * 0.98

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
                state.t2_stop = state.actual_entry * 0.98  # Move T2 stop to entry - 2%

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
            price_data = load_historical_data(symbol, database=self.database, store=self.store)
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

    # ------------------------------------------------------------------
    # Vectorized simulation methods
    # ------------------------------------------------------------------

    def _vectorized_simulate_single_exit(self, predictions, price_data):
        """
        Simulate single-exit trades for all predictions simultaneously using numpy.

        Args:
            predictions: List of dicts with 'symbol', 'entry_price', 'stop_loss', 'take_profit'.
            price_data: Dict mapping symbol -> DataFrame of future OHLCV data.

        Returns:
            List of result dicts (same schema as evaluate_prediction).
        """
        n = len(predictions)
        if n == 0:
            return []

        # Status codes
        PENDING, ACTIVE, STOPPED, SUCCESS, LIMIT_EXPIRED = 0, 1, 2, 3, 4
        CLOSED_PROFIT, CLOSED_LOSS, NO_FUTURE_DATA = 5, 6, 7
        STATUS_MAP = {
            STOPPED: 'stopped_out', SUCCESS: 'success',
            LIMIT_EXPIRED: 'limit_expired', CLOSED_PROFIT: 'closed_profit',
            CLOSED_LOSS: 'closed_loss', NO_FUTURE_DATA: 'no_future_data',
            PENDING: 'no_entry',
        }

        # Build trade parameter arrays
        entry_prices = np.array([p['entry_price'] for p in predictions], dtype=np.float64)
        stop_losses = np.array([p['stop_loss'] for p in predictions], dtype=np.float64)
        take_profits = np.array([p['take_profit'] for p in predictions], dtype=np.float64)

        # Determine max future days across all symbols
        symbols = [p['symbol'] for p in predictions]
        dfs = []
        has_data = np.zeros(n, dtype=bool)
        for idx, sym in enumerate(symbols):
            if sym in price_data:
                dfs.append(price_data[sym])
                has_data[idx] = True
            else:
                dfs.append(None)

        max_days = max((len(df) for df in dfs if df is not None), default=0)
        if max_days == 0:
            return [{'symbol': p['symbol'], 'status': 'no_future_data',
                      'entry': None, 'exit_price': None, 'exit_date': None, 'days_held': 0}
                     for p in predictions]

        # Build price matrices (N x max_days), NaN-padded
        opens = np.full((n, max_days), np.nan)
        highs = np.full((n, max_days), np.nan)
        lows = np.full((n, max_days), np.nan)
        closes = np.full((n, max_days), np.nan)
        # Store dates for exit_date reporting
        dates = [[None] * max_days for _ in range(n)]

        for idx in range(n):
            df = dfs[idx]
            if df is not None:
                length = len(df)
                opens[idx, :length] = df['open'].values
                highs[idx, :length] = df['high'].values
                lows[idx, :length] = df['low'].values
                closes[idx, :length] = df['close'].values
                for d in range(length):
                    dates[idx][d] = df['date'].iloc[d]

        valid = ~np.isnan(opens)  # N x max_days

        # State arrays
        status = np.full(n, PENDING, dtype=np.int8)
        status[~has_data] = NO_FUTURE_DATA
        actual_entry = np.full(n, np.nan)
        exit_price = np.full(n, np.nan)
        exit_day = np.full(n, -1, dtype=np.int32)
        entry_day = np.full(n, -1, dtype=np.int32)

        hold_days = self.hold_days

        for d in range(max_days):
            v = valid[:, d]
            o = opens[:, d]
            h = highs[:, d]
            l = lows[:, d]
            c = closes[:, d]

            # --- PENDING trades: check for entry ---
            pending = (status == PENDING) & v
            if pending.any():
                # Entry triggered: low <= entry_price
                can_enter = pending & (l <= entry_prices)
                if can_enter.any():
                    # Slippage: actual_entry = min(open, entry_price)
                    ae = np.where(o < entry_prices, o, entry_prices)

                    # Check intraday stop (priority over target)
                    intra_stop = can_enter & (l <= stop_losses)
                    if intra_stop.any():
                        sp = np.where(o < stop_losses, o, stop_losses)
                        status[intra_stop] = STOPPED
                        actual_entry[intra_stop] = ae[intra_stop]
                        exit_price[intra_stop] = sp[intra_stop]
                        exit_day[intra_stop] = d
                        entry_day[intra_stop] = d

                    # Check intraday target (only for trades not already stopped)
                    still_entering = can_enter & (status == PENDING)
                    intra_target = still_entering & (h >= take_profits)
                    if intra_target.any():
                        tp = np.where(o > take_profits, o, take_profits)
                        status[intra_target] = SUCCESS
                        actual_entry[intra_target] = ae[intra_target]
                        exit_price[intra_target] = tp[intra_target]
                        exit_day[intra_target] = d
                        entry_day[intra_target] = d

                    # Remaining entries become active
                    newly_active = can_enter & (status == PENDING)
                    if newly_active.any():
                        status[newly_active] = ACTIVE
                        actual_entry[newly_active] = ae[newly_active]
                        entry_day[newly_active] = d

                # Limit expired: no entry within hold_days
                no_entry_expire = pending & ~can_enter & (d >= hold_days)
                if no_entry_expire.any():
                    status[no_entry_expire] = LIMIT_EXPIRED

            # --- ACTIVE trades: check exit conditions ---
            active = (status == ACTIVE) & v
            if active.any():
                # Stop loss (priority)
                hit_stop = active & (l <= stop_losses)
                if hit_stop.any():
                    sp = np.where(o < stop_losses, o, stop_losses)
                    status[hit_stop] = STOPPED
                    exit_price[hit_stop] = sp[hit_stop]
                    exit_day[hit_stop] = d

                # Take profit (only if not already stopped this bar)
                still_active = active & (status == ACTIVE)
                hit_target = still_active & (h >= take_profits)
                if hit_target.any():
                    tp = np.where(o > take_profits, o, take_profits)
                    status[hit_target] = SUCCESS
                    exit_price[hit_target] = tp[hit_target]
                    exit_day[hit_target] = d

                # Time exit
                still_active2 = active & (status == ACTIVE)
                time_up = still_active2 & ((d - entry_day) >= hold_days)
                if time_up.any():
                    profit_exit = time_up & (c > actual_entry)
                    loss_exit = time_up & ~profit_exit
                    status[profit_exit] = CLOSED_PROFIT
                    status[loss_exit] = CLOSED_LOSS
                    exit_price[time_up] = c[time_up]
                    exit_day[time_up] = d

            # Early termination
            unresolved = (status == PENDING) | (status == ACTIVE)
            if not unresolved.any():
                break

        # Mark-to-market: still active trades exit at last valid close
        still_active = (status == ACTIVE)
        if still_active.any():
            for idx in np.where(still_active)[0]:
                # Find last valid day
                last_d = np.where(valid[idx])[0]
                if len(last_d) > 0:
                    ld = last_d[-1]
                    exit_price[idx] = closes[idx, ld]
                    exit_day[idx] = ld
                    if closes[idx, ld] > actual_entry[idx]:
                        status[idx] = CLOSED_PROFIT
                    else:
                        status[idx] = CLOSED_LOSS

        # Build result list
        results = []
        for idx in range(n):
            s = int(status[idx])
            ed = int(exit_day[idx])
            eidx = int(entry_day[idx])
            results.append({
                'symbol': symbols[idx],
                'status': STATUS_MAP.get(s, 'no_entry'),
                'entry': float(actual_entry[idx]) if not np.isnan(actual_entry[idx]) else None,
                'exit_price': float(exit_price[idx]) if not np.isnan(exit_price[idx]) else None,
                'exit_date': dates[idx][ed] if 0 <= ed < max_days else None,
                'days_held': (ed - eidx) if eidx >= 0 and ed >= 0 else 0,
            })
        return results

    def _vectorized_simulate_split_exit(self, predictions, price_data, split_config):
        """
        Simulate split-exit (two-tranche) trades for all predictions using numpy.

        Args:
            predictions: List of dicts with 'symbol', 'entry_price', 'stop_loss', 'take_profit'.
            price_data: Dict mapping symbol -> DataFrame of future OHLCV data.
            split_config: SplitExitConfig instance.

        Returns:
            List of result dicts (same schema as evaluate_prediction_split).
        """
        n = len(predictions)
        if n == 0:
            return []

        # Phase codes
        PRE_ENTRY, BOTH_ACTIVE, T1_EXITED, COMPLETE = 0, 1, 2, 3

        # Build trade parameter arrays
        entry_prices = np.array([p['entry_price'] for p in predictions], dtype=np.float64)
        stop_losses = np.array([p['stop_loss'] for p in predictions], dtype=np.float64)
        take_profits = np.array([p['take_profit'] for p in predictions], dtype=np.float64)

        # Compute T1/T2 targets
        if split_config.mode == 'fixed_pct':
            t1_targets = entry_prices * (1 + split_config.t1_profit_pct)
            t2_targets = take_profits.copy()
        else:
            # atr_tiered
            atrs = np.array([p.get('atr', 0) for p in predictions], dtype=np.float64)
            # Fallback for zero ATR: use half the entry-to-stop distance
            zero_atr = atrs <= 0
            atrs[zero_atr] = np.abs(entry_prices[zero_atr] - stop_losses[zero_atr]) / 2
            t1_targets = entry_prices + split_config.t1_atr_multiple * atrs
            t2_targets = entry_prices + split_config.t2_atr_multiple * atrs

        # Build price matrices
        symbols = [p['symbol'] for p in predictions]
        dfs = []
        has_data = np.zeros(n, dtype=bool)
        for idx, sym in enumerate(symbols):
            if sym in price_data:
                dfs.append(price_data[sym])
                has_data[idx] = True
            else:
                dfs.append(None)

        max_days = max((len(df) for df in dfs if df is not None), default=0)
        if max_days == 0:
            return [{'symbol': p['symbol'], 'status': 'no_future_data',
                      'entry': None, 'exit_price': None, 'exit_date': None,
                      'days_held': 0, 'exit_mode': 'split_exit'}
                     for p in predictions]

        opens = np.full((n, max_days), np.nan)
        highs = np.full((n, max_days), np.nan)
        lows = np.full((n, max_days), np.nan)
        closes = np.full((n, max_days), np.nan)
        dates = [[None] * max_days for _ in range(n)]

        for idx in range(n):
            df = dfs[idx]
            if df is not None:
                length = len(df)
                opens[idx, :length] = df['open'].values
                highs[idx, :length] = df['high'].values
                lows[idx, :length] = df['low'].values
                closes[idx, :length] = df['close'].values
                for d in range(length):
                    dates[idx][d] = df['date'].iloc[d]

        valid = ~np.isnan(opens)

        # State arrays
        phase = np.full(n, PRE_ENTRY, dtype=np.int8)
        phase[~has_data] = COMPLETE
        actual_entry = np.full(n, np.nan)
        entry_day = np.full(n, -1, dtype=np.int32)

        t1_status = np.full(n, 0, dtype=np.int8)  # 0=pending, 1=profit, 2=stopped, 3=time_exit, 4=no_entry
        t1_exit_price = np.full(n, np.nan)
        t1_exit_day = np.full(n, -1, dtype=np.int32)

        t2_status = np.full(n, 0, dtype=np.int8)
        t2_exit_price = np.full(n, np.nan)
        t2_exit_day = np.full(n, -1, dtype=np.int32)
        t2_stops = stop_losses.copy()  # starts at original stop, moves after T1 exit

        T1_PROFIT, T1_STOPPED, T1_TIME, T1_NO_ENTRY = 1, 2, 3, 4

        hold_days = self.hold_days

        for d in range(max_days):
            v = valid[:, d]
            o = opens[:, d]
            h = highs[:, d]
            l = lows[:, d]
            c = closes[:, d]

            # --- PRE_ENTRY ---
            pre = (phase == PRE_ENTRY) & v
            if pre.any():
                can_enter = pre & (l <= entry_prices)
                if can_enter.any():
                    ae = np.where(o < entry_prices, o, entry_prices)

                    # Intraday stop (both tranches)
                    intra_stop = can_enter & (l <= stop_losses)
                    if intra_stop.any():
                        sp = np.where(o < stop_losses, o, stop_losses)
                        actual_entry[intra_stop] = ae[intra_stop]
                        entry_day[intra_stop] = d
                        t1_status[intra_stop] = T1_STOPPED
                        t1_exit_price[intra_stop] = sp[intra_stop]
                        t1_exit_day[intra_stop] = d
                        t2_status[intra_stop] = T1_STOPPED
                        t2_exit_price[intra_stop] = sp[intra_stop]
                        t2_exit_day[intra_stop] = d
                        phase[intra_stop] = COMPLETE

                    # Intraday T1 target (not already stopped)
                    still_pre = can_enter & (phase == PRE_ENTRY)
                    intra_t1 = still_pre & (h >= t1_targets)
                    if intra_t1.any():
                        t1_px = np.where(o > t1_targets, o, t1_targets)
                        actual_entry[intra_t1] = ae[intra_t1]
                        entry_day[intra_t1] = d
                        t1_status[intra_t1] = T1_PROFIT
                        t1_exit_price[intra_t1] = t1_px[intra_t1]
                        t1_exit_day[intra_t1] = d
                        phase[intra_t1] = T1_EXITED
                        # Move T2 stop to entry - 2%
                        t2_stops[intra_t1] = ae[intra_t1] * 0.98

                        # Check T2 on same bar
                        intra_t2 = intra_t1 & (h >= t2_targets)
                        if intra_t2.any():
                            t2_px = np.where(o > t2_targets, o, t2_targets)
                            t2_status[intra_t2] = T1_PROFIT
                            t2_exit_price[intra_t2] = t2_px[intra_t2]
                            t2_exit_day[intra_t2] = d
                            phase[intra_t2] = COMPLETE

                    # Remaining become BOTH_ACTIVE
                    newly_active = can_enter & (phase == PRE_ENTRY)
                    if newly_active.any():
                        actual_entry[newly_active] = ae[newly_active]
                        entry_day[newly_active] = d
                        phase[newly_active] = BOTH_ACTIVE

                # Limit expired
                no_entry_expire = pre & ~(l <= entry_prices) & (d >= hold_days)
                if no_entry_expire.any():
                    t1_status[no_entry_expire] = T1_NO_ENTRY
                    t2_status[no_entry_expire] = T1_NO_ENTRY
                    phase[no_entry_expire] = COMPLETE

            # --- BOTH_ACTIVE ---
            both = (phase == BOTH_ACTIVE) & v
            if both.any():
                # Stop (both tranches)
                hit_stop = both & (l <= stop_losses)
                if hit_stop.any():
                    sp = np.where(o < stop_losses, o, stop_losses)
                    t1_status[hit_stop] = T1_STOPPED
                    t1_exit_price[hit_stop] = sp[hit_stop]
                    t1_exit_day[hit_stop] = d
                    t2_status[hit_stop] = T1_STOPPED
                    t2_exit_price[hit_stop] = sp[hit_stop]
                    t2_exit_day[hit_stop] = d
                    phase[hit_stop] = COMPLETE

                # T1 target
                still_both = both & (phase == BOTH_ACTIVE)
                hit_t1 = still_both & (h >= t1_targets)
                if hit_t1.any():
                    t1_px = np.where(o > t1_targets, o, t1_targets)
                    t1_status[hit_t1] = T1_PROFIT
                    t1_exit_price[hit_t1] = t1_px[hit_t1]
                    t1_exit_day[hit_t1] = d
                    phase[hit_t1] = T1_EXITED
                    t2_stops[hit_t1] = actual_entry[hit_t1] * 0.98

                    # T2 on same bar
                    hit_t1_t2 = hit_t1 & (h >= t2_targets)
                    if hit_t1_t2.any():
                        t2_px = np.where(o > t2_targets, o, t2_targets)
                        t2_status[hit_t1_t2] = T1_PROFIT
                        t2_exit_price[hit_t1_t2] = t2_px[hit_t1_t2]
                        t2_exit_day[hit_t1_t2] = d
                        phase[hit_t1_t2] = COMPLETE

                # Time exit (both)
                still_both2 = both & (phase == BOTH_ACTIVE)
                time_up = still_both2 & ((d - entry_day) >= hold_days)
                if time_up.any():
                    t1_status[time_up] = T1_TIME
                    t1_exit_price[time_up] = c[time_up]
                    t1_exit_day[time_up] = d
                    t2_status[time_up] = T1_TIME
                    t2_exit_price[time_up] = c[time_up]
                    t2_exit_day[time_up] = d
                    phase[time_up] = COMPLETE

            # --- T1_EXITED ---
            t1ex = (phase == T1_EXITED) & v
            if t1ex.any():
                # T2 stop
                hit_t2_stop = t1ex & (l <= t2_stops)
                if hit_t2_stop.any():
                    sp = np.where(o < t2_stops, o, t2_stops)
                    t2_status[hit_t2_stop] = T1_STOPPED
                    t2_exit_price[hit_t2_stop] = sp[hit_t2_stop]
                    t2_exit_day[hit_t2_stop] = d
                    phase[hit_t2_stop] = COMPLETE

                # T2 target
                still_t1ex = t1ex & (phase == T1_EXITED)
                hit_t2 = still_t1ex & (h >= t2_targets)
                if hit_t2.any():
                    t2_px = np.where(o > t2_targets, o, t2_targets)
                    t2_status[hit_t2] = T1_PROFIT
                    t2_exit_price[hit_t2] = t2_px[hit_t2]
                    t2_exit_day[hit_t2] = d
                    phase[hit_t2] = COMPLETE

                # T2 time exit
                still_t1ex2 = t1ex & (phase == T1_EXITED)
                time_up_t2 = still_t1ex2 & ((d - entry_day) >= hold_days)
                if time_up_t2.any():
                    t2_status[time_up_t2] = T1_TIME
                    t2_exit_price[time_up_t2] = c[time_up_t2]
                    t2_exit_day[time_up_t2] = d
                    phase[time_up_t2] = COMPLETE

            # Early termination
            if not ((phase != COMPLETE) & has_data).any():
                break

        # Mark-to-market: incomplete trades
        for idx in np.where((phase != COMPLETE) & has_data)[0]:
            last_valid = np.where(valid[idx])[0]
            if len(last_valid) == 0:
                continue
            ld = last_valid[-1]
            last_close = closes[idx, ld]
            last_day = ld
            if np.isnan(t1_exit_price[idx]):
                t1_status[idx] = T1_TIME
                t1_exit_price[idx] = last_close
                t1_exit_day[idx] = last_day
            if np.isnan(t2_exit_price[idx]):
                t2_status[idx] = T1_TIME
                t2_exit_price[idx] = last_close
                t2_exit_day[idx] = last_day
            phase[idx] = COMPLETE

        # No-data trades
        for idx in np.where(~has_data)[0]:
            t1_status[idx] = T1_NO_ENTRY
            t2_status[idx] = T1_NO_ENTRY

        # Build results
        T_STATUS_MAP = {0: 'pending', 1: 'profit', 2: 'stopped', 3: 'time_exit', 4: 'no_entry'}
        w = split_config.tranche_weight

        results = []
        for idx in range(n):
            sym = symbols[idx]
            ae = actual_entry[idx]
            t1s = int(t1_status[idx])
            t2s = int(t2_status[idx])
            t1_str = T_STATUS_MAP.get(t1s, 'pending')
            t2_str = T_STATUS_MAP.get(t2s, 'pending')

            if not has_data[idx]:
                results.append({
                    'symbol': sym, 'status': 'no_future_data',
                    'entry': None, 'exit_price': None, 'exit_date': None,
                    'days_held': 0, 'exit_mode': 'split_exit',
                })
                continue

            if np.isnan(ae) or t1_str == 'no_entry':
                results.append({
                    'symbol': sym, 'status': 'no_entry',
                    'entry': None, 'exit_price': None, 'exit_date': None,
                    'days_held': 0, 'exit_mode': 'split_exit',
                })
                continue

            entry = float(ae)
            t1_ep = float(t1_exit_price[idx])
            t2_ep = float(t2_exit_price[idx])

            t1_pnl = ((t1_ep / entry) - 1) * 100
            t2_pnl = ((t2_ep / entry) - 1) * 100
            blended_pnl = w * t1_pnl + (1 - w) * t2_pnl

            # Overall status
            if t1_str == 'profit' and t2_str == 'profit':
                overall = 'split_full_profit'
            elif t1_str == 'profit' and t2_str in ('stopped', 'time_exit'):
                overall = 'split_partial_profit'
            elif t1_str == 'stopped' and t2_str == 'stopped':
                overall = 'stopped_out'
            elif blended_pnl > 0:
                overall = 'closed_profit'
            else:
                overall = 'closed_loss'

            synthetic_exit = entry * (1 + blended_pnl / 100)
            ed = int(t2_exit_day[idx]) if t2_exit_day[idx] >= 0 else int(t1_exit_day[idx])
            exit_date = dates[idx][ed] if 0 <= ed < max_days else None
            eidx = int(entry_day[idx])
            days_held = (ed - eidx) if eidx >= 0 and ed >= 0 else 0

            results.append({
                'symbol': sym,
                'status': overall,
                'entry': entry,
                'exit_price': synthetic_exit,
                'exit_date': exit_date,
                'days_held': days_held,
                'blended_pnl_pct': blended_pnl,
                'tranche1_exit_price': t1_ep,
                'tranche1_status': t1_str,
                'tranche1_pnl_pct': t1_pnl,
                'tranche2_exit_price': t2_ep,
                'tranche2_status': t2_str,
                'tranche2_pnl_pct': t2_pnl,
                'exit_mode': 'split_exit',
            })
        return results

    def _evaluate_candidates_vectorized(self, top_predictions, target_date, options,
                                        split_config=None):
        """
        Vectorized version of _evaluate_candidates using bulk data load + numpy simulation.

        Args:
            top_predictions: List of prediction dicts (pre-sorted, pre-filtered).
            target_date: Analysis date string.
            options: BacktestOptions instance.
            split_config: Optional SplitExitConfig for two-tranche mode.

        Returns:
            List of result dicts with score/ML metadata attached.
        """
        score_key = "baseline_score" if options.strategy == "baseline" else "mr_score"
        setup_key = "baseline_setup" if options.strategy == "baseline" else "mr_setup"
        ml_prob_key = "baseline_ml_prob" if options.strategy == "baseline" else "mr_ml_prob"

        # Flatten setup into top-level keys
        flat_preds = []
        for pred in top_predictions:
            setup = pred.get(setup_key, {})
            flat_preds.append({
                'symbol': pred['symbol'],
                'entry_price': setup.get('entry_price'),
                'stop_loss': setup.get('stop_loss'),
                'take_profit': setup.get('take_profit'),
                'atr': pred.get('atr', 0),
            })

        # Bulk-load price data for all symbols
        all_symbols = [p['symbol'] for p in flat_preds]
        price_data = self._bulk_load_price_data(all_symbols, target_date)

        # Dispatch to appropriate simulation
        if split_config is not None:
            results = self._vectorized_simulate_split_exit(flat_preds, price_data, split_config)
        else:
            results = self._vectorized_simulate_single_exit(flat_preds, price_data)

        # Attach score/ML/sentiment metadata and log per-trade output
        for i, result in enumerate(results):
            pred = top_predictions[i]
            result[score_key] = pred.get(score_key, 0.0)
            result[ml_prob_key] = pred.get(ml_prob_key, 0.0)
            result['sentiment'] = pred.get('sentiment', 0.0)

            score_val = pred.get(score_key, 0.0)
            ml_prob = pred.get(ml_prob_key, 0.0)
            msg = f"{pred['symbol']} (Score: {score_val:.2f} | ML: {ml_prob*100:.1f}%): {result['status']}"
            if result.get('entry') is not None and result.get('exit_price') is not None:
                pnl = ((result['exit_price'] / result['entry']) - 1) * 100
                msg += (f" | PnL: {pnl:.2f}% (Entry: {result['entry']:.2f}, "
                        f"Exit: {result['exit_price']:.2f}, Held: {result['days_held']} days)")
            ReportSingleton().write(msg)

        return results

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

    def _load_saved_predictions(self, target_date: str, options: BacktestOptions) -> Optional[List[Dict]]:
        """Load pre-computed scores from MongoDB instead of recalculating."""
        if self.score_manager is None:
            return None

        strategy_name = "baseline" if options.strategy == "baseline" else "mean_reversion"
        scores = self.score_manager.get_scores(target_date, strategy=strategy_name)

        if not scores:
            return None

        score_key = "baseline_score" if options.strategy == "baseline" else "mr_score"
        setup_key = "baseline_setup" if options.strategy == "baseline" else "mr_setup"
        ml_prob_key = "baseline_ml_prob" if options.strategy == "baseline" else "mr_ml_prob"

        predictions = []
        for s in scores:
            meta = s.get('metadata', {})
            entry = meta.get('entry_price')
            if not entry:
                continue
            predictions.append({
                'symbol': s['symbol'],
                score_key: s['score'],
                setup_key: {
                    'entry_price': entry,
                    'stop_loss': meta.get('stop_loss', 0),
                    'take_profit': meta.get('take_profit', 0),
                },
                ml_prob_key: meta.get('ml_win_prob', 0.0),
                'stop_multiplier': meta.get('stop_multiplier', 2.0),
                'target_multiplier': meta.get('target_multiplier', 3.0),
                'sentiment': meta.get('sentiment', 0.0),
            })

        logging.info("Loaded %d saved %s scores for %s", len(predictions), options.strategy, target_date)
        return predictions

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
        # Dispatch to vectorized path when DuckDB store is available
        if self.store is not None:
            return self._evaluate_candidates_vectorized(
                top_predictions, target_date, options, split_config
            )

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
            eval_result['sentiment'] = pred.get('sentiment', 0.0)

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
                'date', 'symbol', 'strategy', 'score', 'ml_prob', 'sentiment',
                'entry', 'stop_loss', 'take_profit', 'exit_price',
                'exit_date', 'days_held', 'status', 'outcome', 'profit_loss',
                't1_status', 't1_pnl', 't2_status', 't2_pnl'
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
                    'sentiment': result.get('sentiment', 0.0),
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

        predictions = None
        if options.use_saved_scores:
            predictions = self._load_saved_predictions(target_date, options)
            if predictions:
                print(f"  > Loaded {len(predictions)} saved scores for {target_date} (skipping re-scoring)")
            else:
                print(f"  > No saved scores for {target_date}, falling back to fresh calculation...")

        if predictions is None:
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

        valid_all = [r for r in valid_all if r.get('exit_price') is not None and r.get('entry') is not None]
        if not valid_all:
            ReportSingleton().write("\nNo valid trades with entry/exit prices in range.")
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
