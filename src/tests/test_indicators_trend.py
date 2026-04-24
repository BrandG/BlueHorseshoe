"""Tests for bh_ftmo.indicators.trend."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bh_ftmo.indicators import (
    adx,
    donchian,
    ema,
    ichimoku,
    ohlc_mid,
    sma,
    supertrend,
)


def _ohlc_from_close(closes, *, spread: float = 0.5) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": list(closes),
            "high": [c + spread for c in closes],
            "low": [c - spread for c in closes],
            "close": list(closes),
        },
        index=pd.RangeIndex(len(closes)),
    )


# ---- SMA / EMA ---------------------------------------------------------


def test_sma_matches_rolling_mean():
    ohlc = _ohlc_from_close([float(i) for i in range(1, 25)])
    out = sma(ohlc, period=5)
    expected = ohlc["close"].rolling(5, min_periods=5).mean()
    pd.testing.assert_series_equal(out, expected, check_names=False)


def test_sma_rejects_period_zero():
    ohlc = _ohlc_from_close([1.0, 2.0])
    with pytest.raises(ValueError, match="period"):
        sma(ohlc, period=0)


def test_sma_rejects_unknown_column():
    ohlc = _ohlc_from_close([1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="column"):
        sma(ohlc, period=2, column="bogus")


def test_ema_matches_ewm():
    ohlc = _ohlc_from_close([float(i) for i in range(1, 25)])
    out = ema(ohlc, period=5)
    expected = ohlc["close"].ewm(span=5, adjust=False, min_periods=5).mean()
    pd.testing.assert_series_equal(out, expected, check_names=False)


def test_ema_on_flat_price():
    ohlc = _ohlc_from_close([50.0] * 30)
    out = ema(ohlc, period=5).dropna()
    assert (out == 50.0).all()


# ---- ADX ---------------------------------------------------------------


def test_adx_strong_uptrend_has_high_adx():
    """Monotonic uptrend should drive ADX high (>50 typically)."""
    ohlc = _ohlc_from_close([float(i) for i in range(1, 80)])
    out = adx(ohlc, period=14).dropna()
    assert out["adx"].iloc[-1] > 50.0
    assert out["plus_di"].iloc[-1] > out["minus_di"].iloc[-1]


def test_adx_strong_downtrend_flips_dis():
    ohlc = _ohlc_from_close([float(80 - i) for i in range(79)])
    out = adx(ohlc, period=14).dropna()
    assert out["adx"].iloc[-1] > 50.0
    assert out["minus_di"].iloc[-1] > out["plus_di"].iloc[-1]


def test_adx_ranging_market_has_lower_adx():
    """Oscillating within a band should have much lower ADX than a trend."""
    closes = [50.0 + np.sin(i / 2) * 2 for i in range(80)]
    ohlc = _ohlc_from_close(closes)
    out = adx(ohlc, period=14).dropna()
    # Lax threshold — just confirm it's nowhere near 100
    assert out["adx"].iloc[-1] < 40.0


def test_adx_in_0_100_range():
    rng = np.random.default_rng(0)
    closes = list(50 + rng.standard_normal(120).cumsum())
    ohlc = _ohlc_from_close(closes, spread=1.0)
    out = adx(ohlc, period=14).dropna()
    assert (out["adx"] >= 0).all()
    assert (out["adx"] <= 100).all()
    assert (out["plus_di"] >= 0).all()
    assert (out["plus_di"] <= 100).all()


# ---- SuperTrend --------------------------------------------------------


def test_supertrend_direction_flag_matches_uptrend():
    """Strong uptrend → SuperTrend line below price, direction +1."""
    ohlc = _ohlc_from_close([float(i) for i in range(1, 80)])
    out = supertrend(ohlc, period=10, multiplier=3.0)
    # After the first ~10-20 bars, we should be in uptrend
    tail = out.dropna().iloc[-10:]
    assert (tail["direction"] == 1).all()
    # Line should be below price on uptrend
    assert (tail["supertrend"] < ohlc["close"].iloc[tail.index]).all()


def test_supertrend_direction_flips_on_downtrend():
    ohlc = _ohlc_from_close([float(80 - i) for i in range(79)])
    out = supertrend(ohlc, period=10, multiplier=3.0)
    tail = out.dropna().iloc[-10:]
    assert (tail["direction"] == -1).all()
    # Line above price on downtrend
    assert (tail["supertrend"] > ohlc["close"].iloc[tail.index]).all()


def test_supertrend_rejects_non_positive_multiplier():
    ohlc = _ohlc_from_close([1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="multiplier"):
        supertrend(ohlc, multiplier=0)


def test_supertrend_handles_empty_after_nan_atr():
    """Input too short for ATR → return all NaN gracefully, no crash."""
    ohlc = _ohlc_from_close([1.0, 2.0, 3.0])
    out = supertrend(ohlc, period=10, multiplier=3.0)
    assert len(out) == 3


# ---- Donchian ----------------------------------------------------------


def test_donchian_upper_is_rolling_max_high():
    ohlc = _ohlc_from_close([float(i) for i in range(1, 30)])
    out = donchian(ohlc, period=10)
    expected_upper = ohlc["high"].rolling(10, min_periods=10).max()
    pd.testing.assert_series_equal(out["upper"], expected_upper, check_names=False)


def test_donchian_lower_is_rolling_min_low():
    ohlc = _ohlc_from_close([float(i) for i in range(30, 1, -1)])
    out = donchian(ohlc, period=10)
    expected_lower = ohlc["low"].rolling(10, min_periods=10).min()
    pd.testing.assert_series_equal(out["lower"], expected_lower, check_names=False)


def test_donchian_middle_is_average_of_bands():
    ohlc = _ohlc_from_close([float(i) for i in range(1, 30)])
    out = donchian(ohlc, period=10).dropna()
    assert ((out["middle"] - (out["upper"] + out["lower"]) / 2.0).abs().max() < 1e-12)


def test_donchian_upper_geq_lower():
    rng = np.random.default_rng(1)
    closes = list(50 + rng.standard_normal(60).cumsum())
    ohlc = _ohlc_from_close(closes, spread=1.0)
    out = donchian(ohlc, period=20).dropna()
    assert (out["upper"] >= out["lower"]).all()


# ---- Ichimoku ----------------------------------------------------------


def test_ichimoku_columns():
    ohlc = _ohlc_from_close([float(i) for i in range(1, 100)])
    out = ichimoku(ohlc)
    assert set(out.columns) == {"tenkan", "kijun", "senkou_a", "senkou_b", "chikou"}


def test_ichimoku_senkou_backward_aligned_to_price():
    """Senkou A/B use shift(+displacement) so each row's value represents the
    cloud built 26 bars ago — i.e., what the current price is sitting inside.
    This means the FIRST 26 rows are NaN (no data before bar 0), not the last.
    """
    ohlc = _ohlc_from_close([float(i) for i in range(1, 100)])
    out = ichimoku(ohlc, displacement=26)
    # First displacement rows are NaN
    assert out["senkou_a"].iloc[:26].isna().all()
    # Late rows are populated (enough history + shift)
    assert out["senkou_a"].iloc[-5:].notna().all()
    # Senkou A at index i == (tenkan + kijun) / 2 at index (i - 26)
    i = 80
    expected = (out["tenkan"].iloc[i - 26] + out["kijun"].iloc[i - 26]) / 2.0
    assert out["senkou_a"].iloc[i] == pytest.approx(expected)


def test_ichimoku_chikou_backward_shift_leaves_tail_nonnan():
    ohlc = _ohlc_from_close([float(i) for i in range(1, 100)])
    out = ichimoku(ohlc, displacement=26)
    # Chikou is close shifted BACK — last 26 rows are NaN (they'd map to future close)
    assert out["chikou"].iloc[-26:].isna().all()
    # But the first 60ish should be populated
    assert out["chikou"].iloc[26:60].notna().all()


def test_ichimoku_tenkan_is_9_period_midpoint():
    ohlc = _ohlc_from_close([float(i) for i in range(1, 30)])
    out = ichimoku(ohlc, tenkan_period=9)
    # At index 8, tenkan = (max high[0..8] + min low[0..8]) / 2
    expected = (ohlc["high"].iloc[:9].max() + ohlc["low"].iloc[:9].min()) / 2
    assert out["tenkan"].iloc[8] == pytest.approx(expected)


def test_ichimoku_rejects_negative_displacement():
    ohlc = _ohlc_from_close([1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="displacement"):
        ichimoku(ohlc, displacement=-1)


# ---- integration: real FxStore data -----------------------------------


def test_trend_indicators_on_fxstore_data():
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

    if len(df) < 120:
        pytest.skip(f"fx_4h.duckdb EUR_USD slice too short ({len(df)} bars)")

    ohlc = ohlc_mid(df)
    sma20 = sma(ohlc, period=20)
    ema20 = ema(ohlc, period=20)
    adx_df = adx(ohlc, period=14)
    st = supertrend(ohlc, period=10, multiplier=3.0)
    dc = donchian(ohlc, period=20)
    ich = ichimoku(ohlc)

    for out in (sma20, ema20):
        pd.testing.assert_index_equal(out.index, ohlc.index)
    for out_df in (adx_df, st, dc, ich):
        pd.testing.assert_index_equal(out_df.index, ohlc.index)

    assert (adx_df["adx"].dropna().between(0, 100)).all()
    assert st["direction"].dropna().isin([-1, 0, 1]).all()
    dc_valid = dc.dropna()
    assert (dc_valid["upper"] >= dc_valid["lower"]).all()
