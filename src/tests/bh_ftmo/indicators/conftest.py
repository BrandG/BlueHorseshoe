"""Shared fixtures for BH FTMO indicator validation tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


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
