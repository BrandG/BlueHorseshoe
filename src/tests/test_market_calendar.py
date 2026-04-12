"""Tests for NYSE holiday calendar helpers."""

import datetime as dt

from bluehorseshoe.core.market_calendar import (
    get_holiday_warning,
    nyse_holidays_for_year,
)


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
