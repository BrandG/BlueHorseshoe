"""Tests for bud.briefing D1-alignment + session annotations (pure logic).

These cover the annotate-only filter findings wired in 2026-05-31: each fire is
tagged with-trend/counter-trend vs the daily bar (MULTITF_FILTER_v1.md) and with
its forex session (SESSION_FILTER_v1.md). Nothing is suppressed.
"""
import pandas as pd

from bud.briefing import (
    NEG_COUNTER_TREND_STRATEGIES,
    d1_alignment,
    session_of,
)


def _h4_day(opens_closes, date="2026-05-28"):
    """Build a one-NY-day H4 mid frame from (open, close) pairs.

    Timestamps are UTC H4 bar opens; high/low are derived loosely. The daily
    open = first bar open, daily close = last bar close (per daily_ohlc).
    """
    rows = []
    for i, (o, c) in enumerate(opens_closes):
        # Start at 12:00 UTC so 4h-spaced bars (12/16/20 UTC = 08/12/16 NY) all
        # land on the same NY calendar date — NY = UTC-4 rolls the date at 04:00 UTC.
        ts = pd.Timestamp(f"{date} {i*4 + 12:02d}:00:00")
        rows.append({"open": o, "high": max(o, c) + 0.01,
                     "low": min(o, c) - 0.01, "close": c, "timestamp": ts})
    df = pd.DataFrame(rows)
    mid = df[["open", "high", "low", "close"]]
    return mid, df["timestamp"]


def test_d1_up_day_long_is_with_trend():
    # day closes well above its open → daily bar is "long"
    mid, ts = _h4_day([(1.10, 1.11), (1.11, 1.12), (1.12, 1.15)])
    assert d1_alignment(mid, ts, "long") == "with-trend"
    assert d1_alignment(mid, ts, "short") == "counter-trend"


def test_d1_down_day_short_is_with_trend():
    mid, ts = _h4_day([(1.15, 1.14), (1.14, 1.12), (1.12, 1.10)])
    assert d1_alignment(mid, ts, "short") == "with-trend"
    assert d1_alignment(mid, ts, "long") == "counter-trend"


def test_d1_doji_day_is_flat():
    # daily open == daily close → flat, never with/counter
    mid, ts = _h4_day([(1.10, 1.12), (1.12, 1.08), (1.08, 1.10)])
    assert d1_alignment(mid, ts, "long") == "flat"
    assert d1_alignment(mid, ts, "short") == "flat"


def test_d1_uses_only_the_latest_day():
    # an up prior day followed by a down current day → classify on the current day
    mid_prior, ts_prior = _h4_day([(1.10, 1.20)], date="2026-05-27")
    mid_curr, ts_curr = _h4_day([(1.20, 1.19), (1.19, 1.15)], date="2026-05-28")
    mid = pd.concat([mid_prior, mid_curr], ignore_index=True)
    ts = pd.concat([ts_prior, ts_curr], ignore_index=True)
    assert d1_alignment(mid, ts, "short") == "with-trend"


def test_d1_empty_is_flat_not_raise():
    empty = pd.DataFrame(columns=["open", "high", "low", "close"])
    assert d1_alignment(empty, pd.Series([], dtype="datetime64[ns]"), "long") == "flat"


def test_session_overlap_and_ny():
    # 2026-05-28 is a Thursday (forex open); May → NY is UTC-4 (EDT).
    # 14:00 UTC → 10:00 NY → OVERLAP (08–12 NY)
    assert session_of(pd.Timestamp("2026-05-28 14:00:00")) == "overlap"
    # 20:00 UTC → 16:00 NY → NY (12–17 NY)
    assert session_of(pd.Timestamp("2026-05-28 20:00:00")) == "ny"
    # 02:00 UTC → 22:00 NY prior day → ASIA (17–03 NY, wraps midnight)
    assert session_of(pd.Timestamp("2026-05-28 02:00:00")) == "asia"


def test_negative_counter_trend_set_matches_research():
    # ATR (both entry modes) + candlestick mid are the negative-counter-trend
    # indicators per MULTITF_FILTER_v1.md. Both briefing families are covered.
    assert "atr" in NEG_COUNTER_TREND_STRATEGIES
    assert "candle" in NEG_COUNTER_TREND_STRATEGIES
    # mean-reversion families are NOT flagged (counter-trend still positive R)
    assert "stoch" not in NEG_COUNTER_TREND_STRATEGIES
    assert "macd" not in NEG_COUNTER_TREND_STRATEGIES
