"""Unit tests for weekend flattening and deadline awareness."""

from __future__ import annotations

# pylint: disable=missing-function-docstring

from datetime import date, datetime
from zoneinfo import ZoneInfo

from bh_ftmo.backtest.risk_exits import DeadlineState, deadline_check, weekend_flatten_events
from bh_ftmo.backtest.types import Position

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")



def _utc_from_ny(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=NY).astimezone(UTC).replace(tzinfo=None)



def _positions() -> list[Position]:
    return [
        Position(1, "EUR_USD", "baseline", 1, datetime(2026, 4, 25, 8, 0), 1.10, 1.09, 1.12, 1.0),
        Position(2, "USD_JPY", "baseline", -1, datetime(2026, 4, 25, 8, 0), 150.0, 150.5, 149.0, 1.0),
    ]



def test_weekend_flatten_emitted_at_friday_13_ny_with_4h_window():
    ts = _utc_from_ny(2026, 4, 24, 13, 0)
    events = weekend_flatten_events(
        _positions(),
        ts,
        {"EUR_USD": 1.1010, "USD_JPY": 149.8},
        {"EUR_USD": 1.1012, "USD_JPY": 149.82},
        {"weekend_flatten_hours_before_close": 4},
    )
    assert len(events) == 2
    assert events[0].kind == "weekend_flatten"



def test_weekend_flatten_not_emitted_before_window():
    ts = _utc_from_ny(2026, 4, 24, 12, 59)
    events = weekend_flatten_events(
        _positions(),
        ts,
        {"EUR_USD": 1.1010, "USD_JPY": 149.8},
        {"EUR_USD": 1.1012, "USD_JPY": 149.82},
        {"weekend_flatten_hours_before_close": 4},
    )
    assert not events



def test_weekend_flatten_not_emitted_on_thursday():
    ts = _utc_from_ny(2026, 4, 23, 13, 0)
    events = weekend_flatten_events(
        _positions(),
        ts,
        {"EUR_USD": 1.1010, "USD_JPY": 149.8},
        {"EUR_USD": 1.1012, "USD_JPY": 149.82},
        {"weekend_flatten_hours_before_close": 4},
    )
    assert not events



def test_weekend_flatten_works_in_spring_forward_week():
    ts = _utc_from_ny(2026, 3, 13, 13, 0)
    events = weekend_flatten_events(
        _positions(),
        ts,
        {"EUR_USD": 1.1010, "USD_JPY": 149.8},
        {"EUR_USD": 1.1012, "USD_JPY": 149.82},
        {"weekend_flatten_hours_before_close": 4},
    )
    assert len(events) == 2



def test_weekend_flatten_works_in_fall_back_week():
    ts = _utc_from_ny(2026, 11, 6, 13, 0)
    events = weekend_flatten_events(
        _positions(),
        ts,
        {"EUR_USD": 1.1010, "USD_JPY": 149.8},
        {"EUR_USD": 1.1012, "USD_JPY": 149.82},
        {"weekend_flatten_hours_before_close": 4},
    )
    assert len(events) == 2



def test_deadline_check_transitions():
    ts = datetime(2026, 4, 25, 12, 0)
    assert deadline_check(ts, date(2026, 5, 5), {}) == DeadlineState.NORMAL
    assert deadline_check(ts, date(2026, 4, 30), {}) == DeadlineState.TIGHTENED
    assert deadline_check(ts, date(2026, 4, 27), {}) == DeadlineState.NO_NEW_ENTRIES
    assert deadline_check(ts, date(2026, 4, 25), {}) == DeadlineState.HARD_FLATTEN
    assert deadline_check(ts, date(2026, 4, 24), {}) == DeadlineState.HARD_FLATTEN



def test_deadline_check_none_deadline_is_normal():
    assert deadline_check(datetime(2026, 4, 25, 12, 0), None, {}) == DeadlineState.NORMAL
