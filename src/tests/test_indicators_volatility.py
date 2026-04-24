"""Tests for bh_ftmo.indicators.volatility (ATR + Bollinger)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bh_ftmo.indicators import (
    atr,
    atr_percent,
    bollinger_bands,
    ohlc_mid,
    true_range,
)


def _make_ohlc(highs, lows, closes, opens=None) -> pd.DataFrame:
    if opens is None:
        opens = list(closes)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes},
        index=pd.RangeIndex(len(closes)),
    )


# ---- true_range --------------------------------------------------------


def test_true_range_first_bar_is_h_minus_l():
    ohlc = _make_ohlc(highs=[10.0], lows=[8.0], closes=[9.0])
    tr = true_range(ohlc)
    assert tr.iloc[0] == pytest.approx(2.0)


def test_true_range_uses_prev_close_gap_up():
    # Bar 2: gap up — high (15) - prev_close (9) = 6 > high-low (2) and low-prev_close
    ohlc = _make_ohlc(
        highs=[10.0, 15.0],
        lows=[8.0, 13.0],
        closes=[9.0, 14.0],
    )
    tr = true_range(ohlc)
    assert tr.iloc[1] == pytest.approx(6.0)


def test_true_range_uses_prev_close_gap_down():
    # Bar 2: gap down — |low (3) - prev_close (9)| = 6, max term
    ohlc = _make_ohlc(
        highs=[10.0, 5.0],
        lows=[8.0, 3.0],
        closes=[9.0, 4.0],
    )
    tr = true_range(ohlc)
    assert tr.iloc[1] == pytest.approx(6.0)


def test_true_range_flat_bars_is_zero():
    ohlc = _make_ohlc(highs=[5.0] * 5, lows=[5.0] * 5, closes=[5.0] * 5)
    tr = true_range(ohlc)
    assert (tr == 0).all()


# ---- atr ---------------------------------------------------------------


def test_atr_flat_price_is_zero():
    ohlc = _make_ohlc(highs=[50.0] * 30, lows=[50.0] * 30, closes=[50.0] * 30)
    out = atr(ohlc, period=14)
    # First period-1 are NaN from min_periods; after that, all zeros
    assert out.dropna().eq(0.0).all()


def test_atr_converges_on_steady_range():
    """Each bar has TR = 2 exactly → ATR should converge to 2."""
    # Build bars where high-low = 2 and no gaps (close = midpoint)
    n = 30
    ohlc = _make_ohlc(
        highs=[11.0] * n,
        lows=[9.0] * n,
        closes=[10.0] * n,
    )
    out = atr(ohlc, period=14).dropna()
    assert out.iloc[-1] == pytest.approx(2.0, abs=0.01)


def test_atr_rejects_period_zero():
    ohlc = _make_ohlc(highs=[1.0], lows=[1.0], closes=[1.0])
    with pytest.raises(ValueError, match="period"):
        atr(ohlc, period=0)


def test_atr_is_non_negative():
    rng = np.random.default_rng(0)
    closes = list(50 + rng.standard_normal(100).cumsum())
    ohlc = pd.DataFrame({
        "open": closes, "close": closes,
        "high": [c + abs(rng.standard_normal()) for c in closes],
        "low":  [c - abs(rng.standard_normal()) for c in closes],
    })
    out = atr(ohlc, period=14).dropna()
    assert (out >= 0).all()


# ---- atr_percent -------------------------------------------------------


def test_atr_percent_is_atr_over_close():
    n = 30
    ohlc = _make_ohlc(
        highs=[101.0] * n,
        lows=[99.0] * n,
        closes=[100.0] * n,
    )
    atr_val = atr(ohlc, period=14).iloc[-1]
    pct = atr_percent(ohlc, period=14).iloc[-1]
    assert pct == pytest.approx(atr_val / 100.0)


# ---- bollinger_bands ---------------------------------------------------


def test_bollinger_columns():
    ohlc = _make_ohlc(highs=[100.0] * 25, lows=[100.0] * 25, closes=list(range(90, 115)))
    out = bollinger_bands(ohlc, period=20)
    assert set(out.columns) == {"middle", "upper", "lower", "pct_b", "bandwidth"}


def test_bollinger_upper_above_middle_above_lower():
    rng = np.random.default_rng(1)
    closes = list(100 + rng.standard_normal(60).cumsum())
    ohlc = pd.DataFrame({
        "open": closes, "high": closes, "low": closes, "close": closes,
    })
    out = bollinger_bands(ohlc, period=20, n_std=2.0).dropna()
    assert (out["upper"] >= out["middle"]).all()
    assert (out["middle"] >= out["lower"]).all()


def test_bollinger_flat_price_gives_nan_pct_b():
    ohlc = _make_ohlc(highs=[50.0] * 30, lows=[50.0] * 30, closes=[50.0] * 30)
    out = bollinger_bands(ohlc, period=20)
    # When close is flat, std=0, upper=lower=middle → band_range = 0 → %B NaN
    assert np.isnan(out["pct_b"].iloc[-1])
    # Bandwidth is 0 / middle = 0 (well-defined)
    assert out["bandwidth"].iloc[-1] == pytest.approx(0.0)


def test_bollinger_pct_b_at_upper_band_is_one():
    """Manually construct close = upper band and verify %B == 1."""
    # 20 bars of constant 100, then bar 21 pushes up to exactly upper band
    closes = [100.0] * 20 + [110.0]  # will produce non-zero std
    ohlc = pd.DataFrame({
        "open": closes, "high": [c + 1 for c in closes],
        "low": [c - 1 for c in closes], "close": closes,
    })
    out = bollinger_bands(ohlc, period=20, n_std=2.0)
    # At index 20, close=110, compute what %B should be:
    # middle_20 = mean(closes[1:21]) = mean of nineteen 100s + 110 = 100.5
    # std_20    = std(closes[1:21], ddof=0)
    expected_middle = np.mean(closes[1:21])
    expected_std = np.std(closes[1:21])  # ddof=0
    expected_upper = expected_middle + 2.0 * expected_std
    expected_lower = expected_middle - 2.0 * expected_std
    expected_pct_b = (110.0 - expected_lower) / (expected_upper - expected_lower)
    assert out["pct_b"].iloc[20] == pytest.approx(expected_pct_b)


def test_bollinger_bandwidth_shrinks_during_squeeze():
    """Low-volatility window should produce smaller bandwidth than high-vol."""
    calm = [100.0 + 0.01 * (i % 3) for i in range(40)]
    stormy = [100.0 + (i % 7) for i in range(40)]
    ohlc_calm = pd.DataFrame({"open": calm, "high": calm, "low": calm, "close": calm})
    ohlc_stormy = pd.DataFrame({"open": stormy, "high": stormy, "low": stormy, "close": stormy})
    bw_calm = bollinger_bands(ohlc_calm, period=20)["bandwidth"].iloc[-1]
    bw_stormy = bollinger_bands(ohlc_stormy, period=20)["bandwidth"].iloc[-1]
    assert bw_calm < bw_stormy


def test_bollinger_rejects_period_lt_2():
    ohlc = _make_ohlc(highs=[1.0], lows=[1.0], closes=[1.0])
    with pytest.raises(ValueError, match="period"):
        bollinger_bands(ohlc, period=1)


def test_bollinger_rejects_non_positive_n_std():
    ohlc = _make_ohlc(highs=[1.0] * 25, lows=[1.0] * 25, closes=[1.0] * 25)
    with pytest.raises(ValueError, match="n_std"):
        bollinger_bands(ohlc, n_std=0)


# ---- integration -------------------------------------------------------


def test_volatility_on_fxstore_data():
    """Smoke: ATR + Bollinger on real EUR_USD H4."""
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

    if len(df) < 30:
        pytest.skip("fx_4h.duckdb missing EUR_USD data")

    ohlc = ohlc_mid(df)
    atr14 = atr(ohlc, period=14)
    atr_pct = atr_percent(ohlc, period=14)
    bb = bollinger_bands(ohlc, period=20)

    # All outputs share input index
    pd.testing.assert_index_equal(atr14.index, ohlc.index)
    pd.testing.assert_index_equal(bb.index, ohlc.index)

    # ATR non-negative, ATR_percent small (forex H4 ATR typically < 1% of price)
    assert (atr14.dropna() >= 0).all()
    assert (atr_pct.dropna() < 0.02).all()  # generous upper bound
    # Band ordering holds
    bb_valid = bb.dropna()
    assert (bb_valid["upper"] >= bb_valid["middle"]).all()
    assert (bb_valid["middle"] >= bb_valid["lower"]).all()
