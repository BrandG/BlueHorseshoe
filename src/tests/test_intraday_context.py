"""Tests for intraday context analysis module."""

import json

import numpy as np
import pandas as pd

from bluehorseshoe.analysis.intraday_context import (
    close_strength,
    compute_context_score,
    compute_daily_context,
    compute_intraday_confirmation,
    detect_failed_breakout,
    range_expansion,
)


def _make_bars(days=30, start_price=100.0, trend=0.001):
    """Generate synthetic daily OHLCV DataFrame with atr_14."""
    rng = np.random.default_rng(42)
    dates = pd.date_range(end=pd.Timestamp.today(), periods=days, freq="D")
    prices = [start_price]
    for _ in range(1, days):
        prices.append(prices[-1] * (1 + trend + rng.normal(0, 0.01)))
    highs = [p * (1 + rng.uniform(0.005, 0.02)) for p in prices]
    lows = [p * (1 - rng.uniform(0.005, 0.02)) for p in prices]
    df = pd.DataFrame({
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": [p * (1 + rng.uniform(-0.005, 0.005)) for p in prices],
        "high": highs,
        "low": lows,
        "close": prices,
        "volume": [int(rng.uniform(1e6, 5e6)) for _ in prices],
    })
    tr = pd.DataFrame({
        "hl": df["high"] - df["low"],
        "hc": (df["high"] - df["close"].shift(1)).abs(),
        "lc": (df["low"] - df["close"].shift(1)).abs(),
    }).max(axis=1)
    df["atr_14"] = tr.rolling(14).mean()
    df["atr_14"] = df["atr_14"].bfill()
    return df


def _make_intraday_bars(n=78, start_price=100.0, trend=0.001):
    """Generate synthetic 5-min OHLCV DataFrame."""
    rng = np.random.default_rng(99)
    base = pd.Timestamp("2026-04-17 09:30:00")
    datetimes = [base + pd.Timedelta(minutes=5 * i) for i in range(n)]
    prices = [start_price]
    for _ in range(1, n):
        prices.append(prices[-1] * (1 + trend + rng.normal(0, 0.002)))
    highs = [p * (1 + rng.uniform(0.001, 0.005)) for p in prices]
    lows = [p * (1 - rng.uniform(0.001, 0.005)) for p in prices]
    return pd.DataFrame({
        "datetime": datetimes,
        "open": [p * (1 + rng.uniform(-0.002, 0.002)) for p in prices],
        "high": highs,
        "low": lows,
        "close": prices,
        "volume": [int(rng.uniform(1000, 5000)) for _ in prices],
    })


def test_failed_breakout_detected():
    df = _make_bars(30)
    prior_max_high = df.iloc[-21:-1]["high"].max()
    df.loc[df.index[-1], "high"] = prior_max_high + 1.0
    df.loc[df.index[-1], "close"] = prior_max_high - 0.5

    fb, fbd, resistance, support = detect_failed_breakout(df)

    assert fb is True
    assert fbd is False
    assert resistance == prior_max_high


def test_successful_breakout_not_flagged():
    df = _make_bars(30)
    prior_max_high = df.iloc[-21:-1]["high"].max()
    df.loc[df.index[-1], "high"] = prior_max_high + 2.0
    df.loc[df.index[-1], "close"] = prior_max_high + 1.0

    fb, fbd, resistance, support = detect_failed_breakout(df)

    assert fb is False
    assert fbd is False
    assert resistance == prior_max_high
    assert support == df.iloc[-21:-1]["low"].min()


def test_failed_breakdown_detected():
    df = _make_bars(30)
    prior_min_low = df.iloc[-21:-1]["low"].min()
    df.loc[df.index[-1], "low"] = prior_min_low - 1.0
    df.loc[df.index[-1], "close"] = prior_min_low + 0.5

    fb, fbd, resistance, support = detect_failed_breakout(df)

    assert fb is False
    assert fbd is True
    assert support == prior_min_low


