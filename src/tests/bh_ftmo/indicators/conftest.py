"""Shared fixtures for BH FTMO indicator validation tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _last_n_compare(
    bh_series: pd.Series,
    ta_array: np.ndarray,
    n_warmup: int,
    *,
    rtol: float,
    atol: float,
) -> None:
    """Compare bh_ftmo output to TA-Lib after the documented warmup window."""
    bh = bh_series.iloc[n_warmup:].to_numpy(dtype=float)
    ta = np.asarray(ta_array, dtype=float)[n_warmup:]

    bh_nan = np.isnan(bh)
    ta_nan = np.isnan(ta)
    if not (bh_nan == ta_nan).all():
        mismatch = np.flatnonzero(bh_nan != ta_nan)[:10] + n_warmup
        raise AssertionError(
            "NaN positions differ post-warmup: "
            f"bh has {bh_nan.sum()}, ta has {ta_nan.sum()}, "
            f"first mismatches at positions {mismatch.tolist()}"
        )

    mask = ~bh_nan
    if not mask.any():
        raise AssertionError("No finite values available after warmup")

    diff = np.abs(bh[mask] - ta[mask])
    max_diff = float(diff.max())
    np.testing.assert_allclose(
        bh[mask],
        ta[mask],
        rtol=rtol,
        atol=atol,
        err_msg=f"max_abs_diff={max_diff:.12g} after warmup={n_warmup}",
    )


@pytest.fixture(scope="session")
def ohlc_fixture() -> pd.DataFrame:
    """500 deterministic 4h OHLC bars for indicator parity tests."""
    rng = np.random.default_rng(42)
    n = 500
    base = 1.10
    pip = 0.0001

    log_returns = rng.normal(0, 0.0005, n)
    close = base * np.exp(np.cumsum(log_returns))

    open_ = np.empty(n)
    open_[0] = base
    open_[1:] = close[:-1]

    intra_hi = rng.uniform(0, 30 * pip, n)
    intra_lo = rng.uniform(0, 30 * pip, n)
    high = np.maximum(open_, close) + intra_hi
    low = np.minimum(open_, close) - intra_lo

    index = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=index,
    )
