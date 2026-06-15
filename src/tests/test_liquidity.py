"""Tests for the shared equity liquidity helpers."""
import numpy as np
import pandas as pd

from bluehorseshoe.analysis.liquidity import (
    trailing_dollar_volume,
    dollar_volume_from_df,
    passes_dollar_volume,
    is_dead_series,
    latest_bar_untraded,
)


def _frame(close, volume):
    return pd.DataFrame({"close": close, "volume": volume})


def test_trailing_dollar_volume_basic():
    # 25 bars at $10 x 1,000,000 shares = $10M/day
    dv = trailing_dollar_volume([10.0] * 25, [1_000_000] * 25)
    assert dv == 1e7


def test_trailing_dollar_volume_uses_last_window_only():
    close = [1.0] * 20 + [100.0] * 20   # recent bars are the pricey ones
    volume = [1_000] * 20 + [1_000] * 20
    dv = trailing_dollar_volume(close, volume, window=20)
    assert dv == 100.0 * 1_000  # only the trailing 20 bars count


def test_trailing_dollar_volume_nan_safe():
    dv = trailing_dollar_volume([np.nan, 10.0, 10.0], [np.nan, 100, 100], window=20)
    assert dv == 1000.0  # NaN bar ignored by nanmean


def test_empty_series_returns_zero():
    assert trailing_dollar_volume([], []) == 0.0
    assert dollar_volume_from_df(pd.DataFrame()) == 0.0
    assert dollar_volume_from_df(None) == 0.0


def test_passes_dollar_volume_floor():
    liquid = _frame([30.0] * 20, [500_000] * 20)      # $15M/day
    thin = _frame([18.0] * 20, [478] * 20)            # ~$8.6k/day (DGICB-like)
    assert passes_dollar_volume(liquid, 5_000_000) is True
    assert passes_dollar_volume(thin, 5_000_000) is False


def test_is_dead_series_detects_zero_volume():
    # ATCOL/LANDM-like: frozen price, zero volume carried forward
    dead = _frame([25.32] * 20, [0] * 20)
    assert is_dead_series(dead) is True


def test_is_dead_series_thin_but_alive_is_not_dead():
    # DGICB-like: barely trades, but not dead — floor handles it, not the skip
    alive = _frame([18.0] * 19 + [18.22], [89, 426, 289, 0, 84, 490, 128] + [100] * 13)
    assert is_dead_series(alive) is False


def test_is_dead_series_empty_is_dead():
    assert is_dead_series(pd.DataFrame()) is True
    assert is_dead_series(None) is True


def test_latest_bar_untraded_catches_recently_delisted():
    # THR-like: real trading then a frozen, zero-volume tail (acquired/halted).
    # 20-bar window still holds real volume, so is_dead_series MISSES it...
    close = [65.0] * 11 + [61.14] * 9
    volume = [500_000] * 11 + [0] * 9
    df = _frame(close, volume)
    assert is_dead_series(df) is False          # window still has volume
    assert latest_bar_untraded(df) is True      # ...but the last bar is untraded


def test_latest_bar_untraded_false_for_live_name():
    df = _frame([30.0] * 20, [400_000] * 19 + [350_000])
    assert latest_bar_untraded(df) is False


def test_latest_bar_untraded_empty_is_untraded():
    assert latest_bar_untraded(pd.DataFrame()) is True
    assert latest_bar_untraded(None) is True