def test_no_breakout_no_breakdown():
    df = _make_bars(30)
    prior_max_high = df.iloc[-21:-1]["high"].max()
    prior_min_low = df.iloc[-21:-1]["low"].min()
    mid = (prior_max_high + prior_min_low) / 2
    df.loc[df.index[-1], "high"] = mid + 0.5
    df.loc[df.index[-1], "low"] = mid - 0.5
    df.loc[df.index[-1], "close"] = mid

    fb, fbd, resistance, support = detect_failed_breakout(df)

    assert fb is False
    assert fbd is False
    assert resistance == prior_max_high
    assert support == prior_min_low


def test_lookback_parameter():
    df = _make_bars(30)
    _, _, r5, s5 = detect_failed_breakout(df, lookback=5)
    _, _, r20, s20 = detect_failed_breakout(df, lookback=20)

    assert r5 <= r20 or s5 >= s20


def test_close_at_high():
    row = {"high": 110.0, "low": 100.0, "close": 110.0}
    assert close_strength(row) == 1.0


def test_close_at_low():
    row = {"high": 110.0, "low": 100.0, "close": 100.0}
    assert close_strength(row) == 0.0


def test_close_midrange():
    row = {"high": 110.0, "low": 100.0, "close": 105.0}
    assert close_strength(row) == 0.5


def test_zero_range_bar():
    row = {"high": 100.0, "low": 100.0, "close": 100.0}
    assert close_strength(row) == 0.5


def test_normal_range():
    assert range_expansion(110.0, 100.0, 10.0) == 1.0


def test_wide_range():
    assert range_expansion(120.0, 100.0, 10.0) == 2.0


def test_zero_atr():
    assert range_expansion(110.0, 100.0, 0.0) == 1.0


def test_nan_atr():
    assert range_expansion(110.0, 100.0, float("nan")) == 1.0


def test_failed_breakout_bearish():
    score, label = compute_context_score(
        failed_breakout=True, failed_breakdown=False,
        close_str=0.2, range_exp=1.0,
    )
    assert score < -0.2
    assert label == "bearish"


def test_strong_close_bullish():
    score, label = compute_context_score(
        failed_breakout=False, failed_breakdown=False,
        close_str=0.9, range_exp=1.0,
    )
    assert score > 0.2
    assert label == "bullish"


def test_neutral_conditions():
    score, label = compute_context_score(
        failed_breakout=False, failed_breakdown=False,
        close_str=0.5, range_exp=1.0,
    )
    assert -0.2 <= score <= 0.2
    assert label == "neutral"


def test_failed_breakdown_recovery_bullish():
    score, label = compute_context_score(
        failed_breakout=False, failed_breakdown=True,
        close_str=0.8, range_exp=1.0,
    )
    assert score > 0.0
    assert label == "bullish"


def test_score_clamped():
    score_low, _ = compute_context_score(True, False, 0.0, 3.0)
    score_high, _ = compute_context_score(False, True, 1.0, 0.5)
    assert score_low >= -1.0
    assert score_high <= 1.0


def test_compute_daily_context_all_keys():
    df = _make_bars(30)
    ctx = compute_daily_context(df)

    expected_keys = {
        "failed_breakout", "failed_breakdown", "close_strength",
        "range_expansion", "resistance", "support",
        "context_score", "context_label",
    }
    assert set(ctx.keys()) == expected_keys
    assert isinstance(ctx["failed_breakout"], bool)
    assert isinstance(ctx["context_score"], float)
    assert ctx["context_label"] in ("bullish", "bearish", "neutral")


def test_short_dataframe():
    df = _make_bars(3)
    ctx = compute_daily_context(df, lookback=20)

    assert "context_score" in ctx
    assert -1.0 <= ctx["context_score"] <= 1.0


def test_serializable():
    df = _make_bars(30)
    ctx = compute_daily_context(df)
    serialized = json.dumps(ctx)
    assert isinstance(serialized, str)


def test_breakout_accepted():
    df = _make_intraday_bars(n=30, start_price=100.0, trend=0.0)
    resistance = 101.0
    df.loc[df.index[-6:], "close"] = resistance + 0.5
    df.loc[df.index[-6:], "high"] = resistance + 0.8
    df.loc[df.index[-6:], "low"] = resistance + 0.2

    result = compute_intraday_confirmation(df, resistance=resistance)

    assert result["breakout_accepted"] is True


