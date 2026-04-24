"""Tests for bh_ftmo.data.fx_time_utils — time/DST/holiday rules per FX_TIME_SPEC.md."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from bh_ftmo.data.fx_time_utils import (
    BarGap,
    BarGapKind,
    classify_gaps,
    expected_h1_bar_opens,
    expected_h4_bar_opens,
    floor_to_h4,
    is_forex_open,
    is_uk_market_holiday,
    is_us_market_holiday,
    ny_calendar_day,
    prior_forex_day,
    week_close,
    week_open,
)

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _utc(*args, **kwargs) -> datetime:
    """Helper: build a naive-UTC datetime."""
    return datetime(*args, **kwargs)


def _ny(*args, **kwargs) -> datetime:
    """Helper: build an NY-local-aware datetime, return its naive-UTC equivalent."""
    return datetime(*args, **kwargs, tzinfo=NY).astimezone(UTC).replace(tzinfo=None)


# ---- is_forex_open ------------------------------------------------------


def test_monday_noon_is_open():
    assert is_forex_open(_ny(2025, 3, 10, 12, 0)) is True


def test_saturday_is_closed():
    assert is_forex_open(_ny(2025, 3, 8, 10, 0)) is False


def test_sunday_before_5pm_is_closed():
    assert is_forex_open(_ny(2025, 3, 9, 16, 59)) is False


def test_sunday_5pm_is_open():
    assert is_forex_open(_ny(2025, 3, 9, 17, 0)) is True


def test_friday_before_5pm_is_open():
    assert is_forex_open(_ny(2025, 3, 14, 16, 59)) is True


def test_friday_5pm_is_closed():
    assert is_forex_open(_ny(2025, 3, 14, 17, 0)) is False


# ---- week_open / week_close ---------------------------------------------


def test_week_open_from_mid_week():
    # Wednesday 3pm NY → week open is the previous Sunday 5pm NY
    got = week_open(_ny(2025, 3, 12, 15, 0))
    assert got == _ny(2025, 3, 9, 17, 0)


def test_week_open_from_sunday_before_open():
    # Sunday 4pm NY → week open is the PREVIOUS Sunday (week hasn't started yet)
    got = week_open(_ny(2025, 3, 9, 16, 0))
    assert got == _ny(2025, 3, 2, 17, 0)


def test_week_close_from_mid_week():
    got = week_close(_ny(2025, 3, 12, 15, 0))
    assert got == _ny(2025, 3, 14, 17, 0)


# ---- floor_to_h4 --------------------------------------------------------


@pytest.mark.parametrize(
    "ny_dt,expected_open",
    [
        ((2025, 3, 10, 17, 0), (2025, 3, 10, 17, 0)),  # exactly on open
        ((2025, 3, 10, 20, 59), (2025, 3, 10, 17, 0)),  # inside 17-21 bar
        ((2025, 3, 10, 21, 0), (2025, 3, 10, 21, 0)),
        ((2025, 3, 11, 0, 30), (2025, 3, 10, 21, 0)),  # past midnight, still inside 21-01 bar
        ((2025, 3, 11, 1, 0), (2025, 3, 11, 1, 0)),
        ((2025, 3, 11, 13, 0), (2025, 3, 11, 13, 0)),
        ((2025, 3, 11, 16, 59), (2025, 3, 11, 13, 0)),
    ],
)
def test_floor_to_h4(ny_dt, expected_open):
    assert floor_to_h4(_ny(*ny_dt)) == _ny(*expected_open)


# ---- expected_h4_bar_opens ----------------------------------------------


def test_expected_h4_bars_normal_week_count():
    # Sun 5pm NY 2025-03-09 through Fri 5pm NY 2025-03-14 = 30 bars
    start = _ny(2025, 3, 9, 17, 0)
    end = _ny(2025, 3, 14, 17, 0)
    bars = expected_h4_bar_opens(start, end)
    assert len(bars) == 30
    assert bars[0] == start
    # Last bar opens 4h before Fri 5pm NY = Fri 1pm NY
    assert bars[-1] == _ny(2025, 3, 14, 13, 0)


def test_expected_h4_bars_skips_weekend():
    # Fri 4pm NY through Sun 6pm NY: Fri 1pm and Sun 5pm bars qualify, weekend skipped.
    start = _ny(2025, 3, 14, 16, 0)
    end = _ny(2025, 3, 9 + 7, 18, 0)  # Sun 3/16 6pm NY
    bars = expected_h4_bar_opens(start, end)
    # Fri 13:00 NY is already in the bar (started before start, but floor pulls us back).
    # Actually expected is only 1 bar: Sun 5pm (the next valid open after start).
    # Fri 16:00 > floor_to_h4(=Fri 13:00), but we advance to next bar = Fri 17:00 which is CLOSED (week close).
    # So only Sun 5pm matches.
    assert _ny(2025, 3, 16, 17, 0) in bars
    # No Saturday bars
    for b in bars:
        ny_dt = b.replace(tzinfo=UTC).astimezone(NY)
        assert ny_dt.weekday() != 5


def test_expected_h4_bars_spring_forward_crosses_dst():
    """Week crossing US spring-forward (2025-03-09) — Monday bars must be in EDT UTC."""
    start = _ny(2025, 3, 9, 17, 0)  # Sun 5pm NY, still EDT starting here
    end = _ny(2025, 3, 10, 17, 1)
    bars = expected_h4_bar_opens(start, end)
    # Sun 5pm NY EDT = 21:00 UTC
    assert bars[0] == datetime(2025, 3, 9, 21, 0)
    # Mon 1pm NY EDT = 17:00 UTC
    assert _ny(2025, 3, 10, 13, 0) in bars
    # All Monday bars should be at EDT-aligned UTC hours {21, 1, 5, 9, 13, 17}
    edt_utc_hours = {21, 1, 5, 9, 13, 17}
    for b in bars:
        assert b.hour in edt_utc_hours


def test_expected_h4_bars_fall_back_crosses_dst():
    """Week crossing US fall-back (2025-11-02) — Monday bars must be in EST UTC."""
    # Sunday Nov 2 2025 is the fall-back Sunday. Forex reopens Sun 5pm NY which is now EST.
    start = _ny(2025, 11, 2, 17, 0)
    end = _ny(2025, 11, 3, 17, 1)
    bars = expected_h4_bar_opens(start, end)
    # Sun 5pm NY EST = 22:00 UTC
    assert bars[0] == datetime(2025, 11, 2, 22, 0)
    est_utc_hours = {22, 2, 6, 10, 14, 18}
    for b in bars:
        assert b.hour in est_utc_hours


# ---- expected_h1_bar_opens ---------------------------------------------


def test_expected_h1_bars_normal_day_count():
    # Sun 5pm NY through Mon 5pm NY = 24 H1 bars
    start = _ny(2025, 3, 9, 17, 0)
    end = _ny(2025, 3, 10, 17, 0)
    bars = expected_h1_bar_opens(start, end)
    assert len(bars) == 24


# ---- ny_calendar_day / prior_forex_day ---------------------------------


def test_ny_calendar_day_basic():
    # Monday 01:00 NY = Sunday 05:00 UTC (during EDT)
    got = ny_calendar_day(_ny(2025, 3, 10, 1, 0))
    assert got == date(2025, 3, 10)


def test_prior_forex_day_skips_weekend():
    # Monday's prior forex day is Friday
    assert prior_forex_day(date(2025, 3, 10)) == date(2025, 3, 7)


def test_prior_forex_day_midweek():
    assert prior_forex_day(date(2025, 3, 12)) == date(2025, 3, 11)


def test_prior_forex_day_tuesday_after_monday_holiday_is_monday():
    """Forex stays open on US holidays so we do NOT skip them."""
    # MLK Day 2025 = Mon Jan 20. Tue Jan 21's prior forex day is Mon Jan 20.
    assert prior_forex_day(date(2025, 1, 21)) == date(2025, 1, 20)


# ---- holiday classifiers -----------------------------------------------


def test_is_us_market_holiday_christmas():
    assert is_us_market_holiday(date(2025, 12, 25)) is True


def test_is_us_market_holiday_thanksgiving():
    assert is_us_market_holiday(date(2025, 11, 27)) is True


def test_is_us_market_holiday_normal_day():
    assert is_us_market_holiday(date(2025, 11, 4)) is False


def test_is_us_market_holiday_ignores_weekends():
    assert is_us_market_holiday(date(2025, 11, 1)) is False  # Saturday


def test_is_uk_market_holiday_christmas():
    assert is_uk_market_holiday(date(2025, 12, 25)) is True


# ---- classify_gaps -----------------------------------------------------


def test_classify_gaps_empty_when_all_observed():
    start = _ny(2025, 3, 10, 17, 0)
    end = _ny(2025, 3, 10, 21, 1)
    expected = expected_h4_bar_opens(start, end)
    gaps = classify_gaps(expected, start_utc=start, end_utc=end)
    assert gaps == []


def test_classify_gaps_detects_data_gap():
    start = _ny(2025, 3, 10, 17, 0)
    end = _ny(2025, 3, 11, 17, 1)
    expected = expected_h4_bar_opens(start, end)
    # Drop one mid-week bar
    observed = [t for t in expected if t != expected[2]]
    gaps = classify_gaps(observed, start_utc=start, end_utc=end)
    assert len(gaps) == 1
    assert gaps[0].timestamp == expected[2]
    assert gaps[0].kind == BarGapKind.DATA_GAP


def test_classify_gaps_labels_us_holiday():
    # Thanksgiving 2025: Thursday Nov 27. Forex open, but XNYS closed.
    start = _ny(2025, 11, 27, 17, 0)
    end = _ny(2025, 11, 28, 17, 0)
    expected = expected_h4_bar_opens(start, end)
    gaps = classify_gaps([], start_utc=start, end_utc=end)
    assert len(gaps) == len(expected)
    # Bars dated Nov 27 NY are holiday; Nov 28 bars are the Friday session after holiday
    thanksgiving_gaps = [g for g in gaps if ny_calendar_day(g.timestamp) == date(2025, 11, 27)]
    assert thanksgiving_gaps, "expected some bars dated Thanksgiving NY"
    for g in thanksgiving_gaps:
        assert g.kind == BarGapKind.US_HOLIDAY


def test_classify_gaps_granularity_rejects_unknown():
    start = _ny(2025, 3, 10, 17, 0)
    end = _ny(2025, 3, 10, 18, 0)
    with pytest.raises(ValueError, match="granularity"):
        classify_gaps([], start_utc=start, end_utc=end, granularity="H8")  # type: ignore[arg-type]
