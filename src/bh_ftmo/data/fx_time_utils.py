"""FX time utilities — NY 5pm-anchored H4/H1 grid, forex-week boundaries, gap classification.

Implements `docs/planning/FX_TIME_SPEC.md`. Read that doc first. If the code and
the spec disagree, the spec wins.

Conventions:
  - All UTC timestamps are stored as tz-naive ``datetime`` at UTC wall-clock.
  - NY local time is the session anchor; UTC is the storage representation.
  - Forex week: Sun 5pm NY (inclusive) → Fri 5pm NY (exclusive).
  - H4 bars open at NY hours {17, 21, 1, 5, 9, 13}; close 4h later.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Iterable, Iterator, Literal, Optional
from zoneinfo import ZoneInfo

import exchange_calendars as ec

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
LONDON = ZoneInfo("Europe/London")

FOREX_WEEK_OPEN_HOUR_NY = 17  # Sun 5pm NY
FOREX_WEEK_CLOSE_HOUR_NY = 17  # Fri 5pm NY

H4_BAR_OPEN_HOURS_NY = (17, 21, 1, 5, 9, 13)

Granularity = Literal["H1", "H4"]


class BarGapKind(str, Enum):
    WEEKEND = "weekend"
    US_HOLIDAY = "us_holiday"
    UK_HOLIDAY = "uk_holiday"
    DATA_GAP = "data_gap"


@dataclass(frozen=True)
class BarGap:
    timestamp: datetime  # UTC, tz-naive
    kind: BarGapKind


# ---- Calendar handles (lazy-loaded; exchange_calendars cold-start is ~500ms) ---

_XNYS: Optional[ec.ExchangeCalendar] = None
_XLON: Optional[ec.ExchangeCalendar] = None


def _xnys() -> ec.ExchangeCalendar:
    global _XNYS
    if _XNYS is None:
        _XNYS = ec.get_calendar("XNYS")
    return _XNYS


def _xlon() -> ec.ExchangeCalendar:
    global _XLON
    if _XLON is None:
        _XLON = ec.get_calendar("XLON")
    return _XLON


# ---- Basic normalization ------------------------------------------------


def _as_naive_utc(dt: datetime) -> datetime:
    """Return a tz-naive UTC datetime. Accepts aware or naive-UTC input."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def _to_ny(dt_utc: datetime) -> datetime:
    """Convert a tz-naive UTC datetime to a tz-aware NY datetime."""
    return dt_utc.replace(tzinfo=UTC).astimezone(NY)


def _ny_to_utc(dt_ny: datetime) -> datetime:
    """Convert a tz-aware NY datetime to a tz-naive UTC datetime."""
    return dt_ny.astimezone(UTC).replace(tzinfo=None)


# ---- Forex-week boundaries ---------------------------------------------


def is_forex_open(dt_utc: datetime) -> bool:
    """True iff the UTC instant falls within the forex trading week.

    Open window: Sun 5pm NY (inclusive) → Fri 5pm NY (exclusive).
    """
    dt_utc = _as_naive_utc(dt_utc)
    ny = _to_ny(dt_utc)
    weekday = ny.weekday()  # Mon=0 .. Sun=6

    if weekday == 5:  # Saturday
        return False
    if weekday == 6:  # Sunday
        return ny.hour >= FOREX_WEEK_OPEN_HOUR_NY
    if weekday == 4:  # Friday
        return ny.hour < FOREX_WEEK_CLOSE_HOUR_NY
    return True  # Mon..Thu


def week_open(dt_utc: datetime) -> datetime:
    """Return UTC of the most recent Sun 5pm NY at or before ``dt_utc``."""
    dt_utc = _as_naive_utc(dt_utc)
    ny = _to_ny(dt_utc)
    # Rewind to Sunday 17:00 NY. Sunday=6.
    days_since_sunday = (ny.weekday() - 6) % 7
    sun_date = (ny - timedelta(days=days_since_sunday)).date()
    candidate_ny = datetime.combine(sun_date, time(FOREX_WEEK_OPEN_HOUR_NY), tzinfo=NY)
    if candidate_ny > ny:
        candidate_ny -= timedelta(days=7)
    return _ny_to_utc(candidate_ny)


