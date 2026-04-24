"""Tests for bh_ftmo.indicators.sessions."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from bh_ftmo.indicators import (
    SESSION_HOURS,
    Session,
    ohlc_mid,
    session_label,
    session_ranges,
)

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _ny(*args) -> datetime:
    return datetime(*args, tzinfo=NY).astimezone(UTC).replace(tzinfo=None)


# ---- session_label: boundary cases -------------------------------------


@pytest.mark.parametrize(
    "ny_hour,expected",
    [
        (17, Session.ASIA),
        (20, Session.ASIA),
        (23, Session.ASIA),
        (0,  Session.ASIA),
        (1,  Session.ASIA),
        (2,  Session.ASIA),
        (3,  Session.LONDON),
        (7,  Session.LONDON),
        (8,  Session.OVERLAP),
        (11, Session.OVERLAP),
        (12, Session.NY),
        (16, Session.NY),
    ],
)
def test_session_label_boundaries_midweek(ny_hour, expected):
    # Use Tuesday 2025-03-11 (market open all day); test each NY hour
    ts = pd.Series([_ny(2025, 3, 11, ny_hour)])
    labels = session_label(ts)
    assert labels.iloc[0] == expected


def test_session_label_weekend_is_closed():
    # Saturday morning NY → market closed
    ts = pd.Series([_ny(2025, 3, 8, 10)])
    assert session_label(ts).iloc[0] == Session.CLOSED


def test_session_label_sunday_before_open_is_closed():
    ts = pd.Series([_ny(2025, 3, 9, 16, )])  # Sun 4pm NY (open at 5pm)
    assert session_label(ts).iloc[0] == Session.CLOSED


def test_session_label_sunday_5pm_opens_asia():
    ts = pd.Series([_ny(2025, 3, 9, 17)])
    assert session_label(ts).iloc[0] == Session.ASIA


def test_session_label_friday_5pm_closes():
    ts = pd.Series([_ny(2025, 3, 14, 17)])
    assert session_label(ts).iloc[0] == Session.CLOSED


def test_session_label_dst_spring_forward():
    """DST transition: 08:00 NY is OVERLAP in EDT just as it is in EST."""
    # Saturday DST transition (spring forward): Sunday 2025-03-09 at 2am becomes 3am NY
    # But we test Mon Mar 10 8am NY (post-spring-forward, EDT)
    ts = pd.Series([_ny(2025, 3, 10, 8)])  # EDT
    assert session_label(ts).iloc[0] == Session.OVERLAP
    # And Mon Feb 3 8am NY (before spring-forward, EST)
    ts = pd.Series([_ny(2025, 2, 3, 8)])  # EST
    assert session_label(ts).iloc[0] == Session.OVERLAP


def test_session_label_accepts_custom_hours():
    custom = {
        Session.ASIA: (0, 6),
        Session.LONDON: (6, 12),
        Session.OVERLAP: (12, 14),
        Session.NY: (14, 24),
    }
    ts = pd.Series([_ny(2025, 3, 11, 13)])  # NY 1pm → OVERLAP by custom def
    assert session_label(ts, hours=custom).iloc[0] == Session.OVERLAP


# ---- session_ranges ---------------------------------------------------


def test_session_ranges_aggregates_per_session():
    # Monday 2025-03-10: simulate one bar in each of ASIA/LONDON/OVERLAP/NY
    # NY hours 1 (ASIA), 5 (LONDON), 9 (OVERLAP), 13 (NY)
    ts = pd.Series([
        _ny(2025, 3, 10, 1),   # ASIA
        _ny(2025, 3, 10, 5),   # LONDON
        _ny(2025, 3, 10, 9),   # OVERLAP
        _ny(2025, 3, 10, 13),  # NY
    ])
    ohlc = pd.DataFrame({
        "open":  [1.0, 2.0, 3.0, 4.0],
        "high":  [1.1, 2.2, 3.3, 4.4],
        "low":   [0.9, 1.8, 2.7, 3.6],
        "close": [1.05, 2.1, 3.15, 4.2],
    })
    ranges = session_ranges(ohlc, timestamps=ts)
    # One row per session
    assert len(ranges) == 4
    # Asia: open=1.0, high=1.1, low=0.9, close=1.05
    asia = ranges.loc[(date(2025, 3, 10), "asia")]
    assert asia["open"] == pytest.approx(1.0)
    assert asia["high"] == pytest.approx(1.1)
    assert asia["close"] == pytest.approx(1.05)


def test_session_ranges_multi_bar_per_session():
    # Three bars all in ASIA on the same day
    ts = pd.Series([
        _ny(2025, 3, 10, 17),
        _ny(2025, 3, 10, 21),
        _ny(2025, 3, 11, 1),  # NOTE: this is Mar 11 in NY! 1am on the 11th
    ])
    ohlc = pd.DataFrame({
        "open":  [1.0, 2.0, 3.0],
        "high":  [1.5, 2.5, 3.5],
        "low":   [0.5, 1.5, 2.5],
        "close": [1.2, 2.2, 3.2],
    })
    ranges = session_ranges(ohlc, timestamps=ts)
    # First 2 bars belong to Mar 10 ASIA; third bar to Mar 11 ASIA
    mar10_asia = ranges.loc[(date(2025, 3, 10), "asia")]
    assert mar10_asia["open"] == 1.0    # first
    assert mar10_asia["high"] == 2.5    # max of 1.5, 2.5
    assert mar10_asia["low"] == 0.5     # min
    assert mar10_asia["close"] == 2.2   # last
    mar11_asia = ranges.loc[(date(2025, 3, 11), "asia")]
    assert mar11_asia["open"] == 3.0


def test_session_ranges_excludes_closed():
    ts = pd.Series([
        _ny(2025, 3, 8, 10),   # Saturday → CLOSED
        _ny(2025, 3, 10, 9),   # Monday OVERLAP
    ])
    ohlc = pd.DataFrame({
        "open":  [99, 1.0],
        "high":  [99, 1.1],
        "low":   [99, 0.9],
        "close": [99, 1.05],
    })
    ranges = session_ranges(ohlc, timestamps=ts)
    # Only the Monday OVERLAP bar should appear
    assert len(ranges) == 1
    assert (date(2025, 3, 10), "overlap") in ranges.index


def test_session_ranges_rejects_length_mismatch():
    ohlc = pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1]})
    ts = pd.Series([_ny(2025, 3, 10, 1), _ny(2025, 3, 10, 5)])
    with pytest.raises(ValueError, match="length"):
        session_ranges(ohlc, timestamps=ts)


# ---- integration: real EUR_USD data -----------------------------------


def test_sessions_on_fxstore_data():
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
        pytest.skip("fx_4h.duckdb EUR_USD slice too short")

    ohlc = ohlc_mid(df)
    labels = session_label(df["timestamp"])
    ranges = session_ranges(ohlc, timestamps=df["timestamp"])

    # Each bar gets a label
    assert len(labels) == len(df)
    # All labels should be valid
    assert labels.isin([s.value for s in Session] + list(Session)).all()
    # Every non-weekend bar should NOT be CLOSED
    open_count = (labels != Session.CLOSED).sum()
    assert open_count == len(df), "FxStore should not contain CLOSED bars"

    # Range DataFrame should have the usual 4 sessions represented across Jan 2025
    sessions_seen = ranges.index.get_level_values("session").unique()
    assert set(sessions_seen) == {"asia", "london", "overlap", "ny"}