def test_breakout_not_accepted():
    df = _make_intraday_bars(n=30, start_price=100.0, trend=0.0)
    resistance = 101.0
    df["close"] = resistance - 0.2
    df.loc[df.index[-2:], "high"] = resistance + 0.5
    df.loc[df.index[-2:], "close"] = resistance + 0.1

    result = compute_intraday_confirmation(df, resistance=resistance)

    assert result["breakout_accepted"] is False


def test_volume_confirmed():
    df = _make_intraday_bars(n=30, start_price=100.0, trend=0.0)
    resistance = 101.0
    df["high"] = resistance - 0.5
    df["close"] = resistance - 0.7
    df["volume"] = 1000
    df.loc[df.index[20], "high"] = resistance + 0.5
    df.loc[df.index[20], "close"] = resistance + 0.2
    df.loc[df.index[20], "volume"] = 3001

    result = compute_intraday_confirmation(df, resistance=resistance)

    assert result["volume_confirmed"] is True


def test_volume_not_confirmed():
    df = _make_intraday_bars(n=30, start_price=100.0, trend=0.0)
    resistance = 101.0
    df["high"] = resistance - 0.5
    df["close"] = resistance - 0.7
    df["volume"] = 1000
    df.loc[df.index[20], "high"] = resistance + 0.5
    df.loc[df.index[20], "close"] = resistance + 0.2

    result = compute_intraday_confirmation(df, resistance=resistance)

    assert result["volume_confirmed"] is False


def test_intraday_trend_up():
    df = _make_intraday_bars(n=30, start_price=100.0, trend=0.0)
    prices = np.linspace(100.0, 110.0, len(df))
    df["close"] = prices
    df["high"] = prices + 0.5
    df["low"] = prices - 0.5

    result = compute_intraday_confirmation(df, resistance=120.0)

    assert result["intraday_trend"] == "up"


def test_intraday_trend_down():
    df = _make_intraday_bars(n=30, start_price=100.0, trend=0.0)
    prices = np.linspace(110.0, 100.0, len(df))
    df["close"] = prices
    df["high"] = prices + 0.5
    df["low"] = prices - 0.5

    result = compute_intraday_confirmation(df, resistance=120.0)

    assert result["intraday_trend"] == "down"


def test_close_trajectory_rising():
    df = _make_intraday_bars(n=30, start_price=100.0, trend=0.0)
    tail_prices = np.linspace(100.0, 104.0, 6)
    df.loc[df.index[-6:], "close"] = tail_prices
    df.loc[df.index[-6:], "high"] = tail_prices + 0.5
    df.loc[df.index[-6:], "low"] = tail_prices - 0.5

    result = compute_intraday_confirmation(df, resistance=120.0)

    assert result["close_trajectory"] == "rising"


def test_close_trajectory_falling():
    df = _make_intraday_bars(n=30, start_price=100.0, trend=0.0)
    tail_prices = np.linspace(104.0, 100.0, 6)
    df.loc[df.index[-6:], "close"] = tail_prices
    df.loc[df.index[-6:], "high"] = tail_prices + 0.5
    df.loc[df.index[-6:], "low"] = tail_prices - 0.5

    result = compute_intraday_confirmation(df, resistance=120.0)

    assert result["close_trajectory"] == "falling"


def test_confirmation_score_range():
    for trend in (-0.002, 0.0, 0.002):
        df = _make_intraday_bars(n=78, start_price=100.0, trend=trend)
        result = compute_intraday_confirmation(df, resistance=101.0)
        assert 0.0 <= result["confirmation_score"] <= 1.0


def test_empty_dataframe():
    df = pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])
    result = compute_intraday_confirmation(df, resistance=105.0)

    assert result["confirmation_score"] == 0.0
    assert result["breakout_accepted"] is False
    assert result["intraday_trend"] == "mixed"


def test_confirmation_serializable():
    df = _make_intraday_bars(n=30)
    result = compute_intraday_confirmation(df, resistance=101.0)
    serialized = json.dumps(result)

    assert isinstance(serialized, str)
