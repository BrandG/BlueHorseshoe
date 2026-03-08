"""
Tests for vectorized backtesting: bulk DuckDB load + numpy simulation.

Covers:
1. Parity: single-exit  — vectorized vs sequential produce identical results
2. Parity: split-exit   — same for two-tranche mode
3. All single-exit statuses — success, stopped_out, limit_expired, closed_profit, closed_loss, no_future_data
4. Bulk load — verify DuckDB store.load_symbols_bulk() is called
5. Mixed data availability — some symbols have data, some don't
6. Intraday stop on entry bar — stop-before-target priority
7. Mark-to-market — trade active when data ends
8. Empty predictions — returns empty list
9. No store fallback — store=None routes to sequential path
10. Split-exit: full profit, partial profit, both stopped
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch, call

from bluehorseshoe.analysis.backtest import (
    Backtester, BacktestConfig, BacktestOptions, SplitExitConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_future_df(bars):
    """Build a DataFrame from (date, open, high, low, close) tuples."""
    rows = [{'date': pd.Timestamp(d), 'open': o, 'high': h, 'low': l, 'close': c}
            for d, o, h, l, c in bars]
    return pd.DataFrame(rows)


def _make_store_with_data(data_by_symbol):
    """Create a mock DuckDB store whose load_symbols_bulk() returns DataFrames."""
    store = MagicMock()
    bulk_result = {}
    for sym, bars in data_by_symbol.items():
        df = pd.DataFrame([{'date': d, 'open': o, 'high': h, 'low': l, 'close': c}
                          for d, o, h, l, c in bars])
        bulk_result[sym] = df
    store.load_symbols_bulk.return_value = bulk_result
    return store


def _make_prediction(symbol, entry, stop, target, score=5.0, ml_prob=0.5):
    """Build a prediction dict in the format _evaluate_candidates expects."""
    return {
        'symbol': symbol,
        'baseline_score': score,
        'baseline_setup': {
            'entry_price': entry,
            'stop_loss': stop,
            'take_profit': target,
        },
        'baseline_ml_prob': ml_prob,
    }


# ---------------------------------------------------------------------------
# 1. Parity: single-exit
# ---------------------------------------------------------------------------

class TestParitySingleExit:
    """Run trades through both paths and assert identical results."""

    def _run_both_paths(self, predictions_flat, bars_by_symbol, hold_days=3):
        """
        Run vectorized path (via _vectorized_simulate_single_exit) and
        sequential path (via evaluate_prediction) and return both result lists.
        """
        config = BacktestConfig(hold_days=hold_days)

        # --- Vectorized path ---
        bt_vec = Backtester(config=config, database=None)
        bt_vec.hold_days = hold_days
        price_data = {}
        target_date = '2026-01-01'
        for sym, bars in bars_by_symbol.items():
            all_bars = [('2026-01-01', 100, 101, 99, 100)] + bars
            df = _make_future_df(all_bars)
            future = df[df['date'] > pd.Timestamp(target_date)].reset_index(drop=True)
            price_data[sym] = future

        vec_results = bt_vec._vectorized_simulate_single_exit(predictions_flat, price_data)

        # --- Sequential path ---
        seq_results = []
        for pred in predictions_flat:
            sym = pred['symbol']
            all_bars = [('2026-01-01', 100, 101, 99, 100)] + bars_by_symbol[sym]
            price_df = _make_future_df(all_bars)
            r = bt_vec.evaluate_prediction(pred, target_date, price_df=price_df)
            seq_results.append(r)

        return vec_results, seq_results

    def test_five_trade_parity(self):
        """5 trades with varied outcomes match between paths."""
        bars = {
            'SUCCESS': [  # Target hit
                ('2026-01-02', 100, 100.5, 99.5, 100),
                ('2026-01-03', 101, 110, 100, 108),
            ],
            'STOPPED': [  # Stop hit
                ('2026-01-02', 100, 100.5, 99.5, 100),
                ('2026-01-03', 97, 98, 93, 94),
            ],
            'TIME_PROFIT': [  # Time exit in profit
                ('2026-01-02', 100, 100.5, 99.5, 100),
                ('2026-01-03', 100.5, 101, 100, 100.5),
                ('2026-01-04', 100.5, 101, 100, 100.5),
                ('2026-01-05', 101, 101.5, 100.5, 101),
            ],
            'TIME_LOSS': [  # Time exit in loss
                ('2026-01-02', 100, 100.5, 99.5, 100),
                ('2026-01-03', 99.5, 100, 99, 99.5),
                ('2026-01-04', 99, 99.5, 98.5, 99),
                ('2026-01-05', 98.5, 99, 98, 98.5),
            ],
            'LIMIT_EXP': [  # Never enters
                ('2026-01-02', 102, 103, 101, 102),
                ('2026-01-03', 103, 104, 102, 103),
                ('2026-01-04', 103, 104, 102, 103),
                ('2026-01-05', 103, 104, 102, 103),
            ],
        }
        preds = [
            {'symbol': 'SUCCESS', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0},
            {'symbol': 'STOPPED', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0},
            {'symbol': 'TIME_PROFIT', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0},
            {'symbol': 'TIME_LOSS', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0},
            {'symbol': 'LIMIT_EXP', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0},
        ]

        vec_results, seq_results = self._run_both_paths(preds, bars)

        for vr, sr in zip(vec_results, seq_results):
            assert vr['symbol'] == sr['symbol'], f"Symbol mismatch: {vr['symbol']} != {sr['symbol']}"
            assert vr['status'] == sr['status'], f"{vr['symbol']}: status {vr['status']} != {sr['status']}"
            if vr['entry'] is not None:
                assert abs(vr['entry'] - sr['entry']) < 0.001, f"{vr['symbol']}: entry mismatch"
            if vr['exit_price'] is not None and sr['exit_price'] is not None:
                assert abs(vr['exit_price'] - sr['exit_price']) < 0.001, f"{vr['symbol']}: exit_price mismatch"


# ---------------------------------------------------------------------------
# 2. Parity: split-exit
# ---------------------------------------------------------------------------

class TestParitySplitExit:
    """Run split-exit trades through both paths and assert identical results."""

    def test_split_parity(self):
        """Split-exit full-profit scenario matches between paths."""
        target_date = '2026-01-01'
        config = BacktestConfig(hold_days=10)
        split_config = SplitExitConfig(mode='fixed_pct', t1_profit_pct=0.02)

        # Bars: enter day 1, T1 day 2, T2 day 3
        future_bars = [
            ('2026-01-02', 100, 100.5, 99.5, 100),
            ('2026-01-03', 101, 103, 101, 102.5),
            ('2026-01-04', 103, 109, 102.5, 108),
        ]
        all_bars = [('2026-01-01', 100, 101, 99, 100)] + future_bars

        pred = {'symbol': 'TEST', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0}

        # Sequential
        bt = Backtester(config=config, database=None)
        price_df = _make_future_df(all_bars)
        seq = bt.evaluate_prediction_split(pred, target_date, split_config, price_df=price_df)

        # Vectorized
        price_data = {
            'TEST': _make_future_df(future_bars),
        }
        vec_results = bt._vectorized_simulate_split_exit([pred], price_data, split_config)
        vec = vec_results[0]

        assert vec['status'] == seq['status']
        assert vec['tranche1_status'] == seq['tranche1_status']
        assert vec['tranche2_status'] == seq['tranche2_status']
        assert abs(vec['tranche1_exit_price'] - seq['tranche1_exit_price']) < 0.001
        assert abs(vec['tranche2_exit_price'] - seq['tranche2_exit_price']) < 0.001
        assert abs(vec['blended_pnl_pct'] - seq['blended_pnl_pct']) < 0.01


# ---------------------------------------------------------------------------
# 3. All single-exit statuses
# ---------------------------------------------------------------------------

class TestAllSingleExitStatuses:
    """One trade per terminal status."""

    @pytest.fixture
    def bt(self):
        return Backtester(config=BacktestConfig(hold_days=3), database=None)

    def test_success(self, bt):
        pred = [{'symbol': 'A', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0}]
        price_data = {'A': _make_future_df([
            ('2026-01-02', 100, 100.5, 99.5, 100),
            ('2026-01-03', 101, 110, 100, 108),
        ])}
        r = bt._vectorized_simulate_single_exit(pred, price_data)[0]
        assert r['status'] == 'success'
        assert r['exit_price'] == 108.0

    def test_stopped_out(self, bt):
        pred = [{'symbol': 'A', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0}]
        price_data = {'A': _make_future_df([
            ('2026-01-02', 100, 100.5, 99.5, 100),
            ('2026-01-03', 97, 98, 93, 94),
        ])}
        r = bt._vectorized_simulate_single_exit(pred, price_data)[0]
        assert r['status'] == 'stopped_out'
        assert r['exit_price'] == 95.0

    def test_limit_expired(self, bt):
        pred = [{'symbol': 'A', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0}]
        price_data = {'A': _make_future_df([
            ('2026-01-02', 102, 103, 101, 102),
            ('2026-01-03', 103, 104, 102, 103),
            ('2026-01-04', 103, 104, 102, 103),
            ('2026-01-05', 103, 104, 102, 103),
        ])}
        r = bt._vectorized_simulate_single_exit(pred, price_data)[0]
        assert r['status'] == 'limit_expired'

    def test_closed_profit(self, bt):
        pred = [{'symbol': 'A', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0}]
        price_data = {'A': _make_future_df([
            ('2026-01-02', 100, 100.5, 99.5, 100),
            ('2026-01-03', 100.5, 101, 100, 100.5),
            ('2026-01-04', 100.5, 101, 100, 100.5),
            ('2026-01-05', 101, 101.5, 100.5, 101),
        ])}
        r = bt._vectorized_simulate_single_exit(pred, price_data)[0]
        assert r['status'] == 'closed_profit'
        assert r['exit_price'] == 101.0

    def test_closed_loss(self, bt):
        pred = [{'symbol': 'A', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0}]
        price_data = {'A': _make_future_df([
            ('2026-01-02', 100, 100.5, 99.5, 100),
            ('2026-01-03', 99.5, 100, 99, 99.5),
            ('2026-01-04', 99, 99.5, 98.5, 99),
            ('2026-01-05', 98.5, 99, 98, 98.5),
        ])}
        r = bt._vectorized_simulate_single_exit(pred, price_data)[0]
        assert r['status'] == 'closed_loss'
        assert r['exit_price'] == 98.5

    def test_no_future_data(self, bt):
        pred = [{'symbol': 'A', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0}]
        price_data = {}  # no data
        r = bt._vectorized_simulate_single_exit(pred, price_data)[0]
        assert r['status'] == 'no_future_data'


# ---------------------------------------------------------------------------
# 4. Bulk load — verify DuckDB store is called
# ---------------------------------------------------------------------------

class TestBulkLoad:
    """Verify _bulk_load_price_data calls store.load_symbols_bulk()."""

    def test_single_query(self):
        bars_a = [('2026-01-02', 100, 101, 99, 100), ('2026-01-03', 101, 102, 100, 101)]
        bars_b = [('2026-01-02', 50, 51, 49, 50)]
        store = _make_store_with_data({'AAPL': bars_a, 'MSFT': bars_b})

        bt = Backtester(config=BacktestConfig(), database=None, store=store)
        result = bt._bulk_load_price_data(['AAPL', 'MSFT'], '2026-01-01')

        store.load_symbols_bulk.assert_called_once_with(['AAPL', 'MSFT'], start_date='2026-01-01')

        assert 'AAPL' in result
        assert 'MSFT' in result
        assert len(result['AAPL']) == 2
        assert len(result['MSFT']) == 1


# ---------------------------------------------------------------------------
# 5. Mixed data availability
# ---------------------------------------------------------------------------

class TestMixedDataAvailability:
    """Some symbols have data, some don't."""

    def test_partial_data(self):
        bars = [('2026-01-02', 100, 100.5, 99.5, 100), ('2026-01-03', 101, 110, 100, 108)]
        store = _make_store_with_data({'AAPL': bars})

        bt = Backtester(config=BacktestConfig(hold_days=3), database=None, store=store)
        price_data = bt._bulk_load_price_data(['AAPL', 'MSFT'], '2026-01-01')

        preds = [
            {'symbol': 'AAPL', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0},
            {'symbol': 'MSFT', 'entry_price': 50.0, 'stop_loss': 47.0, 'take_profit': 55.0},
        ]
        results = bt._vectorized_simulate_single_exit(preds, price_data)

        assert results[0]['status'] == 'success'
        assert results[1]['status'] == 'no_future_data'


