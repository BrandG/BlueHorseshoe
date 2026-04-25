"""Tests for Phase 3.4 walk-forward helpers."""

from __future__ import annotations

# pylint: disable=missing-function-docstring

from datetime import date

import pandas as pd
import pytest

from bh_ftmo.backtest.walk_forward import Fold, assert_no_oos_contamination, fold_windows, non_overlapping_starts


def _bars() -> dict[str, pd.DataFrame]:
    index = pd.date_range('2020-01-01', periods=12, freq='1D')
    return {
        'EUR_USD': pd.DataFrame(
            {
                'timestamp': index,
                'close': [1.10, 1.11, 1.12, 1.13, 1.14, 1.15, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0],
            }
        )
    }


def test_fold_windows_default_10y_yields_17_folds():
    folds = fold_windows(date(2016, 1, 1), date(2026, 1, 1))
    assert len(folds) == 17


def test_fold_windows_no_gaps_or_overlaps_in_is_oos_within_fold():
    for fold in fold_windows(date(2016, 1, 1), date(2026, 1, 1)):
        assert fold.is_start < fold.is_end < fold.oos_start <= fold.oos_end


def test_fold_windows_roll_advances_by_roll_months():
    folds = fold_windows(date(2016, 1, 1), date(2026, 1, 1))
    first = folds[0].oos_start
    second = folds[1].oos_start
    month_delta = (second.year - first.year) * 12 + (second.month - first.month)
    assert month_delta == 6


def test_fold_windows_snaps_edges_to_trading_days():
    folds = fold_windows(date(2026, 12, 25), date(2029, 12, 25))
    assert folds[0].is_start == date(2026, 12, 24)


def test_non_overlapping_starts_14_day_window_yields_expected_count():
    fold = Fold(is_start=date(2025, 1, 1), is_end=date(2025, 6, 30), oos_start=date(2026, 1, 1), oos_end=date(2026, 7, 1))
    assert len(non_overlapping_starts(fold, 14)) == 12


def test_non_overlapping_starts_30_day_window_yields_expected_count():
    fold = Fold(is_start=date(2025, 1, 1), is_end=date(2025, 6, 30), oos_start=date(2026, 1, 1), oos_end=date(2026, 7, 1))
    assert len(non_overlapping_starts(fold, 30)) == 5


def test_non_overlapping_starts_each_fits_inside_oos_window():
    fold = Fold(is_start=date(2025, 1, 1), is_end=date(2025, 6, 30), oos_start=date(2026, 1, 1), oos_end=date(2026, 7, 1))
    starts = non_overlapping_starts(fold, 14)
    assert all(start >= fold.oos_start for start in starts)
    assert all(start.fromordinal(start.toordinal() + 14) <= fold.oos_end for start in starts)


def test_assert_no_oos_contamination_passes_for_pure_indicator():
    fold = Fold(is_start=date(2020, 1, 1), is_end=date(2020, 1, 6), oos_start=date(2020, 1, 7), oos_end=date(2020, 1, 12))
    bars = _bars()

    def pure_metric(frames: dict[str, pd.DataFrame]) -> float:
        frame = frames['EUR_USD']
        return float(frame.loc[frame['timestamp'].dt.date <= fold.is_end, 'close'].mean())

    assert_no_oos_contamination(fold, bars, pure_metric)


def test_assert_no_oos_contamination_fails_for_leaky_indicator():
    fold = Fold(is_start=date(2020, 1, 1), is_end=date(2020, 1, 6), oos_start=date(2020, 1, 7), oos_end=date(2020, 1, 12))
    bars = _bars()

    def leaky_metric(frames: dict[str, pd.DataFrame]) -> float:
        frame = frames['EUR_USD'].copy()
        next_close = frame['close'].shift(-1)
        return float(next_close.loc[frame['timestamp'].dt.date <= fold.is_end].mean())

    with pytest.raises(AssertionError, match='OOS contamination detected'):
        assert_no_oos_contamination(fold, bars, leaky_metric)