def week_close(dt_utc: datetime) -> datetime:
    """Return UTC of the next Fri 5pm NY at or after ``dt_utc``."""
    dt_utc = _as_naive_utc(dt_utc)
    ny = _to_ny(dt_utc)
    # Advance to Friday 17:00 NY. Friday=4.
    days_until_friday = (4 - ny.weekday()) % 7
    fri_date = (ny + timedelta(days=days_until_friday)).date()
    candidate_ny = datetime.combine(fri_date, time(FOREX_WEEK_CLOSE_HOUR_NY), tzinfo=NY)
    if candidate_ny < ny:
        candidate_ny += timedelta(days=7)
    return _ny_to_utc(candidate_ny)


# ---- H4 / H1 grid -------------------------------------------------------


def floor_to_h4(dt_utc: datetime) -> datetime:
    """Return the UTC open of the H4 bar containing ``dt_utc``.

    H4 bars open at NY hours {17, 21, 1, 5, 9, 13}. The bar containing T is the
    one whose open ≤ T and whose close (open + 4h) > T.
    """
    dt_utc = _as_naive_utc(dt_utc)
    ny = _to_ny(dt_utc)
    # Find the greatest open-hour ≤ ny.hour that is in the allowed set, considering
    # the anchor wraps through midnight.
    allowed = sorted(H4_BAR_OPEN_HOURS_NY)
    hour = ny.hour
    # Build candidates on today and yesterday (since 17 on day D-1 is the open of
    # a bar that straddles midnight into day D).
    candidates: list[datetime] = []
    for h in allowed:
        cand = datetime.combine(ny.date(), time(h), tzinfo=NY)
        candidates.append(cand)
        cand_prev = datetime.combine(ny.date() - timedelta(days=1), time(h), tzinfo=NY)
        candidates.append(cand_prev)
    # The bar open is the largest candidate ≤ ny.
    candidates = [c for c in candidates if c <= ny]
    open_ny = max(candidates)
    return _ny_to_utc(open_ny)


def expected_h4_bar_opens(start_utc: datetime, end_utc: datetime) -> list[datetime]:
    """Return H4 bar open UTC timestamps where ``start_utc <= open < end_utc``.

    Only emits timestamps that fall in the forex-open window. No holiday filtering
    (forex stays open on holidays with thin liquidity).
    """
    start_utc = _as_naive_utc(start_utc)
    end_utc = _as_naive_utc(end_utc)
    if end_utc <= start_utc:
        return []
    cursor = floor_to_h4(start_utc)
    # floor_to_h4 may be < start_utc; advance to first bar >= start_utc
    while cursor < start_utc:
        cursor = _advance_h4(cursor)
    opens: list[datetime] = []
    while cursor < end_utc:
        if is_forex_open(cursor):
            opens.append(cursor)
        cursor = _advance_h4(cursor)
    return opens


def expected_h1_bar_opens(start_utc: datetime, end_utc: datetime) -> list[datetime]:
    """Return H1 bar open UTC timestamps where ``start_utc <= open < end_utc``.

    Anchor: H1 bars open at every NY local hour. Same forex-open filtering as H4.
    """
    start_utc = _as_naive_utc(start_utc)
    end_utc = _as_naive_utc(end_utc)
    if end_utc <= start_utc:
        return []
    cursor = _floor_to_h1(start_utc)
    while cursor < start_utc:
        cursor = _advance_h1(cursor)
    opens: list[datetime] = []
    while cursor < end_utc:
        if is_forex_open(cursor):
            opens.append(cursor)
        cursor = _advance_h1(cursor)
    return opens