# ---------------------------------------------------------------------------
# 6. Intraday stop on entry bar
# ---------------------------------------------------------------------------

class TestIntradayStopOnEntry:
    """Stop triggers on the same bar as entry, has priority over target."""

    def test_stop_before_target(self):
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)
        # Wide bar: low below stop AND high above target
        # Stop should take priority per the original backtester logic
        pred = [{'symbol': 'A', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0}]
        price_data = {'A': _make_future_df([
            ('2026-01-02', 100, 110, 93, 100),  # low=93 < stop=95, high=110 > target=108
        ])}
        r = bt._vectorized_simulate_single_exit(pred, price_data)[0]
        assert r['status'] == 'stopped_out'
        assert r['exit_price'] == 95.0

    def test_gap_down_entry_intraday_stop(self):
        """Open gaps below entry; stop also hit on entry bar."""
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)
        pred = [{'symbol': 'A', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0}]
        price_data = {'A': _make_future_df([
            ('2026-01-02', 94, 96, 93, 95),  # open=94 < entry=100, low=93 < stop=95
        ])}
        r = bt._vectorized_simulate_single_exit(pred, price_data)[0]
        assert r['status'] == 'stopped_out'
        assert r['entry'] == 94.0  # slippage: open was below entry
        assert r['exit_price'] == 94.0  # open < stop, so exit at open


