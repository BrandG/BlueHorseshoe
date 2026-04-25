"""Unit tests for the calendar-provider seam."""

from __future__ import annotations

# pylint: disable=missing-function-docstring

from datetime import datetime

from bh_ftmo.backtest.calendar_provider import CalendarProvider, NullCalendarProvider


class FakeCalendarProvider:
    """Small fake used to prove the protocol shape is sufficient."""

    def is_blackout(self, ts: datetime, currencies: set[str]) -> bool:
        del ts, currencies
        return True

    def next_blackout_end(self, ts: datetime, currencies: set[str]) -> datetime | None:
        del currencies
        return ts



def test_null_calendar_provider_never_blocks():
    provider = NullCalendarProvider()
    ts = datetime(2026, 4, 25, 12, 0)
    assert provider.is_blackout(ts, {"USD", "JPY"}) is False
    assert provider.next_blackout_end(ts, {"USD", "JPY"}) is None



def test_protocol_shape_is_satisfied():
    provider: CalendarProvider = FakeCalendarProvider()
    ts = datetime(2026, 4, 25, 12, 0)
    assert provider.is_blackout(ts, {"USD"}) is True
    assert provider.next_blackout_end(ts, {"USD"}) == ts
