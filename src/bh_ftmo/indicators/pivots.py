"""Classic daily pivot levels for BH FTMO.

Per FX_TIME_SPEC.md section 6: pivot levels for a bar at timestamp T are
computed from the OHLC of the prior forex-trading day (Mon-Fri, weekend
skipped). The daily OHLC is itself aggregated from intraday bars keyed by
NY calendar date (midnight-to-midnight NY local).

Classic pivot formula:
    PP = (H + L + C) / 3
    R1 = 2*PP - L           S1 = 2*PP - H
    R2 = PP + (H - L)       S2 = PP - (H - L)
    R3 = H + 2*(PP - L)     S3 = L - 2*(H - PP)

where (H, L, C) are the prior day's high/low/close.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from bh_ftmo.data.fx_time_utils import NY, UTC, prior_forex_day
from bh_ftmo.indicators._common import _require_ohlc


def daily_ohlc(ohlc: pd.DataFrame, *, timestamps: pd.Series) -> pd.DataFrame:
    """Aggregate intraday OHLC into daily OHLC keyed by NY calendar date.

    Assumes ``ohlc`` rows are sorted by ``timestamps`` ascending (true of
    :class:`FxStore` output). Each day's:
      - ``open``:  first bar's open
      - ``high``:  max of all bars' high
      - ``low``:   min of all bars' low
      - ``close``: last bar's close

    Returns a DataFrame indexed by :class:`datetime.date` with four columns.
    """
    _require_ohlc(ohlc)
    if len(timestamps) != len(ohlc):
        raise ValueError(
            f"timestamps length {len(timestamps)} != ohlc length {len(ohlc)}"
        )

    ts_utc = pd.to_datetime(timestamps)
    # Localize as UTC, then convert to NY local, then take date component.
    # This vectorizes the per-row ny_calendar_day call.
    if ts_utc.dt.tz is None:
        ts_ny = ts_utc.dt.tz_localize(UTC).dt.tz_convert(NY)
    else:
        ts_ny = ts_utc.dt.tz_convert(NY)
    ny_dates = ts_ny.dt.date

    # Use the ohlc index (not the caller's) to avoid surprises
    work = ohlc.reset_index(drop=True).assign(_ny_date=pd.Series(ny_dates).reset_index(drop=True))
    grouped = work.groupby("_ny_date", sort=True)
    daily = pd.DataFrame(
        {
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
        }
    )
    daily.index.name = None
    return daily


def _classic_pivots(daily: pd.DataFrame) -> pd.DataFrame:
    """Apply the classic pivot formula row-wise to a daily OHLC DataFrame."""
    high = daily["high"]
    low = daily["low"]
    close = daily["close"]
    rng = high - low
    pp = (high + low + close) / 3.0
    return pd.DataFrame(
        {
            "pp": pp,
            "r1": 2 * pp - low,
            "s1": 2 * pp - high,
            "r2": pp + rng,
            "s2": pp - rng,
            "r3": high + 2 * (pp - low),
            "s3": low - 2 * (high - pp),
        },
        index=daily.index,
    )


def pivots(ohlc: pd.DataFrame, *, timestamps: pd.Series) -> pd.DataFrame:
    """Classic daily pivots applied per bar using prior forex day's OHLC.

    Parameters
    ----------
    ohlc:
        Normalized OHLC DataFrame from :func:`ohlc_mid` (columns
        ``open``/``high``/``low``/``close``).
    timestamps:
        tz-naive UTC :class:`datetime` series aligned to ``ohlc`` rows.
        (Typically ``df["timestamp"]`` from an :class:`FxStore.load` result.)

    Returns
    -------
    pd.DataFrame
        Indexed like ``ohlc``, columns ``pp``, ``r1``, ``r2``, ``r3``, ``s1``,
        ``s2``, ``s3``. Bars on the first NY trading day of the data are NaN
        (no prior day available); Monday bars use Friday's OHLC (weekend skip).
    """
    _require_ohlc(ohlc)
    if len(timestamps) != len(ohlc):
        raise ValueError(
            f"timestamps length {len(timestamps)} != ohlc length {len(ohlc)}"
        )

    daily = daily_ohlc(ohlc, timestamps=timestamps)
    daily_pivots = _classic_pivots(daily)

    # For each bar: find its NY calendar day, then its prior forex day,
    # then pull that day's pivots.
    ts_utc = pd.to_datetime(timestamps)
    if ts_utc.dt.tz is None:
        ts_ny = ts_utc.dt.tz_localize(UTC).dt.tz_convert(NY)
    else:
        ts_ny = ts_utc.dt.tz_convert(NY)
    ny_dates = ts_ny.dt.date
    prior_dates = ny_dates.apply(prior_forex_day)

    result = daily_pivots.reindex(prior_dates.to_numpy())
    result.index = ohlc.index
    return result