# ---------------------------------------------------------------------------
# 7. Mark-to-market
# ---------------------------------------------------------------------------

class TestMarkToMarket:
    """Trade still active when data runs out -> exit at last close."""

    def test_mark_to_market_profit(self):
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)
        pred = [{'symbol': 'A', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0}]
        # Only 2 days of data, hold_days=10, no stop/target hit
        price_data = {'A': _make_future_df([
            ('2026-01-02', 100, 100.5, 99.5, 100),
            ('2026-01-03', 100.5, 101, 100, 101),
        ])}
        r = bt._vectorized_simulate_single_exit(pred, price_data)[0]
        assert r['status'] == 'closed_profit'
        assert r['exit_price'] == 101.0

    def test_mark_to_market_loss(self):
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)
        pred = [{'symbol': 'A', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0}]
        price_data = {'A': _make_future_df([
            ('2026-01-02', 100, 100.5, 99.5, 100),
            ('2026-01-03', 99.5, 100, 99, 99),
        ])}
        r = bt._vectorized_simulate_single_exit(pred, price_data)[0]
        assert r['status'] == 'closed_loss'
        assert r['exit_price'] == 99.0


# ---------------------------------------------------------------------------
# 8. Empty predictions
# ---------------------------------------------------------------------------

class TestEmptyPredictions:
    def test_empty_single(self):
        bt = Backtester(config=BacktestConfig(), database=None)
        assert bt._vectorized_simulate_single_exit([], {}) == []

    def test_empty_split(self):
        bt = Backtester(config=BacktestConfig(), database=None)
        sc = SplitExitConfig()
        assert bt._vectorized_simulate_split_exit([], {}, sc) == []


