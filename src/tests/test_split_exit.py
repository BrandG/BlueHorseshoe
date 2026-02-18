"""
Tests for split-exit (two-tranche) backtester.

Covers:
- Plan A (fixed_pct): T1 at entry+2%, T2 rides to original take_profit
- Plan B (atr_tiered): T1 at entry+1xATR, T2 at entry+2xATR
- Edge cases: same-bar T1+T2, time exits, no entry, backward compat
"""

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

from bluehorseshoe.analysis.backtest import (
    Backtester, BacktestConfig, SplitExitConfig, SplitTradeState,
)


def _make_future_data(bars):
    """
    Build a DataFrame from a list of (date, open, high, low, close) tuples.
    Resets index to 0..N-1 so iterrows() matches the backtester's expectations.
    """
    rows = []
    for date_str, o, h, l, c in bars:
        rows.append({'date': pd.Timestamp(date_str), 'open': o, 'high': h, 'low': l, 'close': c})
    return pd.DataFrame(rows)


def _make_price_data(bars):
    """Wrap bars into the dict format load_historical_data returns."""
    df = _make_future_data(bars)
    return {'days': df.to_dict('records')}


def _patch_load(bars):
    """Return a patcher that makes load_historical_data return the given bars."""
    return patch(
        'bluehorseshoe.analysis.backtest.load_historical_data',
        return_value=_make_price_data(bars),
    )


