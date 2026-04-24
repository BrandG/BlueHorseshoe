"""Momentum indicators for BH FTMO — RSI, MACD, Stochastic, CCI, Williams %R.

All functions take an OHLC DataFrame (columns: open/high/low/close — mid
prices, produced by :func:`bh_ftmo.indicators.ohlc_mid`) and return a
pandas Series or DataFrame indexed identically to the input.

The first ``lookback - 1`` rows of each output are NaN (insufficient history).

Defaults are the classic daily-bar values. Phase 2c tunes lookbacks for 4h
forex via walk-forward grid search — do not hard-code new defaults here;
pass ``period=...`` at the call site from a weights config.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bh_ftmo.indicators._common import _require_ohlc


def rsi(ohlc: pd.DataFrame, *, period: int = 14) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing (EMA with alpha = 1/period).

    RSI in [0, 100]. Oversold typically < 30, overbought > 70 on daily bars.
    Forex 4h thresholds will tune differently — tune via Phase 2c.
    """
    _require_ohlc(ohlc)
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")

    close = ohlc["close"]
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    # Wilder's smoothing = EMA with alpha = 1/period, no bias adjustment.
    alpha = 1.0 / period
    avg_gain = gain.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False, min_periods=period).mean()

    # Divide-by-zero: if avg_loss == 0, RS is infinite → RSI = 100.
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    # Where avg_loss == 0 and avg_gain > 0, force RSI = 100
    out = out.where(~((avg_loss == 0) & (avg_gain > 0)), 100.0)
    # Where both are 0 (flat price), RSI is undefined — leave as NaN
    out.name = "rsi"
    return out


def macd(
    ohlc: pd.DataFrame,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """Moving Average Convergence/Divergence.

    Returns a DataFrame with columns:
      - ``macd``:      EMA(close, fast) - EMA(close, slow)
      - ``signal``:    EMA(macd, signal)
      - ``histogram``: macd - signal
    """
    _require_ohlc(ohlc)
    if not (1 <= fast < slow):
        raise ValueError(f"require 1 <= fast < slow, got fast={fast} slow={slow}")
    if signal < 1:
        raise ValueError(f"signal must be >= 1, got {signal}")

    close = ohlc["close"]
    ema_fast = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line

    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "histogram": histogram},
        index=ohlc.index,
    )


def stochastic(
    ohlc: pd.DataFrame,
    *,
    k_period: int = 14,
    d_period: int = 3,
) -> pd.DataFrame:
    """Fast stochastic oscillator.

    Returns a DataFrame with columns:
      - ``k``: 100 * (close - min(low, k_period)) / (max(high, k_period) - min(low, k_period))
      - ``d``: SMA(k, d_period) — the signal line
    """
    _require_ohlc(ohlc)
    if k_period < 1 or d_period < 1:
        raise ValueError(f"periods must be >= 1, got k={k_period} d={d_period}")

    low_min = ohlc["low"].rolling(k_period, min_periods=k_period).min()
    high_max = ohlc["high"].rolling(k_period, min_periods=k_period).max()
    rng = high_max - low_min
    # Flat range → undefined %K (NaN)
    k = 100.0 * (ohlc["close"] - low_min) / rng.replace(0, np.nan)
    d = k.rolling(d_period, min_periods=d_period).mean()
    return pd.DataFrame({"k": k, "d": d}, index=ohlc.index)


def cci(ohlc: pd.DataFrame, *, period: int = 20) -> pd.Series:
    """Commodity Channel Index.

    Formula:
      TP = (H + L + C) / 3
      CCI = (TP - SMA(TP, period)) / (0.015 * mean_absolute_deviation)

    ``mean_absolute_deviation`` is computed over the same rolling window.
    Ranges loosely ±100 typical; ±200 extreme.
    """
    _require_ohlc(ohlc)
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")

    tp = (ohlc["high"] + ohlc["low"] + ohlc["close"]) / 3.0
    sma = tp.rolling(period, min_periods=period).mean()
    mad = tp.rolling(period, min_periods=period).apply(
        lambda x: np.mean(np.abs(x - x.mean())), raw=True,
    )
    out = (tp - sma) / (0.015 * mad.replace(0, np.nan))
    out.name = "cci"
    return out


def williams_r(ohlc: pd.DataFrame, *, period: int = 14) -> pd.Series:
    """Williams %R — same numerator as Stochastic's %K but inverted.

    Returns values in [-100, 0]. Oversold typically < -80, overbought > -20.
    """
    _require_ohlc(ohlc)
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")

    high_max = ohlc["high"].rolling(period, min_periods=period).max()
    low_min = ohlc["low"].rolling(period, min_periods=period).min()
    rng = high_max - low_min
    out = -100.0 * (high_max - ohlc["close"]) / rng.replace(0, np.nan)
    out.name = "williams_r"
    return out
