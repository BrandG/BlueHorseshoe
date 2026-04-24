"""Forex session classification + per-session range aggregation.

Session boundaries are defined by NY-local wall-clock hour (see
``SESSION_HOURS``). DST is handled implicitly: the conversion from UTC to
NY local respects the current offset, so a bar opening at "08:00 NY" in
July (EDT) and "08:00 NY" in January (EST) both land in the OVERLAP session
despite being at different UTC hours.

Labels:
  - ``ASIA``    17:00 – 03:00 NY (10h, wraps midnight): Tokyo + Sydney desks
  - ``LONDON``  03:00 – 08:00 NY (5h): London pre-NY overlap
  - ``OVERLAP`` 08:00 – 12:00 NY (4h): London + NY concurrent, highest volume
  - ``NY``      12:00 – 17:00 NY (5h): NY post-London
  - ``CLOSED``  Fri 17:00 – Sun 17:00 NY: market closed

Phase 2c can override the hour boundaries via the ``hours`` argument if
empirical tuning suggests different session cut-offs.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

import pandas as pd

from bh_ftmo.data.fx_time_utils import NY, UTC, is_forex_open
from bh_ftmo.indicators._common import _require_ohlc


class Session(str, Enum):
    ASIA = "asia"
    LONDON = "london"
    OVERLAP = "overlap"
    NY = "ny"
    CLOSED = "closed"


# Default NY-local hour boundaries. ``hours`` arg to session_label can override.
SESSION_HOURS: dict[Session, tuple[int, int]] = {
    Session.ASIA: (17, 3),      # 17..23, 0..2  (wraps midnight)
    Session.LONDON: (3, 8),
    Session.OVERLAP: (8, 12),
    Session.NY: (12, 17),
}


def _hour_in_window(hour: int, start: int, end: int) -> bool:
    """Return True if ``hour`` is in [start, end). Wraps if start > end."""
    if start <= end:
        return start <= hour < end
    # Wraps midnight, e.g. start=17 end=3 → [17..23] ∪ [0..2]
    return hour >= start or hour < end


def _classify_hour(hour: int, hours: dict[Session, tuple[int, int]]) -> Session:
    for session, (start, end) in hours.items():
        if _hour_in_window(hour, start, end):
            return session
    # Should never reach here if the hours dict covers 24h; defensively return ASIA.
    return Session.ASIA


def session_label(
    timestamps: pd.Series,
    *,
    hours: Optional[dict[Session, tuple[int, int]]] = None,
) -> pd.Series:
    """Return a Series of :class:`Session` values (one per input timestamp).

    Classification is based on each timestamp's NY-local hour, with market-
    closed weekends labeled ``CLOSED``.
    """
    hours = hours or SESSION_HOURS
    ts_utc = pd.to_datetime(timestamps)
    if ts_utc.dt.tz is None:
        ts_ny = ts_utc.dt.tz_localize(UTC).dt.tz_convert(NY)
    else:
        ts_ny = ts_utc.dt.tz_convert(NY)
    ny_hours = ts_ny.dt.hour

    labels: list[Session] = []
    for ts, h in zip(timestamps, ny_hours):
        if not is_forex_open(ts):
            labels.append(Session.CLOSED)
            continue
        labels.append(_classify_hour(int(h), hours))
    out = pd.Series(labels, index=timestamps.index if hasattr(timestamps, "index") else None)
    out.name = "session"
    return out


def session_ranges(
    ohlc: pd.DataFrame,
    *,
    timestamps: pd.Series,
    hours: Optional[dict[Session, tuple[int, int]]] = None,
) -> pd.DataFrame:
    """Aggregate OHLC per (NY date, session) pair.

    Returns a DataFrame indexed by ``(date, session)`` with columns
    ``open`` / ``high`` / ``low`` / ``close``. Bars in the CLOSED session
    are excluded.

    Assumes input rows are sorted chronologically (true of :class:`FxStore`
    output).
    """
    _require_ohlc(ohlc)
    if len(timestamps) != len(ohlc):
        raise ValueError(
            f"timestamps length {len(timestamps)} != ohlc length {len(ohlc)}"
        )

    hours = hours or SESSION_HOURS
    ts_utc = pd.to_datetime(timestamps)
    if ts_utc.dt.tz is None:
        ts_ny = ts_utc.dt.tz_localize(UTC).dt.tz_convert(NY)
    else:
        ts_ny = ts_utc.dt.tz_convert(NY)
    ny_dates = ts_ny.dt.date
    labels = session_label(timestamps, hours=hours)

    work = ohlc.reset_index(drop=True).assign(
        _date=pd.Series(ny_dates).reset_index(drop=True),
        _session=pd.Series([s.value for s in labels]).reset_index(drop=True),
    )
    work = work[work["_session"] != Session.CLOSED.value]

    grouped = work.groupby(["_date", "_session"], sort=True)
    agg = pd.DataFrame(
        {
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
        }
    )
    agg.index.names = ["date", "session"]
    return agg