class TestPlanAFixedPct:
    """Plan A: T1 exits at entry+2%, T2 rides to original take_profit."""

    def test_full_success(self):
        """Both T1 (+2%) and T2 (take_profit) hit."""
        # Entry at 100, stop at 95, take_profit at 108
        # T1 target = 100 * 1.02 = 102
        # Day 1: enters at 100
        # Day 2: hits 102 (T1 exits), continues
        # Day 3: hits 108 (T2 exits)
        bars = [
            ('2026-01-01', 100, 101, 99, 100.5),  # target_date (skipped)
            ('2026-01-02', 100, 101, 99.5, 100.5),  # entry day: low=99.5 <= 100
            ('2026-01-03', 101, 103, 100.5, 102),    # T1 hit: high=103 >= 102
            ('2026-01-04', 103, 109, 102.5, 108),    # T2 hit: high=109 >= 108, low > T2 stop (102)
        ]
        prediction = {
            'symbol': 'TEST',
            'entry_price': 100.0,
            'stop_loss': 95.0,
            'take_profit': 108.0,
        }
        split_config = SplitExitConfig(mode='fixed_pct', t1_profit_pct=0.02)
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)

        with _patch_load(bars):
            result = bt.evaluate_prediction_split(prediction, '2026-01-01', split_config)

        assert result['status'] == 'split_full_profit'
        assert result['tranche1_status'] == 'profit'
        assert result['tranche2_status'] == 'profit'
        assert result['tranche1_exit_price'] == 102.0
        assert result['tranche2_exit_price'] == 108.0
        # Blended: 0.5 * 2% + 0.5 * 8% = 5%
        assert abs(result['blended_pnl_pct'] - 5.0) < 0.01

    def test_partial_profit_t2_stopped_at_t1_level(self):
        """T1 hits +2%, T2 stopped at T1 level (breakeven+). Net PnL = 2%."""
        # T1 target = 102, T2 target = 108, original stop = 95
        # After T1 exits, T2 stop moves to 102
        bars = [
            ('2026-01-01', 100, 101, 99, 100),
            ('2026-01-02', 100, 101, 99, 100),        # entry at 100
            ('2026-01-03', 101, 103, 101, 102.5),      # T1 hit at 102
            ('2026-01-04', 103, 104, 101.5, 103),      # T2 still active
            ('2026-01-05', 102, 102.5, 101, 101.5),    # T2 stopped: low=101 < 102
        ]
        prediction = {
            'symbol': 'TEST',
            'entry_price': 100.0,
            'stop_loss': 95.0,
            'take_profit': 108.0,
        }
        split_config = SplitExitConfig(mode='fixed_pct', t1_profit_pct=0.02)
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)

        with _patch_load(bars):
            result = bt.evaluate_prediction_split(prediction, '2026-01-01', split_config)

        assert result['status'] == 'split_partial_profit'
        assert result['tranche1_status'] == 'profit'
        assert result['tranche2_status'] == 'stopped'
        assert result['tranche2_exit_price'] == 102.0  # Stopped at T1 level
        # Blended: 0.5 * 2% + 0.5 * 2% = 2%
        assert abs(result['blended_pnl_pct'] - 2.0) < 0.01

    def test_full_stop(self):
        """Both tranches stopped at original stop."""
        bars = [
            ('2026-01-01', 100, 101, 99, 100),
            ('2026-01-02', 100, 100.5, 99.5, 100),   # entry at 100
            ('2026-01-03', 98, 98.5, 94, 94.5),       # stop hit: low=94 < 95
        ]
        prediction = {
            'symbol': 'TEST',
            'entry_price': 100.0,
            'stop_loss': 95.0,
            'take_profit': 108.0,
        }
        split_config = SplitExitConfig(mode='fixed_pct', t1_profit_pct=0.02)
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)

        with _patch_load(bars):
            result = bt.evaluate_prediction_split(prediction, '2026-01-01', split_config)

        assert result['status'] == 'stopped_out'
        assert result['tranche1_status'] == 'stopped'
        assert result['tranche2_status'] == 'stopped'
        assert result['tranche1_exit_price'] == 95.0
        assert result['tranche2_exit_price'] == 95.0
        # Blended: 0.5 * (-5%) + 0.5 * (-5%) = -5%
        assert abs(result['blended_pnl_pct'] - (-5.0)) < 0.01

    def test_time_exit_both(self):
        """Hold days expire with both tranches still active."""
        bars = [
            ('2026-01-01', 100, 101, 99, 100),
            ('2026-01-02', 100, 100.5, 99.5, 100),   # entry at 100 (day 0)
            ('2026-01-03', 100, 101, 99.5, 100.5),    # day 1
            ('2026-01-04', 100.5, 101, 99.5, 101),    # day 2
            ('2026-01-05', 101, 101.5, 100, 101),     # day 3 = hold_days -> time exit
        ]
        prediction = {
            'symbol': 'TEST',
            'entry_price': 100.0,
            'stop_loss': 95.0,
            'take_profit': 108.0,
        }
        split_config = SplitExitConfig(mode='fixed_pct', t1_profit_pct=0.02)
        bt = Backtester(config=BacktestConfig(hold_days=3), database=None)

        with _patch_load(bars):
            result = bt.evaluate_prediction_split(prediction, '2026-01-01', split_config)

        assert result['tranche1_status'] == 'time_exit'
        assert result['tranche2_status'] == 'time_exit'
        # Both exit at close of last bar (101)
        assert result['tranche1_exit_price'] == 101.0
        assert result['tranche2_exit_price'] == 101.0

    def test_t1_hit_t2_time_exit(self):
        """T1 hits target, T2 runs out of time."""
        bars = [
            ('2026-01-01', 100, 101, 99, 100),
            ('2026-01-02', 100, 100.5, 99, 100),      # entry at 100 (idx 0)
            ('2026-01-03', 101, 103, 101, 102.5),      # T1 hit at 102 (idx 1)
            ('2026-01-04', 102.5, 103, 102.5, 102.5),  # idx 2, low > T2 stop (102)
            ('2026-01-05', 102.5, 103.5, 102.5, 103),  # idx 3 = hold_days -> T2 time exit
        ]
        prediction = {
            'symbol': 'TEST',
            'entry_price': 100.0,
            'stop_loss': 95.0,
            'take_profit': 108.0,
        }
        split_config = SplitExitConfig(mode='fixed_pct', t1_profit_pct=0.02)
        bt = Backtester(config=BacktestConfig(hold_days=3), database=None)

        with _patch_load(bars):
            result = bt.evaluate_prediction_split(prediction, '2026-01-01', split_config)

        assert result['tranche1_status'] == 'profit'
        assert result['tranche2_status'] == 'time_exit'
        assert result['tranche1_exit_price'] == 102.0
        assert result['tranche2_exit_price'] == 103.0  # close of time exit bar
        # Blended: 0.5 * 2% + 0.5 * 3% = 2.5%
        assert abs(result['blended_pnl_pct'] - 2.5) < 0.01

    def test_intraday_entry_and_t1_same_bar(self):
        """Entry and T1 hit on the same bar (wide range)."""
        # Entry at 100, T1 = 102. Bar: open=99 (gap down entry), high=103 (T1 hit)
        bars = [
            ('2026-01-01', 100, 101, 99, 100),
            ('2026-01-02', 99, 103, 98, 102),    # entry at 99 (open gap), T1=102 hit at high=103
            ('2026-01-03', 102, 109, 101, 108),   # T2 hit
        ]
        prediction = {
            'symbol': 'TEST',
            'entry_price': 100.0,
            'stop_loss': 95.0,
            'take_profit': 108.0,
        }
        # T1 = 100 * 1.02 = 102
        split_config = SplitExitConfig(mode='fixed_pct', t1_profit_pct=0.02)
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)

        with _patch_load(bars):
            result = bt.evaluate_prediction_split(prediction, '2026-01-01', split_config)

        # Entry should be at open=99 (gap below entry_price)
        assert result['entry'] == 99.0
        assert result['tranche1_status'] == 'profit'
        # T1 exit at target 102 (high >= 102)
        assert result['tranche1_exit_price'] == 102.0


