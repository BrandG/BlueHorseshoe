"""Shared liquidity helpers for the equity (Gordon) candidate pipeline.

A single source of truth for "is this name actually tradeable?" so every
surface — the deep-oversold sleeve's $25M edge floor, the general report's
candidate panels (Baseline/MeanRev/Connors), and the universe-hygiene skip
that drops delisted/dead symbols — measures liquidity the same way:
20-day average *dollar* volume (price x shares), not raw share count.

Dollar volume is the right metric: a 100k-share floor passes a $1 stock at
$100k/day while blocking a $400 stock at $36M/day. The old share-count
``MIN_VOLUME_THRESHOLD`` was never actually enforced; these helpers replace it.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd


def trailing_dollar_volume(
    close: Sequence[float], volume: Sequence[float], window: int = 20
) -> float:
    """Mean of (close * volume) over the trailing ``window`` bars.

    NaN-safe. Returns 0.0 when there is no usable data (so callers can treat a
    missing/empty series as "fails the floor" without special-casing).
    """
    close = np.asarray(close, dtype=float)
    volume = np.asarray(volume, dtype=float)
    if close.size == 0 or volume.size == 0:
        return 0.0
    n = min(close.size, volume.size, window)
    dollar = close[-n:] * volume[-n:]
    if not np.any(np.isfinite(dollar)):
        return 0.0
    return float(np.nanmean(dollar))


def dollar_volume_from_df(df: pd.DataFrame, window: int = 20) -> float:
    """Trailing dollar volume from a frame carrying ``close`` and ``volume``."""
    if df is None or df.empty or "close" not in df or "volume" not in df:
        return 0.0
    return trailing_dollar_volume(df["close"].to_numpy(), df["volume"].to_numpy(), window)


def passes_dollar_volume(df: pd.DataFrame, min_dollar_volume: float, window: int = 20) -> bool:
    """True when the name clears the dollar-volume liquidity floor."""
    return dollar_volume_from_df(df, window) >= min_dollar_volume


def latest_bar_untraded(df: pd.DataFrame) -> bool:
    """True when the most-recent bar shows no trading (volume 0 / NaN).

    Catches *recently* delisted/halted names that ``is_dead_series`` misses: when
    a stock stops trading, the data provider carries the last close forward on a
    current-dated row with zero volume (e.g. THR/Thermon froze at $61.14 on
    2026-05-29 after an acquisition). The trailing-20d window still overlaps the
    live period, so both the dead-series and dollar-volume floors pass — but the
    name is untradeable *today*. A current-dated bar with zero volume is the tell;
    the date-based freshness check can't see it because the date looks fresh.
    """
    if df is None or df.empty or "volume" not in df:
        return True
    last_vol = df["volume"].to_numpy(dtype=float)[-1]
    return not last_vol > 0.0  # also True for NaN


def is_dead_series(df: pd.DataFrame, window: int = 20) -> bool:
    """True when the symbol looks delisted/dead rather than merely thin.

    The data provider returns flat placeholder bars for delisted names: a frozen
    OHLC with zero volume carried forward (e.g. ATCOL/LANDM pinned near $25 with
    vol 0 for weeks). We treat "no shares traded at all over the trailing
    window" as dead — an unambiguous signal that no liquidity floor can salvage.
    Thinly-but-genuinely traded names (DGICB at ~478 sh/day) are NOT dead here;
    they get filtered by the dollar-volume floor instead.
    """
    if df is None or df.empty or "volume" not in df:
        return True
    volume = df["volume"].to_numpy(dtype=float)
    n = min(volume.size, window)
    tail = volume[-n:]
    return not np.any(np.nan_to_num(tail) > 0.0)
