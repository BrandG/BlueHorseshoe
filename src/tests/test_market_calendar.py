"""Tests for NYSE holiday calendar helpers."""

import datetime as dt

from bluehorseshoe.core.market_calendar import (
    get_holiday_warning,
    nyse_holidays_for_year,
    trading_days_after,
)


class TestTradingDaysAfter:
    """Coverage for the calendar-based trading-day counter."""

    def test_counts_weekdays_excluding_weekends(self):
        # Mon 2026-06-01 -> Fri 2026-06-05 inclusive is 4 sessions *after* Mon.
        assert trading_days_after("2026-06-01", "2026-06-05") == 4

    def test_excludes_nyse_holidays(self):
        # Span includes Memorial Day (Mon 2026-05-25). Tue–Fri = 4 sessions.
        assert trading_days_after("2026-05-22", "2026-05-29") == 4

    def test_strictly_after_start(self):
        # Same day, and end before start, both yield 0.
        assert trading_days_after("2026-06-01", "2026-06-01") == 0
        assert trading_days_after("2026-06-05", "2026-06-01") == 0

    def test_skips_weekend_only_span(self):
        # Sat 2026-06-06 -> Sun 2026-06-07: no sessions.
        assert trading_days_after("2026-06-06", "2026-06-07") == 0

    def test_does_not_depend_on_price_store(self):
        # Maturity must be judgeable far past any stale OHLCV: ~21 sessions in a month.
        assert trading_days_after("2026-04-08", "2026-05-08") >= 20


class TestGetHolidayWarning:
    """Coverage for holiday warning generation."""

    def test_thursday_before_good_friday_warns(self):
        """Warn on the trading day immediately before Good Friday."""
        result = get_holiday_warning(dt.date(2025, 4, 17))

        assert result is not None
        assert result["holiday_name"] == "Good Friday"
        assert result["holiday_date"] == dt.date(2025, 4, 18)
        assert result["holiday_weekday"] == "Friday"
        assert result["today_weekday"] == "Thursday"
        assert result["message"] == (
            "NYSE is closed Friday (Apr 18) for Good Friday. "
            "Adjust hold periods accordingly."
        )

    def test_monday_before_future_friday_holiday_warns(self):
        """Warn earlier in the same week when the holiday is still ahead."""
        result = get_holiday_warning(dt.date(2025, 4, 14))

        assert result is not None
        assert result["holiday_name"] == "Good Friday"
        assert result["holiday_date"] == dt.date(2025, 4, 18)

    def test_holiday_itself_returns_none(self):
        """Do not warn on the holiday itself."""
        assert get_holiday_warning(dt.date(2025, 4, 18)) is None

    def test_day_after_monday_holiday_returns_none(self):
        """Do not warn when the relevant holiday has already passed."""
        assert get_holiday_warning(dt.date(2025, 5, 27)) is None

    def test_saturday_returns_none(self):
        """Weekend dates should not emit warnings."""
        assert get_holiday_warning(dt.date(2025, 4, 12)) is None
        assert get_holiday_warning(dt.date(2025, 4, 13)) is None

    def test_default_today_uses_real_date(self):
        """Defaulting to the real current date should not raise."""
        get_holiday_warning()


class TestNyseHolidaysForYear:
    """Coverage for holiday lookup and caching."""

    def test_2025_includes_good_friday(self):
        """Good Friday should be present."""
        holidays = nyse_holidays_for_year(2025)

        assert dt.date(2025, 4, 18) in holidays

    def test_2025_includes_thanksgiving(self):
        """Thanksgiving should be present in the 2025 calendar."""
        holidays = nyse_holidays_for_year(2025)

        assert dt.date(2025, 11, 27) in holidays

    def test_caching(self):
        """Repeated calls should reuse the cached mapping."""
        a = nyse_holidays_for_year(2025)
        b = nyse_holidays_for_year(2025)

        assert a is b