class TestPlanBATRTiered:
    """Plan B: T1 at entry+1xATR, T2 at entry+2xATR."""

    def test_atr_targets_from_prediction(self):
        """ATR passed in prediction dict sets correct targets."""
        # Entry=100, ATR=3, T1=103, T2=106
        bars = [
            ('2026-01-01', 100, 101, 99, 100),
            ('2026-01-02', 100, 100.5, 99, 100),    # entry at 100
            ('2026-01-03', 101, 104, 101, 103.5),    # T1 hit: high=104 >= 103
            ('2026-01-04', 104, 107, 103.5, 106),    # T2 hit: high=107 >= 106, low > T2 stop (103)
        ]
        prediction = {
            'symbol': 'TEST',
            'entry_price': 100.0,
            'stop_loss': 94.0,
            'take_profit': 110.0,
            'atr': 3.0,
        }
        split_config = SplitExitConfig(mode='atr_tiered', t1_atr_multiple=1.0, t2_atr_multiple=2.0)
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)

        with _patch_load(bars):
            result = bt.evaluate_prediction_split(prediction, '2026-01-01', split_config)

        assert result['status'] == 'split_full_profit'
        assert result['tranche1_exit_price'] == 103.0  # entry + 1*ATR
        assert result['tranche2_exit_price'] == 106.0  # entry + 2*ATR
        # Blended: 0.5 * 3% + 0.5 * 6% = 4.5%
        assert abs(result['blended_pnl_pct'] - 4.5) < 0.01

    def test_atr_computed_from_history(self):
        """When ATR not in prediction, compute from pre-trade data."""
        # Pre-trade bars + future bars. ATR will be computed from high-low range.
        pre_bars = []
        for i in range(14):
            d = f'2025-12-{15+i:02d}'
            # high-low range of 4 => ATR ~ 4
            pre_bars.append((d, 98, 102, 98, 100))
        future_bars = [
            ('2026-01-02', 100, 100.5, 99, 100),      # entry at 100
            ('2026-01-03', 101, 105, 100.5, 104),       # T1 at 104 = entry + 1*4
            ('2026-01-04', 105, 109, 104, 108),          # T2 at 108 = entry + 2*4
        ]
        all_bars = pre_bars + [('2026-01-01', 100, 101, 99, 100)] + future_bars

        prediction = {
            'symbol': 'TEST',
            'entry_price': 100.0,
            'stop_loss': 94.0,
            'take_profit': 112.0,
            # No 'atr' key - should be computed
        }
        split_config = SplitExitConfig(mode='atr_tiered', t1_atr_multiple=1.0, t2_atr_multiple=2.0)
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)

        with _patch_load(all_bars):
            result = bt.evaluate_prediction_split(prediction, '2026-01-01', split_config)

        # ATR should be computed as ~4 (high-low range of pre-trade bars)
        assert result['tranche1_status'] == 'profit'
        assert result['tranche2_status'] == 'profit'
        assert result['status'] == 'split_full_profit'


