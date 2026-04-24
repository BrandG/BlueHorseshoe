"""Trend indicators for BH FTMO — SMA, EMA, ADX, SuperTrend, Donchian, Ichimoku.

All functions take an OHLC DataFrame (mid prices from :func:`ohlc_mid`) and
return a pandas Series or DataFrame indexed identically to the input.

Defaults are classic daily-bar values; Phase 2c tunes lookbacks for 4h forex.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bh_ftmo.indicators._common import OHLC_COLUMNS, _require_ohlc
from bh_ftmo.indicators.volatility import atr, true_range


def sma(ohlc: pd.DataFrame, *, period: int = 20, column: str = "close") -> pd.Series:
    """Simple Moving Average over ``column`` (default: close)."""
    _require_ohlc(ohlc)
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    if column not in ohlc.columns:
        raise ValueError(f"column {column!r} not in ohlc DataFrame")
    out = ohlc[column].rolling(period, min_periods=period).mean()
    out.name = f"sma_{period}"
    return out


def ema(ohlc: pd.DataFrame, *, period: int = 20, column: str = "close") -> pd.Series:
    """Exponential Moving Average (span=period, no bias adjustment)."""
    _require_ohlc(ohlc)
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    if column not in ohlc.columns:
        raise ValueError(f"column {column!r} not in ohlc DataFrame")
    out = ohlc[column].ewm(span=period, adjust=False, min_periods=period).mean()
    out.name = f"ema_{period}"
    return out


def adx(ohlc: pd.DataFrame, *, period: int = 14) -> pd.DataFrame:
    """Average Directional Index + Plus/Minus Directional Indicators.

    Returns a DataFrame with columns:
      - ``adx``:     trend strength in [0, 100]; >25 is typically trending
      - ``plus_di``: upward directional strength
      - ``minus_di``: downward directional strength

    Direction is given by sign(+DI - -DI); strength by ADX. ADX is direction-free.
    """
    _require_ohlc(ohlc)
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")

    high = ohlc["high"]
    low = ohlc["low"]

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr = true_range(ohlc)
    alpha = 1.0 / period

    tr_smooth = tr.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()

    plus_di = 100.0 * plus_dm_smooth / tr_smooth.replace(0, np.nan)
    minus_di = 100.0 * minus_dm_smooth / tr_smooth.replace(0, np.nan)
    di_sum = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum.replace(0, np.nan)
    adx_series = dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean()

    return pd.DataFrame(
        {"adx": adx_series, "plus_di": plus_di, "minus_di": minus_di},
        index=ohlc.index,
    )


def supertrend(
    ohlc: pd.DataFrame,
    *,
    period: int = 10,
    multiplier: float = 3.0,
) -> pd.DataFrame:
    """SuperTrend line + direction flag.

    Returns a DataFrame with columns:
      - ``supertrend``: the indicator line; below price during uptrend,
        above price during downtrend
      - ``direction``: +1 during uptrend, -1 during downtrend

    Formula uses ATR(period) * multiplier envelope around (H+L)/2, with
    the classic state-dependent "final band" carry-forward logic.
    """
    _require_ohlc(ohlc)
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    if multiplier <= 0:
        raise ValueError(f"multiplier must be > 0, got {multiplier}")

    atr_series = atr(ohlc, period=period)
    hl2 = (ohlc["high"] + ohlc["low"]) / 2.0
    basic_upper = hl2 + multiplier * atr_series
    basic_lower = hl2 - multiplier * atr_series

    close_arr = ohlc["close"].to_numpy()
    basic_upper_arr = basic_upper.to_numpy()
    basic_lower_arr = basic_lower.to_numpy()
    atr_arr = atr_series.to_numpy()

    n = len(ohlc)
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    super_line = np.full(n, np.nan)
    direction = np.zeros(n, dtype=np.int8)

    # Find the first index where ATR is available (period-1 bars NaN)
    first = 0
    while first < n and np.isnan(atr_arr[first]):
        first += 1
    if first >= n:
        return pd.DataFrame(
            {"supertrend": super_line, "direction": direction},
            index=ohlc.index,
        )

    # Seed at first available bar: start in downtrend (line = upper)
    final_upper[first] = basic_upper_arr[first]
    final_lower[first] = basic_lower_arr[first]
    super_line[first] = final_upper[first]
    direction[first] = -1

    for i in range(first + 1, n):
        # Carry-forward final bands
        if basic_upper_arr[i] < final_upper[i - 1] or close_arr[i - 1] > final_upper[i - 1]:
            final_upper[i] = basic_upper_arr[i]
        else:
            final_upper[i] = final_upper[i - 1]
        if basic_lower_arr[i] > final_lower[i - 1] or close_arr[i - 1] < final_lower[i - 1]:
            final_lower[i] = basic_lower_arr[i]
        else:
            final_lower[i] = final_lower[i - 1]

        # State transition
        if super_line[i - 1] == final_upper[i - 1]:
            # Was in downtrend
            if close_arr[i] > final_upper[i]:
                super_line[i] = final_lower[i]
                direction[i] = 1
            else:
                super_line[i] = final_upper[i]
                direction[i] = -1
        else:
            # Was in uptrend
            if close_arr[i] < final_lower[i]:
                super_line[i] = final_upper[i]
                direction[i] = -1
            else:
                super_line[i] = final_lower[i]
                direction[i] = 1

    return pd.DataFrame(
        {"supertrend": super_line, "direction": direction},
        index=ohlc.index,
    )


def donchian(ohlc: pd.DataFrame, *, period: int = 20) -> pd.DataFrame:
    """Donchian Channel: rolling max high / min low, with midline.

    Returns a DataFrame with columns ``upper``, ``middle``, ``lower``.
    """
    _require_ohlc(ohlc)
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")

    upper = ohlc["high"].rolling(period, min_periods=period).max()
    lower = ohlc["low"].rolling(period, min_periods=period).min()
    middle = (upper + lower) / 2.0
    return pd.DataFrame(
        {"upper": upper, "middle": middle, "lower": lower},
        index=ohlc.index,
    )


def ichimoku(
    ohlc: pd.DataFrame,
    *,
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
    displacement: int = 26,
) -> pd.DataFrame:
    """Ichimoku Cloud components.

    Returns a DataFrame with columns:
      - ``tenkan``:    (9-period high + low) / 2 — conversion line
      - ``kijun``:     (26-period high + low) / 2 — base line
      - ``senkou_a``:  (tenkan + kijun) / 2, aligned so row T holds the
        cloud the price at T is sitting inside (built from data at T-26)
      - ``senkou_b``:  (52-period high + low) / 2, aligned the same way
      - ``chikou``:    close shifted 26 bars back — at row T, shows the
        close 26 bars into the future (NaN for the last 26 rows)

    Alignment convention: senkou_a/b use ``.shift(+displacement)`` so that
    scoring logic can ask "where is this bar's price relative to the cloud?"
    directly at the current row. Consequence: the FIRST ``displacement`` rows
    of senkou_a/b are NaN (no data from before bar 0).

    Typical scoring: close above both senkou_a and senkou_b → bullish regime;
    close below both → bearish; between → uncertain.
    """
    _require_ohlc(ohlc)
    for p, name in (
        (tenkan_period, "tenkan_period"),
        (kijun_period, "kijun_period"),
        (senkou_b_period, "senkou_b_period"),
    ):
        if p < 1:
            raise ValueError(f"{name} must be >= 1, got {p}")
    if displacement < 0:
        raise ValueError(f"displacement must be >= 0, got {displacement}")

    high = ohlc["high"]
    low = ohlc["low"]

    def _period_midpoint(period: int) -> pd.Series:
        hi = high.rolling(period, min_periods=period).max()
        lo = low.rolling(period, min_periods=period).min()
        return (hi + lo) / 2.0

    tenkan = _period_midpoint(tenkan_period)
    kijun = _period_midpoint(kijun_period)
    senkou_a = ((tenkan + kijun) / 2.0).shift(displacement)
    senkou_b = _period_midpoint(senkou_b_period).shift(displacement)
    chikou = ohlc["close"].shift(-displacement)

    return pd.DataFrame(
        {
            "tenkan": tenkan,
            "kijun": kijun,
            "senkou_a": senkou_a,
            "senkou_b": senkou_b,
            "chikou": chikou,
        },
        index=ohlc.index,
    )
