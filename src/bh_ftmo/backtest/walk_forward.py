"""Walk-forward window enumeration for Phase 3 backtest evaluation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from bh_ftmo.data.fx_time_utils import prior_forex_day


@dataclass(frozen=True)
class Fold:
    """One Phase 3 walk-forward fold with disjoint IS and OOS windows."""

    is_start: date
    is_end: date
    oos_start: date
    oos_end: date


def fold_windows(
    start: date,
    end: date,
    is_months: int = 18,
    oos_months: int = 6,
    roll_months: int = 6,
) -> list[Fold]:
    """Generate Phase 3 walk-forward folds spanning ``[start, end]``.

    Fold anchors advance by ``roll_months``. Boundary dates are snapped away from
    weekends and Christmas so OOS cohorts never start on an obvious non-trading
    boundary.
    """

    if min(is_months, oos_months, roll_months) <= 0:
        raise ValueError('fold month parameters must be positive')
    if start >= end:
        return []

    folds: list[Fold] = []
    anchor = start
    total_months = is_months + oos_months
    while _add_months(anchor, total_months) <= end:
        is_start = _snap_boundary_backward(anchor)
        oos_start = _snap_boundary_forward(_add_months(anchor, is_months))
        is_end = prior_forex_day(oos_start)
        oos_end = _snap_boundary_backward(_add_months(anchor, total_months))
        if is_start < is_end < oos_start <= oos_end:
            folds.append(Fold(is_start=is_start, is_end=is_end, oos_start=oos_start, oos_end=oos_end))
        anchor = _add_months(anchor, roll_months)
    return folds


def non_overlapping_starts(
    fold: Fold,
    challenge_window_days: int,
) -> list[date]:
    """Enumerate non-overlapping challenge start dates inside one fold's OOS window."""

    if challenge_window_days <= 0:
        raise ValueError('challenge_window_days must be positive')

    starts: list[date] = []
    current = _next_trading_day_on_or_after(fold.oos_start)
    while current + timedelta(days=challenge_window_days) <= fold.oos_end:
        starts.append(current)
        current = _next_trading_day_on_or_after(current + timedelta(days=challenge_window_days))
    return starts


def assert_no_oos_contamination(
    fold: Fold,
    bars_4h: dict[str, pd.DataFrame],
    metric_fn: Callable[[dict[str, pd.DataFrame]], float],
) -> None:
    """Assert that shuffling OOS rows cannot change an IS-only metric."""

    restricted = {symbol: _restrict_to_fold(frame, fold) for symbol, frame in bars_4h.items()}
    baseline = float(metric_fn(restricted))
    shuffled = {symbol: _shuffle_oos_rows(frame, fold) for symbol, frame in restricted.items()}
    candidate = float(metric_fn(shuffled))
    if not np.isclose(baseline, candidate, atol=1e-12, rtol=0.0, equal_nan=True):
        raise AssertionError(
            f'OOS contamination detected: IS metric changed from {baseline!r} to {candidate!r}'
        )


def _add_months(value: date, months: int) -> date:
    return (pd.Timestamp(value) + pd.DateOffset(months=months)).date()


def _snap_boundary_backward(value: date) -> date:
    if value.weekday() >= 5 or (value.month, value.day) == (12, 25):
        return prior_forex_day(value)
    return value


def _snap_boundary_forward(value: date) -> date:
    if (value.month, value.day) == (12, 25):
        value += timedelta(days=1)
    return _next_trading_day_on_or_after(value)


def _next_trading_day_on_or_after(value: date) -> date:
    current = value
    while current.weekday() >= 5:
        current += timedelta(days=1)
    return current


def _timestamps(frame: pd.DataFrame) -> pd.Series:
    if 'timestamp' in frame.columns:
        return pd.to_datetime(frame['timestamp'])
    return pd.Series(pd.to_datetime(frame.index), index=frame.index)


def _restrict_to_fold(frame: pd.DataFrame, fold: Fold) -> pd.DataFrame:
    timestamps = _timestamps(frame)
    mask = (timestamps.dt.date >= fold.is_start) & (timestamps.dt.date <= fold.oos_end)
    restricted = frame.loc[mask].copy()
    if 'timestamp' in restricted.columns:
        restricted['timestamp'] = pd.to_datetime(restricted['timestamp'])
    return restricted


def _shuffle_oos_rows(frame: pd.DataFrame, fold: Fold) -> pd.DataFrame:
    timestamps = _timestamps(frame)
    oos_mask = (timestamps.dt.date >= fold.oos_start) & (timestamps.dt.date <= fold.oos_end)
    if int(oos_mask.sum()) <= 1:
        return frame.copy()

    shuffled = frame.copy()
    data_columns = [column for column in shuffled.columns if column != 'timestamp']
    oos_values = shuffled.loc[oos_mask, data_columns]
    permuted = oos_values.sample(frac=1.0, random_state=0).to_numpy()
    shuffled.loc[oos_mask, data_columns] = permuted
    return shuffled
