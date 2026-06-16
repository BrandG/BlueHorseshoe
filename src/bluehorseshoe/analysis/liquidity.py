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


def is_merger_pinned(
    df: pd.DataFrame,
    window: int = 15,
    baseline_window: int = 252,
    vol_collapse_ratio: float = 0.3,
    max_band_pct: float = 0.02,
) -> bool:
    """True when price shows the merger-arb "pinned to deal price" signature.

    After a cash acquisition is announced, the target gaps to just under the
    offer price and then trades dead-flat: upside is capped at the cash
    consideration, so there is nothing left to price. A trend/swing entry there
    is structurally bad (capped upside, only deal-break downside), and the broker
    often freezes trading before close — KW/Kennedy-Wilson (cash take-private at
    $10.90) was the motivating case.

    Two conditions must BOTH hold over the trailing ``window``:

      1. Tight absolute band — ``(high - low) / mean close`` under ``max_band_pct``
         (default 2%). Cheap, computed first.
      2. Volatility collapse vs the name's OWN baseline — recent daily-return
         stdev is under ``vol_collapse_ratio`` of its trailing ``baseline_window``
         stdev. This is the discriminator that separates a merger pin from a name
         that is simply *always* quiet (a perpetually-quiet stock shows a tight
         band but no collapse, so its ratio stays near 1).

    Fires during the weeks after announcement, while the pre-pin baseline is
    still in window; a deal pinned for longer than the baseline is caught by the
    news layer instead. Heuristic — fail-open (returns False on insufficient or
    non-finite data) so a detector hiccup never drops a tradeable name.
    """
    if df is None or df.empty or "close" not in df:
        return False
    close = df["close"].to_numpy(dtype=float)
    if close.size < 2 * window:
        return False
    high = df["high"].to_numpy(dtype=float) if "high" in df else close
    low = df["low"].to_numpy(dtype=float) if "low" in df else close

    recent_close = close[-window:]
    if not np.all(np.isfinite(recent_close)) or np.any(recent_close <= 0.0):
        return False

    # (1) tight absolute band near a fixed level
    mean_close = float(np.nanmean(recent_close))
    if mean_close <= 0.0:
        return False
    band_pct = float(np.nanmax(high[-window:]) - np.nanmin(low[-window:])) / mean_close
    if band_pct >= max_band_pct:
        return False

    # (2) volatility collapse vs the name's own trailing baseline
    returns = np.diff(close) / close[:-1]
    returns = returns[np.isfinite(returns)]
    if returns.size < 2 * window:
        return False
    recent_vol = float(np.std(returns[-window:]))
    baseline_vol = float(np.std(returns[-min(baseline_window, returns.size):]))
    if baseline_vol <= 0.0:
        return False
    return (recent_vol / baseline_vol) < vol_collapse_ratio