# ---------------------------------------------------------------------------
# 9. No store fallback
# ---------------------------------------------------------------------------

class TestNoStoreFallback:
    """store=None should route to sequential path in _evaluate_candidates."""

    def test_sequential_path_used(self):
        bt = Backtester(config=BacktestConfig(), database=None)
        assert bt.store is None

        pred = _make_prediction('TEST', 100, 95, 108)
        options = BacktestOptions(strategy="baseline")

        with patch.object(bt, 'evaluate_prediction', return_value={'symbol': 'TEST', 'status': 'success', 'entry': 100, 'exit_price': 108, 'exit_date': None, 'days_held': 2}) as mock_eval, \
             patch.object(bt, '_evaluate_candidates_vectorized') as mock_vec:
            bt._evaluate_candidates([pred], '2026-01-01', options)
            mock_eval.assert_called_once()
            mock_vec.assert_not_called()

    def test_vectorized_path_used_with_store(self):
        store = MagicMock()
        bt = Backtester(config=BacktestConfig(), database=None, store=store)

        pred = _make_prediction('TEST', 100, 95, 108)
        options = BacktestOptions(strategy="baseline")

        with patch.object(bt, '_evaluate_candidates_vectorized', return_value=[]) as mock_vec, \
             patch.object(bt, 'evaluate_prediction') as mock_seq:
            bt._evaluate_candidates([pred], '2026-01-01', options)
            mock_vec.assert_called_once()
            mock_seq.assert_not_called()


# ---------------------------------------------------------------------------
# 10. Split-exit scenarios
# ---------------------------------------------------------------------------

