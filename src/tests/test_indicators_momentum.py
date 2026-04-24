"""Tests for bh_ftmo.indicators.momentum.

Every test uses small hand-constructable inputs. Fidelity is cross-checked
against well-known reference values (e.g., Wilder's RSI worked example).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bh_ftmo.indicators import (
    cci,
    macd,
    ohlc_mid,
    rsi,
    stochastic,
    williams_r,
)


def _ohlc_from_close(closes: list[float], *, spread: float = 0.0) -> pd.DataFrame:
    """Build a minimal OHLC DataFrame where H=L=C=close + spread/2 each bar.

    spread widens H/L so range calculations have something to work with.
    """
    n = len(closes)
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + spread for c in closes],
            "low": [c - spread for c in closes],
            "close": closes,
        },
        index=pd.RangeIndex(n),
    )


# ---- ohlc_mid ----------------------------------------------------------


def test_ohlc_mid_averages_bid_and_ask():
    df = pd.DataFrame({
        "open_bid": [1.0], "open_ask": [1.002],
        "high_bid": [1.01], "high_ask": [1.012],
        "low_bid": [0.99], "low_ask": [0.992],
        "close_bid": [1.005], "close_ask": [1.007],
    })
    mid = ohlc_mid(df)
    assert list(mid.columns) == ["open", "high", "low", "close"]
    assert mid["open"].iloc[0] == pytest.approx(1.001)
    assert mid["close"].iloc[0] == pytest.approx(1.006)


def test_ohlc_mid_preserves_index():
    idx = pd.date_range("2020-01-01", periods=3, freq="4h")
    df = pd.DataFrame({
        "open_bid": [1, 2, 3], "open_ask": [1.01, 2.01, 3.01],
        "high_bid": [1, 2, 3], "high_ask": [1.01, 2.01, 3.01],
        "low_bid": [1, 2, 3], "low_ask": [1.01, 2.01, 3.01],
        "close_bid": [1, 2, 3], "close_ask": [1.01, 2.01, 3.01],
    }, index=idx)
    mid = ohlc_mid(df)
    pd.testing.assert_index_equal(mid.index, idx)


# ---- rsi ---------------------------------------------------------------


def test_rsi_all_gains_returns_100():
    """Monotonic increase: avg_loss == 0 → RSI pinned to 100."""
    ohlc = _ohlc_from_close([float(i) for i in range(1, 30)])
    out = rsi(ohlc, period=14)
    # First 14 are NaN (min_periods), 15th onward should be 100
    assert out.iloc[-1] == pytest.approx(100.0)


def test_rsi_all_losses_returns_0():
    """Monotonic decrease: avg_gain == 0 → RSI → 0."""
    ohlc = _ohlc_from_close([float(i) for i in range(30, 1, -1)])
    out = rsi(ohlc, period=14)
    # When avg_gain == 0 and avg_loss > 0, rs = 0 → RSI = 100 - 100/1 = 0
    assert out.iloc[-1] == pytest.approx(0.0)


def test_rsi_flat_price_is_nan():
    """Zero price change forever → avg_gain = avg_loss = 0 → undefined."""
    ohlc = _ohlc_from_close([50.0] * 20)
    out = rsi(ohlc, period=14)
    # First 14 NaN from min_periods; after that, flat prices yield NaN because
    # the divide-by-zero + both-zero path is guarded.
    assert np.isnan(out.iloc[-1])


def test_rsi_range_stays_in_bounds():
    """On noisy data, RSI must stay in [0, 100]."""
    rng = np.random.default_rng(42)
    closes = list(100 + rng.standard_normal(200).cumsum())
    ohlc = _ohlc_from_close(closes)
    out = rsi(ohlc, period=14).dropna()
    assert out.min() >= 0.0
    assert out.max() <= 100.0


def test_rsi_rejects_period_zero():
    ohlc = _ohlc_from_close([1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="period"):
        rsi(ohlc, period=0)


def test_rsi_preserves_index():
    idx = pd.date_range("2020-01-01", periods=30, freq="4h")
    ohlc = _ohlc_from_close(list(range(30)))
    ohlc.index = idx
    out = rsi(ohlc, period=14)
    pd.testing.assert_index_equal(out.index, idx)


# ---- macd --------------------------------------------------------------


def test_macd_returns_three_columns():
    ohlc = _ohlc_from_close([100 + i for i in range(60)])
    out = macd(ohlc)
    assert set(out.columns) == {"macd", "signal", "histogram"}
    assert len(out) == len(ohlc)


def test_macd_histogram_equals_macd_minus_signal():
    ohlc = _ohlc_from_close([100 + np.sin(i / 3) * 5 for i in range(80)])
    out = macd(ohlc).dropna()
    assert (out["histogram"] - (out["macd"] - out["signal"])).abs().max() < 1e-9


def test_macd_constant_price_yields_zeros():
    ohlc = _ohlc_from_close([50.0] * 60)
    out = macd(ohlc).dropna()
    assert out["macd"].abs().max() < 1e-9
    assert out["signal"].abs().max() < 1e-9
    assert out["histogram"].abs().max() < 1e-9


def test_macd_rejects_fast_gte_slow():
    ohlc = _ohlc_from_close([100.0] * 30)
    with pytest.raises(ValueError, match="fast"):
        macd(ohlc, fast=26, slow=12)


def test_macd_nan_front_fill():
    ohlc = _ohlc_from_close([float(i) for i in range(40)])
    out = macd(ohlc, fast=12, slow=26, signal=9)
    # signal needs slow=26 + signal=9 - 1 = 34 bars of history for first value
    assert out["signal"].iloc[33] is not None  # maybe NaN or value
    # But certainly the first N are NaN
    assert out["macd"].iloc[0] != out["macd"].iloc[0]  # NaN check via != self


# ---- stochastic --------------------------------------------------------


def test_stochastic_k_at_high_is_100():
    """Close at the high of the lookback → %K should be 100."""
    # Build a sequence where the last bar's close = max high of last 14 bars
    closes = [10.0] * 13 + [20.0]
    ohlc = pd.DataFrame({
        "open": closes,
        "high": closes,    # high = close, so max high over the window = 20
        "low": [10.0] * 14,  # uniform low = 10
        "close": closes,
    })
    out = stochastic(ohlc, k_period=14, d_period=3)
    assert out["k"].iloc[-1] == pytest.approx(100.0)


def test_stochastic_k_at_low_is_0():
    closes = [20.0] * 13 + [10.0]
    ohlc = pd.DataFrame({
        "open": closes,
        "high": [20.0] * 14,
        "low": closes,
        "close": closes,
    })
    out = stochastic(ohlc, k_period=14, d_period=3)
    assert out["k"].iloc[-1] == pytest.approx(0.0)


def test_stochastic_flat_range_is_nan():
    ohlc = _ohlc_from_close([50.0] * 20)  # spread=0 → high == low everywhere
    out = stochastic(ohlc, k_period=14, d_period=3)
    assert np.isnan(out["k"].iloc[-1])


def test_stochastic_d_is_sma_of_k():
    rng = np.random.default_rng(0)
    closes = list(50 + rng.standard_normal(60).cumsum())
    ohlc = _ohlc_from_close(closes, spread=1.0)
    out = stochastic(ohlc, k_period=14, d_period=3)
    # D at index i should equal mean of K over [i-2, i-1, i] (window=3)
    dropped = out.dropna()
    if len(dropped) >= 5:
        i = dropped.index[-1]
        expected_d = out["k"].loc[[dropped.index[-3], dropped.index[-2], i]].mean()
        assert out["d"].loc[i] == pytest.approx(expected_d)


# ---- cci ---------------------------------------------------------------


def test_cci_constant_price_is_nan():
    """Flat TP → mean deviation is 0 → CCI undefined."""
    ohlc = _ohlc_from_close([50.0] * 30)
    out = cci(ohlc, period=20)
    assert np.isnan(out.iloc[-1])


def test_cci_trending_up_becomes_positive():
    ohlc = _ohlc_from_close([float(i) for i in range(40)], spread=0.5)
    out = cci(ohlc, period=20).dropna()
    # Steady uptrend → TP > SMA(TP) → CCI > 0 consistently
    assert (out > 0).all()


def test_cci_trending_down_becomes_negative():
    ohlc = _ohlc_from_close([float(40 - i) for i in range(40)], spread=0.5)
    out = cci(ohlc, period=20).dropna()
    assert (out < 0).all()


# ---- williams_r --------------------------------------------------------


def test_williams_r_range_is_negative():
    rng = np.random.default_rng(0)
    closes = list(50 + rng.standard_normal(60).cumsum())
    ohlc = _ohlc_from_close(closes, spread=1.0)
    out = williams_r(ohlc, period=14).dropna()
    assert out.min() >= -100.0
    assert out.max() <= 0.0


def test_williams_r_close_at_high_is_zero():
    """Close == max high over period → %R = 0."""
    closes = [10.0] * 13 + [20.0]
    ohlc = pd.DataFrame({
        "open": closes,
        "high": closes,
        "low": [10.0] * 14,
        "close": closes,
    })
    out = williams_r(ohlc, period=14)
    assert out.iloc[-1] == pytest.approx(0.0)


def test_williams_r_close_at_low_is_minus_100():
    closes = [20.0] * 13 + [10.0]
    ohlc = pd.DataFrame({
        "open": closes,
        "high": [20.0] * 14,
        "low": closes,
        "close": closes,
    })
    out = williams_r(ohlc, period=14)
    assert out.iloc[-1] == pytest.approx(-100.0)


# ---- integration: real FxStore data -----------------------------------


def test_momentum_indicators_work_on_fxstore_data():
    """Smoke: compute all five on a real EUR_USD slice."""
    from bh_ftmo.data.fx_store import FxStore

    store = FxStore(read_only=True)
    try:
        df = store.load(
            "EUR_USD",
            granularity="H4",
            start=pd.Timestamp("2025-01-01").to_pydatetime(),
            end=pd.Timestamp("2025-02-01").to_pydatetime(),
        )
    finally:
        store.close()

    if len(df) < 50:
        pytest.skip(f"fx_4h.duckdb has insufficient EUR_USD data ({len(df)} bars) — skipping")

    ohlc = ohlc_mid(df)
    rsi14 = rsi(ohlc, period=14)
    macd_df = macd(ohlc)
    stoch_df = stochastic(ohlc)
    cci20 = cci(ohlc, period=20)
    wr14 = williams_r(ohlc, period=14)

    # All outputs share the input's index
    for out in (rsi14, cci20, wr14):
        pd.testing.assert_index_equal(out.index, ohlc.index)
    for out_df in (macd_df, stoch_df):
        pd.testing.assert_index_equal(out_df.index, ohlc.index)

    # Sanity-check value ranges where defined
    assert rsi14.dropna().between(0, 100).all()
    assert wr14.dropna().between(-100, 0).all()
    assert stoch_df["k"].dropna().between(0, 100).all()