class TestBackwardCompat:
    """Ensure existing evaluate_prediction is unchanged."""

    def test_single_exit_unchanged(self):
        """Original evaluate_prediction still works without split_config."""
        bars = [
            ('2026-01-01', 100, 101, 99, 100),
            ('2026-01-02', 100, 100.5, 99, 100),   # entry at 100
            ('2026-01-03', 101, 109, 100, 108),      # take_profit hit at 108
        ]
        prediction = {
            'symbol': 'TEST',
            'entry_price': 100.0,
            'stop_loss': 95.0,
            'take_profit': 108.0,
        }
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)

        with _patch_load(bars):
            result = bt.evaluate_prediction(prediction, '2026-01-01')

        assert result['status'] == 'success'
        assert result['exit_price'] == 108.0
        assert 'exit_mode' not in result  # No split marker


class TestSyntheticExitPrice:
    """Verify synthetic exit_price matches blended_pnl_pct."""

    def test_synthetic_price_consistency(self):
        """((exit_price / entry) - 1) * 100 should equal blended_pnl_pct."""
        bars = [
            ('2026-01-01', 100, 101, 99, 100),
            ('2026-01-02', 100, 101, 99, 100),        # entry at 100
            ('2026-01-03', 101, 103, 101, 102.5),      # T1 hit at 102
            ('2026-01-04', 103, 104, 101.5, 103),
            ('2026-01-05', 102, 102.5, 101, 101.5),    # T2 stopped at 102
        ]
        prediction = {
            'symbol': 'TEST',
            'entry_price': 100.0,
            'stop_loss': 95.0,
            'take_profit': 108.0,
        }
        split_config = SplitExitConfig(mode='fixed_pct', t1_profit_pct=0.02)
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)

        with _patch_load(bars):
            result = bt.evaluate_prediction_split(prediction, '2026-01-01', split_config)

        # Verify synthetic exit_price encodes blended P&L
        computed_pnl = ((result['exit_price'] / result['entry']) - 1) * 100
        assert abs(computed_pnl - result['blended_pnl_pct']) < 0.001


class TestNoEntry:
    """Test when price never reaches entry level."""

    def test_no_entry_within_hold(self):
        """If entry is never triggered, result should be no_entry."""
        bars = [
            ('2026-01-01', 100, 101, 99, 100),
            ('2026-01-02', 102, 103, 101, 102),   # low=101 > entry=100? No. low=101 > 100 is False
            ('2026-01-03', 103, 104, 102, 103),   # low=102 > 100? No.
        ]
        # Actually low=101 <= 100 is False (101 > 100), so no entry
        # Let's make it clearer
        bars = [
            ('2026-01-01', 100, 101, 99, 100),
            ('2026-01-02', 102, 103, 101, 102),   # low=101 > entry=99
            ('2026-01-03', 103, 104, 102, 103),
            ('2026-01-04', 103, 104, 102, 103),
            ('2026-01-05', 103, 104, 102, 103),
        ]
        prediction = {
            'symbol': 'TEST',
            'entry_price': 99.0,   # Entry at 99
            'stop_loss': 95.0,
            'take_profit': 108.0,
        }
        split_config = SplitExitConfig(mode='fixed_pct', t1_profit_pct=0.02)
        bt = Backtester(config=BacktestConfig(hold_days=3), database=None)

        with _patch_load(bars):
            result = bt.evaluate_prediction_split(prediction, '2026-01-01', split_config)

        assert result['status'] == 'no_entry' or result.get('entry') is None


class TestIntradayStopOnEntry:
    """Stop loss triggered on the same bar as entry."""

    def test_intraday_stop_on_entry_bar(self):
        """Entry and stop hit on same bar."""
        # Entry at 100, stop at 95
        # Bar: open=100, low=94 (below stop), high=101
        bars = [
            ('2026-01-01', 100, 101, 99, 100),
            ('2026-01-02', 100, 101, 94, 96),   # entry at 100, then low=94 < stop=95
        ]
        prediction = {
            'symbol': 'TEST',
            'entry_price': 100.0,
            'stop_loss': 95.0,
            'take_profit': 108.0,
        }
        split_config = SplitExitConfig(mode='fixed_pct', t1_profit_pct=0.02)
        bt = Backtester(config=BacktestConfig(hold_days=10), database=None)

        with _patch_load(bars):
            result = bt.evaluate_prediction_split(prediction, '2026-01-01', split_config)

        assert result['status'] == 'stopped_out'
        assert result['tranche1_status'] == 'stopped'
        assert result['tranche2_status'] == 'stopped'
        assert result['tranche1_exit_price'] == 95.0
        assert result['tranche2_exit_price'] == 95.0