class TestSplitExitVectorized:
    """Key split-exit scenarios via vectorized path."""

    def test_full_profit(self):
        """Both T1 and T2 hit."""
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)
        sc = SplitExitConfig(mode='fixed_pct', t1_profit_pct=0.02)
        pred = [{'symbol': 'A', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0}]
        price_data = {'A': _make_future_df([
            ('2026-01-02', 100, 100.5, 99.5, 100),
            ('2026-01-03', 101, 103, 101, 102.5),     # T1 hit (102)
            ('2026-01-04', 103, 109, 102.5, 108),       # T2 hit (108)
        ])}
        r = bt._vectorized_simulate_split_exit(pred, price_data, sc)[0]
        assert r['status'] == 'split_full_profit'
        assert r['tranche1_status'] == 'profit'
        assert r['tranche2_status'] == 'profit'
        assert abs(r['blended_pnl_pct'] - 5.0) < 0.01

    def test_partial_profit(self):
        """T1 hits, T2 stopped at entry-2%."""
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)
        sc = SplitExitConfig(mode='fixed_pct', t1_profit_pct=0.02)
        pred = [{'symbol': 'A', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0}]
        price_data = {'A': _make_future_df([
            ('2026-01-02', 100, 100.5, 99.5, 100),
            ('2026-01-03', 101, 103, 101, 102.5),     # T1 hit (102)
            ('2026-01-04', 101, 102, 100, 101),        # T2 still active
            ('2026-01-05', 99, 100, 97, 98),           # T2 stopped (low < 98)
        ])}
        r = bt._vectorized_simulate_split_exit(pred, price_data, sc)[0]
        assert r['status'] == 'split_partial_profit'
        assert r['tranche1_status'] == 'profit'
        assert r['tranche2_status'] == 'stopped'
        assert r['tranche2_exit_price'] == 98.0
        assert abs(r['blended_pnl_pct'] - 0.0) < 0.01

    def test_both_stopped(self):
        """Both tranches stopped at original stop."""
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)
        sc = SplitExitConfig(mode='fixed_pct', t1_profit_pct=0.02)
        pred = [{'symbol': 'A', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0}]
        price_data = {'A': _make_future_df([
            ('2026-01-02', 100, 100.5, 99.5, 100),
            ('2026-01-03', 98, 98.5, 94, 94.5),       # stop hit: low=94 < 95
        ])}
        r = bt._vectorized_simulate_split_exit(pred, price_data, sc)[0]
        assert r['status'] == 'stopped_out'
        assert r['tranche1_status'] == 'stopped'
        assert r['tranche2_status'] == 'stopped'
        assert abs(r['blended_pnl_pct'] - (-5.0)) < 0.01

    def test_split_no_future_data(self):
        """Symbol with no data returns no_future_data."""
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)
        sc = SplitExitConfig(mode='fixed_pct', t1_profit_pct=0.02)
        pred = [{'symbol': 'A', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0}]
        r = bt._vectorized_simulate_split_exit(pred, {}, sc)[0]
        assert r['status'] == 'no_future_data'
        assert r['exit_mode'] == 'split_exit'

    def test_split_intraday_stop_on_entry(self):
        """Both tranches stopped on the entry bar."""
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)
        sc = SplitExitConfig(mode='fixed_pct', t1_profit_pct=0.02)
        pred = [{'symbol': 'A', 'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 108.0}]
        price_data = {'A': _make_future_df([
            ('2026-01-02', 100, 101, 94, 96),  # entry at 100, low=94 < stop=95
        ])}
        r = bt._vectorized_simulate_split_exit(pred, price_data, sc)[0]
        assert r['status'] == 'stopped_out'
        assert r['tranche1_exit_price'] == 95.0
        assert r['tranche2_exit_price'] == 95.0


# ---------------------------------------------------------------------------
# Integration: _evaluate_candidates_vectorized end-to-end
# ---------------------------------------------------------------------------

class TestEvaluateCandidatesVectorized:
    """End-to-end test of _evaluate_candidates_vectorized."""

    def test_end_to_end(self):
        bars_data = {'TEST': [
            ('2026-01-01', 100, 101, 99, 100),
            ('2026-01-02', 100, 100.5, 99.5, 100),
            ('2026-01-03', 101, 110, 100, 108),
        ]}
        store = _make_store_with_data(bars_data)

        bt = Backtester(config=BacktestConfig(hold_days=3), database=None, store=store)
        pred = _make_prediction('TEST', 100, 95, 108)
        options = BacktestOptions(strategy="baseline")

        results = bt._evaluate_candidates_vectorized([pred], '2026-01-01', options)
        assert len(results) == 1
        assert results[0]['status'] == 'success'
        assert results[0]['exit_price'] == 108.0
        assert results[0]['baseline_score'] == 5.0
