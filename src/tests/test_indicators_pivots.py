"""Tests for bh_ftmo.indicators.pivots."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from bh_ftmo.indicators import daily_ohlc, ohlc_mid, pivots
from bh_ftmo.indicators.pivots import _classic_pivots

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _ny_ts(y, m, d, h=0) -> datetime:
    """Return tz-naive UTC equivalent of a NY-local datetime."""
    return datetime(y, m, d, h, 0, tzinfo=NY).astimezone(UTC).replace(tzinfo=None)


# ---- daily_ohlc --------------------------------------------------------


def test_daily_ohlc_single_day_aggregation():
    # Six H4 bars all on Monday NY (2025-03-10) at NY hours 1, 5, 9, 13, 17, 21
    ts = [_ny_ts(2025, 3, 10, h) for h in (1, 5, 9, 13, 17, 21)]
    ohlc = pd.DataFrame({
        "open": [1.10, 1.11, 1.12, 1.13, 1.14, 1.15],
        "high": [1.20, 1.21, 1.25, 1.22, 1.20, 1.19],
        "low":  [1.05, 1.08, 1.09, 1.10, 1.08, 1.07],
        "close":[1.11, 1.12, 1.13, 1.14, 1.15, 1.16],
    })
    daily = daily_ohlc(ohlc, timestamps=pd.Series(ts))
    # One day in index
    assert list(daily.index) == [date(2025, 3, 10)]
    row = daily.iloc[0]
    assert row["open"] == pytest.approx(1.10)      # first bar
    assert row["high"] == pytest.approx(1.25)      # max
    assert row["low"] == pytest.approx(1.05)       # min
    assert row["close"] == pytest.approx(1.16)     # last bar


def test_daily_ohlc_multi_day():
    # Three bars on Mon, three on Tue
    ts = [_ny_ts(2025, 3, 10, h) for h in (1, 9, 17)]
    ts += [_ny_ts(2025, 3, 11, h) for h in (1, 9, 17)]
    ohlc = pd.DataFrame({
        "open":  [1, 2, 3, 4, 5, 6],
        "high":  [2, 3, 4, 5, 6, 7],
        "low":   [0, 1, 2, 3, 4, 5],
        "close": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5],
    })
    daily = daily_ohlc(ohlc, timestamps=pd.Series(ts))
    assert len(daily) == 2
    assert daily.loc[date(2025, 3, 10), "open"] == 1
    assert daily.loc[date(2025, 3, 10), "close"] == 3.5
    assert daily.loc[date(2025, 3, 11), "open"] == 4
    assert daily.loc[date(2025, 3, 11), "close"] == 6.5


def test_daily_ohlc_rejects_length_mismatch():
    ohlc = pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1]})
    ts = pd.Series([_ny_ts(2025, 1, 1), _ny_ts(2025, 1, 2)])
    with pytest.raises(ValueError, match="length"):
        daily_ohlc(ohlc, timestamps=ts)


# ---- _classic_pivots ---------------------------------------------------


def test_classic_pivots_formula():
    # Hand-computed: H=110, L=90, C=100 → PP=100, rng=20
    daily = pd.DataFrame({"open": [100], "high": [110], "low": [90], "close": [100]}, index=[date(2025, 3, 10)])
    p = _classic_pivots(daily).iloc[0]
    assert p["pp"] == pytest.approx(100.0)
    assert p["r1"] == pytest.approx(2 * 100 - 90)           # 110
    assert p["s1"] == pytest.approx(2 * 100 - 110)          # 90
    assert p["r2"] == pytest.approx(100 + 20)               # 120
    assert p["s2"] == pytest.approx(100 - 20)               # 80
    assert p["r3"] == pytest.approx(110 + 2 * (100 - 90))   # 130
    assert p["s3"] == pytest.approx(90 - 2 * (110 - 100))   # 70


# ---- pivots: full flow -------------------------------------------------


def test_pivots_uses_prior_day_ohlc():
    """Tuesday's bars should use Monday's OHLC for pivots."""
    ts = [_ny_ts(2025, 3, 10, h) for h in (1, 9, 17)]  # Monday NY
    ts += [_ny_ts(2025, 3, 11, h) for h in (1, 9, 17)] # Tuesday NY
    ohlc = pd.DataFrame({
        "open":  [100, 100, 100, 200, 200, 200],
        "high":  [110, 110, 110, 220, 220, 220],
        "low":   [90, 90, 90, 180, 180, 180],
        "close": [100, 100, 100, 200, 200, 200],
    })
    p = pivots(ohlc, timestamps=pd.Series(ts))
    # Monday's bars have no prior trading day data → NaN
    assert p.iloc[0:3].isna().all().all()
    # Tuesday's bars should get Monday's pivots: PP = (110+90+100)/3 = 100
    assert p.iloc[3]["pp"] == pytest.approx(100.0)
    assert p.iloc[4]["pp"] == pytest.approx(100.0)
    assert p.iloc[5]["pp"] == pytest.approx(100.0)


def test_pivots_monday_uses_friday_skipping_weekend():
    """Monday bars must reach back to Friday (skip Sat/Sun)."""
    # Friday 2025-03-07, Saturday 3-8, Sunday 3-9, Monday 3-10
    ts = [_ny_ts(2025, 3, 7, h) for h in (1, 9, 17)]   # Friday
    ts += [_ny_ts(2025, 3, 10, h) for h in (1, 9, 17)] # Monday (skip weekend)
    ohlc = pd.DataFrame({
        "open":  [50, 50, 50, 200, 200, 200],
        "high":  [60, 60, 60, 220, 220, 220],
        "low":   [40, 40, 40, 180, 180, 180],
        "close": [55, 55, 55, 200, 200, 200],
    })
    p = pivots(ohlc, timestamps=pd.Series(ts))
    # Monday gets Friday's pivots: PP = (60+40+55)/3 ≈ 51.67
    friday_pp = (60 + 40 + 55) / 3.0
    assert p.iloc[3]["pp"] == pytest.approx(friday_pp)


def test_pivots_preserves_input_index():
    idx = pd.date_range("2020-01-01", periods=6, freq="4h")
    ts = [_ny_ts(2025, 3, 10, h) for h in (1, 9, 17)]
    ts += [_ny_ts(2025, 3, 11, h) for h in (1, 9, 17)]
    ohlc = pd.DataFrame({"open": [1] * 6, "high": [2] * 6, "low": [0] * 6, "close": [1] * 6}, index=idx)
    p = pivots(ohlc, timestamps=pd.Series(ts, index=idx))
    pd.testing.assert_index_equal(p.index, idx)


def test_pivots_all_columns_present():
    ts = [_ny_ts(2025, 3, 10, 9), _ny_ts(2025, 3, 11, 9)]
    ohlc = pd.DataFrame({
        "open":  [100, 200], "high": [110, 220], "low": [90, 180], "close": [100, 200],
    })
    p = pivots(ohlc, timestamps=pd.Series(ts))
    assert set(p.columns) == {"pp", "r1", "r2", "r3", "s1", "s2", "s3"}


def test_pivots_band_ordering():
    """On positive-range days: r3 > r2 > r1 > pp > s1 > s2 > s3."""
    ts = [_ny_ts(2025, 3, 10, 9), _ny_ts(2025, 3, 11, 9)]
    ohlc = pd.DataFrame({
        "open":  [100, 100], "high": [120, 120], "low": [80, 80], "close": [100, 100],
    })
    p = pivots(ohlc, timestamps=pd.Series(ts))
    row = p.iloc[1]
    assert row["r3"] > row["r2"] > row["r1"] > row["pp"]
    assert row["pp"] > row["s1"] > row["s2"] > row["s3"]


# ---- integration: real FxStore data -----------------------------------


def test_pivots_on_fxstore_data():
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

    if len(df) < 20:
        pytest.skip("fx_4h.duckdb EUR_USD slice too short")

    ohlc = ohlc_mid(df)
    p = pivots(ohlc, timestamps=df["timestamp"])

    pd.testing.assert_index_equal(p.index, ohlc.index)
    valid = p.dropna()
    # Pivot ordering invariants must hold on every row
    assert (valid["r3"] >= valid["r2"]).all()
    assert (valid["r2"] >= valid["r1"]).all()
    assert (valid["r1"] >= valid["pp"]).all()
    assert (valid["pp"] >= valid["s1"]).all()
    assert (valid["s1"] >= valid["s2"]).all()
    assert (valid["s2"] >= valid["s3"]).all()
    # Pivots should be in the neighborhood of the price
    assert valid["pp"].between(0.5, 2.0).all()