def _advance_h4(bar_open_utc: datetime) -> datetime:
    """Return the next H4 bar open after ``bar_open_utc``.

    Computes in NY local to respect the anchor hours across DST transitions.
    """
    ny = _to_ny(bar_open_utc)
    # Find current hour's position in the allowed set.
    allowed = sorted(H4_BAR_OPEN_HOURS_NY)
    idx = allowed.index(ny.hour) if ny.hour in allowed else -1
    if idx == -1:
        # Not on an anchor — advance to the next anchor hour.
        later = [h for h in allowed if h > ny.hour]
        if later:
            next_ny = ny.replace(hour=later[0], minute=0, second=0, microsecond=0)
        else:
            next_ny = datetime.combine(ny.date() + timedelta(days=1), time(allowed[0]), tzinfo=NY)
    else:
        if idx + 1 < len(allowed):
            next_ny = ny.replace(hour=allowed[idx + 1], minute=0, second=0, microsecond=0)
        else:
            next_ny = datetime.combine(ny.date() + timedelta(days=1), time(allowed[0]), tzinfo=NY)
    return _ny_to_utc(next_ny)


def _floor_to_h1(dt_utc: datetime) -> datetime:
    dt_utc = _as_naive_utc(dt_utc)
    ny = _to_ny(dt_utc)
    floored_ny = ny.replace(minute=0, second=0, microsecond=0)
    return _ny_to_utc(floored_ny)


def _advance_h1(bar_open_utc: datetime) -> datetime:
    ny = _to_ny(bar_open_utc)
    next_ny = ny + timedelta(hours=1)
    # Normalize to the NY local hour (DST handled by zoneinfo arithmetic).
    next_ny = next_ny.replace(minute=0, second=0, microsecond=0)
    return _ny_to_utc(next_ny)


# ---- Calendar / session-day helpers -------------------------------------


def ny_calendar_day(dt_utc: datetime) -> date:
    """Return the NY calendar date (midnight-to-midnight NY local) of a UTC instant."""
    return _to_ny(_as_naive_utc(dt_utc)).date()


def prior_forex_day(d: date) -> date:
    """Return the previous trading day (Mon-Fri). Does not skip US holidays.

    For pivot derivation: forex is open on most US holidays so we use the prior
    calendar weekday, not the prior XNYS session.
    """
    cur = d - timedelta(days=1)
    while cur.weekday() >= 5:  # Sat=5, Sun=6
        cur -= timedelta(days=1)
    return cur


def is_us_market_holiday(d: date) -> bool:
    """True if XNYS is closed for a regular session on date ``d``."""
    if d.weekday() >= 5:
        return False  # weekends aren't "holidays" in the informational sense we want
    return not _xnys().is_session(d.isoformat())


def is_uk_market_holiday(d: date) -> bool:
    """True if XLON is closed for a regular session on date ``d``."""
    if d.weekday() >= 5:
        return False
    return not _xlon().is_session(d.isoformat())


# ---- Gap classification -------------------------------------------------


def classify_gaps(
    observed: Iterable[datetime],
    *,
    start_utc: datetime,
    end_utc: datetime,
    granularity: Granularity = "H4",
) -> list[BarGap]:
    """Return missing bar opens in ``[start_utc, end_utc)`` with gap-kind labels.

    Observed timestamps are matched by exact equality (after UTC normalization).
    """
    start_utc = _as_naive_utc(start_utc)
    end_utc = _as_naive_utc(end_utc)

    if granularity == "H4":
        expected = expected_h4_bar_opens(start_utc, end_utc)
    elif granularity == "H1":
        expected = expected_h1_bar_opens(start_utc, end_utc)
    else:
        raise ValueError(f"unsupported granularity: {granularity}")

    observed_set = {_as_naive_utc(o) for o in observed}
    missing = [t for t in expected if t not in observed_set]

    gaps: list[BarGap] = []
    for t in missing:
        if not is_forex_open(t):
            gaps.append(BarGap(t, BarGapKind.WEEKEND))
            continue
        ny_d = ny_calendar_day(t)
        if is_us_market_holiday(ny_d):
            gaps.append(BarGap(t, BarGapKind.US_HOLIDAY))
        elif is_uk_market_holiday(ny_d):
            gaps.append(BarGap(t, BarGapKind.UK_HOLIDAY))
        else:
            gaps.append(BarGap(t, BarGapKind.DATA_GAP))
    return gaps


# ---- Iteration helpers for backfill -------------------------------------


def iter_h4_bar_opens(start_utc: datetime, end_utc: datetime) -> Iterator[datetime]:
    """Generator form of :func:`expected_h4_bar_opens`."""
    for t in expected_h4_bar_opens(start_utc, end_utc):
        yield t
