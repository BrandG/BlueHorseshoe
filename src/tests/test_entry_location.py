"""Tests for the high-ATR ∩ NY entry-location skip predicate (bud.entry_location)."""
import numpy as np
import pandas as pd
import pytest

from bud.entry_location import (
    ATR_HIGH_PCT,
    ATR_PCT_WINDOW,
    atr_pct_w252,
    is_high_ny_skip,
)

# NY session = 12:00–17:00 NY local. Jan 2 2024 is a Tuesday (forex open, EST = UTC-5).
NY_TS = pd.Timestamp("2024-01-02 18:00:00")     # 13:00 EST -> ny
ASIA_TS = pd.Timestamp("2024-01-02 23:00:00")   # 18:00 EST -> asia (17:00–03:00)


def _mid(n: int = 300, trend: str = "up") -> pd.DataFrame:
    """Synthetic mid OHLC with monotonic bar range → monotonic ATR.

    trend='up'  → last bar has the largest ATR  → trailing-252 percentile = 1.0 (high).
    trend='down'→ last bar has the smallest ATR → percentile ≈ 1/252      (low).
    """
    rng = np.linspace(0.1, 2.0, n) if trend == "up" else np.linspace(2.0, 0.1, n)
    close = np.full(n, 100.0)
    return pd.DataFrame({
        "open": close, "high": close + rng / 2, "low": close - rng / 2, "close": close,
    })


def test_atr_pct_high_and_low():
    assert atr_pct_w252(_mid(trend="up")) == pytest.approx(1.0)
    assert atr_pct_w252(_mid(trend="down")) < 1.0 / 3.0


def test_atr_pct_insufficient_history_is_nan():
    assert np.isnan(atr_pct_w252(_mid(n=ATR_PCT_WINDOW - 1)))


def test_skip_fires_for_each_strong4_long_in_ny_high_atr():
    mid = _mid(trend="up")
    for strat in ("bb", "rsi", "ema", "stoch"):
        assert is_high_ny_skip(strat, "long", NY_TS, mid) is True


def test_skip_false_for_shorts():
    assert is_high_ny_skip("bb", "short", NY_TS, _mid(trend="up")) is False


def test_skip_false_for_non_strong4():
    for strat in ("cci", "sma", "macd", "atr", "ichimoku", "candle"):
        assert is_high_ny_skip(strat, "long", NY_TS, _mid(trend="up")) is False


def test_skip_false_outside_ny_session():
    assert is_high_ny_skip("bb", "long", ASIA_TS, _mid(trend="up")) is False


def test_skip_false_in_low_atr():
    assert is_high_ny_skip("bb", "long", NY_TS, _mid(trend="down")) is False


def test_skip_fails_open_on_insufficient_history():
    # nan percentile → never suppress
    assert is_high_ny_skip("bb", "long", NY_TS, _mid(n=ATR_PCT_WINDOW - 1)) is False


def test_high_bucket_threshold_constant():
    assert ATR_HIGH_PCT == pytest.approx(2.0 / 3.0)
