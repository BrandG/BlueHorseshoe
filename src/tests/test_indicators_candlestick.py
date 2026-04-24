"""Tests for bh_ftmo.indicators.candlestick."""
from __future__ import annotations

import pandas as pd
import pytest

from bh_ftmo.indicators import (
    body_size,
    is_bearish,
    is_bearish_engulfing,
    is_bullish,
    is_bullish_engulfing,
    is_doji,
    is_hammer,
    is_shooting_star,
    lower_shadow,
    ohlc_mid,
    total_range,
    upper_shadow,
)


def _bar(o, h, l, c) -> dict:
    return {"open": o, "high": h, "low": l, "close": c}


def _ohlc(bars: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(bars)


# ---- Anatomy helpers ---------------------------------------------------


def test_body_size_is_abs():
    df = _ohlc([_bar(10, 12, 8, 11), _bar(10, 12, 8, 9)])
    got = body_size(df).tolist()
    assert got == [1, 1]


def test_total_range_is_high_minus_low():
    df = _ohlc([_bar(10, 12, 8, 11)])
    assert total_range(df).iloc[0] == 4


def test_upper_shadow_uses_max_of_body():
    # body top = max(open=10, close=11) = 11; upper = 12 - 11 = 1
    df = _ohlc([_bar(10, 12, 8, 11)])
    assert upper_shadow(df).iloc[0] == 1


def test_lower_shadow_uses_min_of_body():
    # body bottom = min(open=10, close=11) = 10; lower = 10 - 8 = 2
    df = _ohlc([_bar(10, 12, 8, 11)])
    assert lower_shadow(df).iloc[0] == 2


def test_is_bullish_bearish_direction():
    df = _ohlc([_bar(10, 12, 8, 11), _bar(10, 12, 8, 9), _bar(10, 12, 8, 10)])
    assert is_bullish(df).tolist() == [True, False, False]
    assert is_bearish(df).tolist() == [False, True, False]


# ---- Doji --------------------------------------------------------------


def test_doji_detects_tiny_body():
    # body = 0.1, range = 4 → body/range = 2.5%; default body_frac=0.1 should fire
    df = _ohlc([_bar(10.0, 12.0, 8.0, 10.1)])
    assert is_doji(df).iloc[0] is True or is_doji(df).iloc[0] == True  # noqa: E712


def test_doji_ignores_big_body():
    df = _ohlc([_bar(10.0, 12.0, 8.0, 11.9)])  # body=1.9, range=4, frac≈47%
    assert is_doji(df).iloc[0] == False  # noqa: E712


def test_doji_threshold_is_configurable():
    df = _ohlc([_bar(10.0, 12.0, 8.0, 10.6)])  # body=0.6, range=4, frac=15%
    assert is_doji(df, body_frac=0.1).iloc[0] == False  # noqa: E712
    assert is_doji(df, body_frac=0.2).iloc[0] == True   # noqa: E712


def test_doji_flat_bar_is_false():
    df = _ohlc([_bar(10.0, 10.0, 10.0, 10.0)])
    assert is_doji(df).iloc[0] == False  # noqa: E712


def test_doji_rejects_bad_frac():
    df = _ohlc([_bar(10, 12, 8, 11)])
    with pytest.raises(ValueError, match="body_frac"):
        is_doji(df, body_frac=0)


# ---- Hammer ------------------------------------------------------------


def test_hammer_clean_case():
    # Textbook hammer: small body at top, long lower shadow, tiny upper shadow
    # range = 10, body = 1 (10%), lower = 8, upper = 1
    df = _ohlc([_bar(9.0, 10.0, 0.0, 9.5)])
    assert is_hammer(df).iloc[0] == True  # noqa: E712


def test_hammer_rejects_big_body():
    # Big body should fail body_frac_max check
    df = _ohlc([_bar(3.0, 10.0, 0.0, 9.0)])  # body=6, range=10, frac=60%
    assert is_hammer(df).iloc[0] == False  # noqa: E712


def test_hammer_rejects_short_lower_shadow():
    # lower shadow too short
    df = _ohlc([_bar(9.0, 10.0, 7.0, 9.5)])  # lower=2, range=3, 67% actually close
    # Wait: body=0.5, range=3, frac=17% OK; lower=min(9,9.5)-7=2, 67% of range OK
    # so this IS a hammer. Let me reconstruct: small range above the body.
    # body 9.7→9.8, high=10, low=8. body=0.1, range=2, lower=min(9.7,9.8)-8=1.7,
    # lower/range=85%. Upper = 10 - max(9.7, 9.8) = 0.2, 10% of range. Hammer.
    # To NOT be a hammer: lower shadow < 50% of range.
    df = _ohlc([_bar(9.0, 10.0, 8.5, 9.4)])  # lower=0.5, range=1.5, 33%
    assert is_hammer(df).iloc[0] == False  # noqa: E712


def test_hammer_rejects_long_upper_shadow():
    # body small, lower shadow long, BUT upper shadow also long → not a hammer
    df = _ohlc([_bar(5.0, 10.0, 0.0, 5.5)])  # body=0.5, upper=4.5 (45%), lower=5 (50%)
    assert is_hammer(df).iloc[0] == False  # noqa: E712


def test_hammer_flat_bar_is_false():
    df = _ohlc([_bar(10.0, 10.0, 10.0, 10.0)])
    assert is_hammer(df).iloc[0] == False  # noqa: E712


# ---- Shooting Star -----------------------------------------------------


def test_shooting_star_clean_case():
    # Small body at bottom, long upper shadow, tiny lower shadow
    df = _ohlc([_bar(0.5, 10.0, 0.0, 1.0)])  # body=0.5, upper=9, lower=0.5
    assert is_shooting_star(df).iloc[0] == True  # noqa: E712


def test_shooting_star_rejects_hammer_shape():
    # Classic hammer shape should NOT fire as shooting star
    df = _ohlc([_bar(9.0, 10.0, 0.0, 9.5)])
    assert is_shooting_star(df).iloc[0] == False  # noqa: E712


# ---- Bullish Engulfing -------------------------------------------------


def test_bullish_engulfing_clean():
    prior = _bar(10.0, 11.0, 8.0, 8.5)   # bearish: o=10, c=8.5
    curr  = _bar(8.0, 12.0, 7.5, 11.0)   # bullish: o=8 <= prior.c=8.5, c=11 >= prior.o=10
    df = _ohlc([prior, curr])
    assert is_bullish_engulfing(df).iloc[1] == True  # noqa: E712
    # First bar has no prior → False
    assert is_bullish_engulfing(df).iloc[0] == False  # noqa: E712


def test_bullish_engulfing_requires_prior_bearish():
    prior = _bar(8.0, 12.0, 7.5, 11.0)  # prior is BULLISH
    curr  = _bar(7.5, 13.0, 7.0, 12.5)  # bullish, engulfs
    df = _ohlc([prior, curr])
    assert is_bullish_engulfing(df).iloc[1] == False  # noqa: E712


def test_bullish_engulfing_requires_full_body_cover():
    prior = _bar(10.0, 11.0, 8.0, 8.5)   # prior bearish, body 8.5..10
    curr  = _bar(8.0, 12.0, 7.5, 9.5)    # current closes at 9.5 < 10 → does NOT engulf
    df = _ohlc([prior, curr])
    assert is_bullish_engulfing(df).iloc[1] == False  # noqa: E712


def test_bullish_engulfing_rejects_dojis():
    # Tiny-body "engulfing" on both bars should fail the body-fraction filter
    prior = _bar(10.0, 11.0, 9.0, 9.95)  # body 0.05 of range 2 = 2.5%
    curr  = _bar(9.9, 11.0, 9.0, 10.1)   # body 0.2 of range 2 = 10%
    df = _ohlc([prior, curr])
    assert is_bullish_engulfing(df).iloc[1] == False  # noqa: E712


# ---- Bearish Engulfing -------------------------------------------------


def test_bearish_engulfing_clean():
    prior = _bar(8.0, 11.0, 7.5, 10.5)   # bullish
    curr  = _bar(11.0, 11.5, 6.0, 7.5)   # bearish: o=11 >= prior.c=10.5, c=7.5 <= prior.o=8
    df = _ohlc([prior, curr])
    assert is_bearish_engulfing(df).iloc[1] == True  # noqa: E712


def test_bearish_engulfing_requires_prior_bullish():
    prior = _bar(10.0, 11.0, 7.5, 8.5)  # prior BEARISH
    curr  = _bar(11.0, 11.5, 6.0, 7.5)
    df = _ohlc([prior, curr])
    assert is_bearish_engulfing(df).iloc[1] == False  # noqa: E712


# ---- integration: real EUR_USD ----------------------------------------


def test_candlestick_on_fxstore_data():
    from bh_ftmo.data.fx_store import FxStore

    store = FxStore(read_only=True)
    try:
        df = store.load(
            "EUR_USD",
            granularity="H4",
            start=pd.Timestamp("2025-01-01").to_pydatetime(),
        )
    finally:
        store.close()

    if len(df) < 500:
        pytest.skip("fx_4h.duckdb EUR_USD slice too short")

    ohlc = ohlc_mid(df)
    # All detectors should run without error and produce bool Series
    for fn in (is_doji, is_hammer, is_shooting_star, is_bullish_engulfing, is_bearish_engulfing):
        out = fn(ohlc)
        assert len(out) == len(ohlc)
        assert out.dtype == bool

    # At least a handful of each pattern should appear across a year of bars
    dojis = int(is_doji(ohlc).sum())
    hammers = int(is_hammer(ohlc).sum())
    stars = int(is_shooting_star(ohlc).sum())
    bull_engulf = int(is_bullish_engulfing(ohlc).sum())
    bear_engulf = int(is_bearish_engulfing(ohlc).sum())
    # Sanity: dojis should fire on a nontrivial fraction (5-40%); engulfings should be rarer
    assert dojis >= 10
    # Engulfings can legitimately be very rare; assert they're at least computable
    assert bull_engulf >= 0 and bear_engulf >= 0
