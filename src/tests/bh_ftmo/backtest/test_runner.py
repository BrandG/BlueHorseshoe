"""Tests for the Phase 3.4 comparison harness."""

from __future__ import annotations

# pylint: disable=missing-function-docstring

from datetime import datetime, timedelta
import pickle

import pandas as pd

from bh_ftmo.analysis.strategy import Signal
from bh_ftmo.backtest.engine import StartConfig
from bh_ftmo.backtest.runner import run_full_comparison
from bh_ftmo.backtest.swap import SwapRates
from bh_ftmo.backtest.types import PairSpec

BASE_CONFIG = {
    'initial_balance': 100_000.0,
    'account_currency': 'USD',
    'phase': 'challenge',
    'profit_target_pct': 0.10,
    'daily_loss_pct': 0.05,
    'max_loss_pct': 0.10,
    'max_loss_type': 'static',
    'min_trading_days': 1,
    'max_trading_days': 14,
    'server_timezone': 'Europe/Prague',
    'commission_per_lot_round_turn': 0.0,
    'swap_model': 'standard',
}


def _bars_4h(start: datetime, periods: int) -> pd.DataFrame:
    timestamps = pd.date_range(start, periods=periods, freq='4h')
    prices = [1.1000 + ((idx % 8) - 4) * 0.0015 for idx in range(periods)]
    frame = pd.DataFrame({'timestamp': timestamps})
    frame['open_bid'] = prices
    frame['open_ask'] = frame['open_bid'] + 0.0002
    frame['close_bid'] = frame['open_bid'] + 0.0008
    frame['close_ask'] = frame['close_bid'] + 0.0002
    frame['high_bid'] = frame[['open_bid', 'close_bid']].max(axis=1) + 0.0025
    frame['high_ask'] = frame['high_bid'] + 0.0002
    frame['low_bid'] = frame[['open_bid', 'close_bid']].min(axis=1) - 0.0025
    frame['low_ask'] = frame['low_bid'] + 0.0002
    return frame


def _bars_1h(frame_4h: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in frame_4h.itertuples(index=False):
        for step in range(1, 5):
            close_bid = row.open_bid + 0.0004 * step
            rows.append(
                {
                    'timestamp': row.timestamp + timedelta(hours=step),
                    'close_bid': close_bid,
                    'close_ask': close_bid + 0.0002,
                    'high_bid': row.high_bid,
                    'high_ask': row.high_ask,
                    'low_bid': row.low_bid,
                    'low_ask': row.low_ask,
                }
            )
    return pd.DataFrame(rows)


def _bh_signal(ts: datetime) -> Signal:
    return Signal(
        symbol='EUR_USD',
        strategy='bh_ftmo',
        timestamp=ts,
        direction=1,
        score=1.0,
        components={'edge': 1.0},
        above_threshold=True,
    )


def test_run_full_comparison_returns_all_four_strategies_with_one_result_per_start():
    start = datetime(2026, 1, 5, 0, 0)
    bars_4h = {'EUR_USD': _bars_4h(start, 84)}
    bars_1h = {'EUR_USD': _bars_1h(bars_4h['EUR_USD'])}
    atr_index = pd.to_datetime(bars_4h['EUR_USD']['timestamp'])
    atr_by_symbol = {'EUR_USD': pd.Series(0.0020, index=atr_index)}
    starts = [
        StartConfig(start_ts=start, end_ts=start + timedelta(days=14), rng_seed=1),
        StartConfig(start_ts=start + timedelta(days=7), end_ts=start + timedelta(days=21), rng_seed=2),
    ]
    results = run_full_comparison(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        atr_by_symbol=atr_by_symbol,
        pair_specs={'EUR_USD': PairSpec('EUR_USD', 0.0001, 100_000)},
        ftmo_config=dict(BASE_CONFIG),
        sizing_config={'risk_pct_per_trade': 0.005, 'k_stop': 1.5, 'k_target': 2.5},
        swap_rates_by_symbol={'EUR_USD': SwapRates(0.0, 0.0)},
        bh_ftmo_signals=[_bh_signal(ts) for ts in atr_index[::12][:4]],
        starts=starts,
        rng_seed=7,
        max_workers=1,
    )
    assert sorted(results) == ['bh_ftmo', 'monday_friday', 'random_baseline', 'rsi_14']
    assert all(len(strategy_results) == len(starts) for strategy_results in results.values())
    assert all(trade.strategy == 'bh_ftmo' for result in results['bh_ftmo'] for trade in result.trades)


def test_start_config_list_is_picklable():
    starts = [StartConfig(start_ts=datetime(2026, 1, 1), end_ts=datetime(2026, 1, 15), rng_seed=3)]
    round_trip = pickle.loads(pickle.dumps(starts))
    assert round_trip == starts
