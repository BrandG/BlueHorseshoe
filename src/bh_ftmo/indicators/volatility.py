"""Volatility indicators for BH FTMO — ATR, Bollinger Bands.

ATR sizes stops and dynamic targets; forex-specific `atr_percent` normalizes
across instruments whose price scales differ (EUR_USD ≈ 1.1 vs USD_JPY ≈ 150).

Bollinger output includes ``%B`` (position within the band, 0 = at lower
band, 1 = at upper) and ``bandwidth`` (relative width for squeeze detection),
since those are the actual scoring inputs — not the raw band prices.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bh_ftmo.indicators._common import _require_ohlc


def true_range(ohlc: pd.DataFrame) -> pd.Series:
    """Wilder's True Range: max(H-L, |H-prevC|, |L-prevC|).

    First bar has no prev_close; TR[0] = H[0] - L[0] (degenerates to bar range).
    """
    _require_ohlc(ohlc)
    prev_close = ohlc["close"].shift(1)
    h_minus_l = ohlc["high"] - ohlc["low"]
    h_minus_pc = (ohlc["high"] - prev_close).abs()
    l_minus_pc = (ohlc["low"] - prev_close).abs()
    # For the first bar where prev_close is NaN, the two prev-close terms are NaN,
    # so max skips them — TR degenerates to H-L, which is what we want.
    tr = pd.concat([h_minus_l, h_minus_pc, l_minus_pc], axis=1).max(axis=1)
    tr.name = "true_range"
    return tr


def atr(ohlc: pd.DataFrame, *, period: int = 14) -> pd.Series:
    """Average True Range via Wilder's smoothing (EMA alpha = 1/period).

    First ``period - 1`` bars are NaN (insufficient history).
    """
    _require_ohlc(ohlc)
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    tr = true_range(ohlc)
    out = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    out.name = "atr"
    return out


def atr_percent(ohlc: pd.DataFrame, *, period: int = 14) -> pd.Series:
    """ATR expressed as a fraction of current close (``ATR / close``).

    Dimensionless — comparable across instruments with different price scales
    (EUR_USD ~0.0001 vs USD_JPY ~0.1 native; both ~0.001 as a fraction).
    """
    series = atr(ohlc, period=period) / ohlc["close"].replace(0, np.nan)
    series.name = "atr_percent"
    return series


def bollinger_bands(
    ohlc: pd.DataFrame,
    *,
    period: int = 20,
    n_std: float = 2.0,
) -> pd.DataFrame:
    """Bollinger Bands plus %B and bandwidth.

    Returns a DataFrame with columns:
      - ``middle``:    SMA(close, period)
      - ``upper``:     middle + n_std * rolling_std(close, period)
      - ``lower``:     middle - n_std * rolling_std(close, period)
      - ``pct_b``:     (close - lower) / (upper - lower); NaN when flat
      - ``bandwidth``: (upper - lower) / middle; NaN when middle is 0

    ``pct_b`` is 0 at the lower band, 1 at the upper, 0.5 at the middle.
    Values outside [0, 1] are legitimate (close penetrates the band).
    """
    _require_ohlc(ohlc)
    if period < 2:
        raise ValueError(f"period must be >= 2 for a std dev, got {period}")
    if n_std <= 0:
        raise ValueError(f"n_std must be > 0, got {n_std}")

    close = ohlc["close"]
    middle = close.rolling(period, min_periods=period).mean()
    std = close.rolling(period, min_periods=period).std(ddof=0)  # population stddev
    upper = middle + n_std * std
    lower = middle - n_std * std
    band_range = upper - lower
    # %B is undefined when band_range == 0 (flat window). Bandwidth at 0 is a
    # legitimate squeeze reading, so keep it as-is — only guard the %B divide.
    pct_b = (close - lower) / band_range.replace(0, np.nan)
    bandwidth = band_range / middle.replace(0, np.nan)
    return pd.DataFrame(
        {
            "middle": middle,
            "upper": upper,
            "lower": lower,
            "pct_b": pct_b,
            "bandwidth": bandwidth,
        },
        index=ohlc.index,
    )
