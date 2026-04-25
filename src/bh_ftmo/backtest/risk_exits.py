"""Risk-driven forced exits used by the Phase 3 backtest engine.

These exits are not alpha logic. They model hard operational constraints around
the Friday close and FTMO challenge deadlines so the future engine can close
positions conservatively before those boundaries.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo

from bh_ftmo.backtest.types import ExitEvent, Position

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


class DeadlineState(Enum):
    """Graduated deadline-pressure states consumed by entry and flatten logic."""

    NORMAL = "normal"
    TIGHTENED = "tightened"
    NO_NEW_ENTRIES = "no_new_entries"
    HARD_FLATTEN = "hard_flatten"



def _to_ny(ts: datetime) -> datetime:
    """Convert a tz-naive UTC timestamp into NY-local aware time."""

    return ts.replace(tzinfo=UTC).astimezone(NY)



def weekend_flatten_events(
    open_positions: list[Position],
    ts: datetime,
    bid_at: dict[str, float],
    ask_at: dict[str, float],
    config: dict,
) -> list[ExitEvent]:
    """Emit forced close events inside the configured Friday pre-close window."""

    ny_ts = _to_ny(ts)
    if ny_ts.weekday() != 4:
        return []

    hours = float(config.get("weekend_flatten_hours_before_close", 4))
    friday_close = datetime.combine(ny_ts.date(), time(17, 0), tzinfo=NY)
    if ny_ts < friday_close - timedelta(hours=hours) or ny_ts >= friday_close:
        return []

    events: list[ExitEvent] = []
    for position in open_positions:
        price = bid_at[position.symbol] if position.direction > 0 else ask_at[position.symbol]
        events.append(
            ExitEvent(
                ts=ts,
                symbol=position.symbol,
                kind="weekend_flatten",
                price=price,
                position_id=position.id,
            )
        )
    return events



def deadline_check(
    ts: datetime,
    deadline: Optional[date],
    config: dict,
) -> DeadlineState:
    """Return the current deadline-pressure state for the supplied timestamp."""

    del config
    if deadline is None:
        return DeadlineState.NORMAL

    days_remaining = (deadline - ts.date()).days
    if days_remaining <= 0:
        return DeadlineState.HARD_FLATTEN
    if days_remaining < 3:
        return DeadlineState.NO_NEW_ENTRIES
    if days_remaining <= 7:
        return DeadlineState.TIGHTENED
    return DeadlineState.NORMAL
