"""NYSE holiday calendar and warning helpers."""
from __future__ import annotations

import datetime as _dt
from typing import Dict, Optional, Set

from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USLaborDay,
    USMartinLutherKingJr,
    USMemorialDay,
    USPresidentsDay,
    USThanksgivingDay,
    nearest_workday,
)

__all__ = [
    "NYSEHolidayCalendar",
    "nyse_holidays_for_year",
    "get_holiday_warning",
]


class NYSEHolidayCalendar(AbstractHolidayCalendar):
    """NYSE-observed holidays (10 per year)."""

    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=nearest_workday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, observance=nearest_workday, start_date="2022-01-01"),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


_nyse_calendar = NYSEHolidayCalendar()
_nyse_holiday_cache: Dict[int, Set[_dt.date]] = {}


def nyse_holidays_for_year(year: int) -> Set[_dt.date]:
    """Return the set of NYSE holiday dates for *year* (cached)."""
    if year not in _nyse_holiday_cache:
        start = _dt.datetime(year, 1, 1)
        end = _dt.datetime(year, 12, 31)
        holidays = _nyse_calendar.holidays(start=start, end=end)
        _nyse_holiday_cache[year] = {d.date() for d in holidays}
    return _nyse_holiday_cache[year]


def get_holiday_warning(today: Optional[_dt.date] = None) -> Optional[Dict]:
    """
    Check if an NYSE holiday falls in the current Mon-Fri week.

    Returns a dict with holiday info if a warning should be shown, or None.

    Rules:
    - Only warns about holidays from today through end of the week (not past days).
    - Skips if today IS the holiday (market is closed, nothing actionable).
    - Skips if today is Saturday or Sunday.

    Returns:
        {
            "holiday_name": str,
            "holiday_date": datetime.date,
            "holiday_weekday": str,
            "today_weekday": str,
            "message": str,
        }
        or None
    """
    if today is None:
        today = _dt.date.today()

    if today.weekday() >= 5:
        return None

    monday = today - _dt.timedelta(days=today.weekday())
    friday = monday + _dt.timedelta(days=4)
    holidays = nyse_holidays_for_year(today.year)
    if monday.year != friday.year:
        holidays = holidays | nyse_holidays_for_year(friday.year)

    tomorrow = today + _dt.timedelta(days=1)
    for day_offset in range((friday - tomorrow).days + 1):
        check_date = tomorrow + _dt.timedelta(days=day_offset)
        if check_date in holidays:
            year = check_date.year
            start = _dt.datetime(year, 1, 1)
            end = _dt.datetime(year, 12, 31)
            cal_holidays = _nyse_calendar.holidays(start=start, end=end, return_name=True)
            holiday_name = "NYSE Holiday"
            for h_date, h_name in cal_holidays.items():
                if h_date.date() == check_date:
                    holiday_name = h_name
                    break

            weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            return {
                "holiday_name": holiday_name,
                "holiday_date": check_date,
                "holiday_weekday": weekday_names[check_date.weekday()],
                "today_weekday": weekday_names[today.weekday()],
                "message": (
                    f"NYSE is closed {weekday_names[check_date.weekday()]} "
                    f"({check_date.strftime('%b %d')}) for {holiday_name}. "
                    "Adjust hold periods accordingly."
                ),
            }

    return None
