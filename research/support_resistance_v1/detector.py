"""Swing-pivot + volume-weighted support/resistance detector.

Greenfield research module for the support_resistance_v1 spike. Turns a single
symbol's OHLCV history into per-bar features describing how close price is to the
nearest support/resistance *line* and how strong that line is -- the quantified
version of "near a strong support, buy in".

DESIGN (chosen 2026-06-18 with Brand): swing-pivot clusters + volume strength.
  1. Detect swing pivots (fractal highs/lows).
  2. Cluster nearby pivots into horizontal LEVELS.
  3. Score each level's STRENGTH = touches x recency x volume-at-level.
  4. For each bar, report distance (in ATR) and strength of the nearest support
     below and nearest resistance above.

POINT-IN-TIME DISCIPLINE (the cardinal rule in this repo's research -- no lookahead):
  * A fractal pivot at bar i uses bars [i-k, i+k], so it is only CONFIRMED at bar
    i+k. When we compute features at evaluation bar t, only pivots with
    (i + k) <= t are in the level set. A level can never "know" about a pivot that
    has not yet been confirmed as of t.
  * Volume normalization uses a TRAILING median only.
  * ATR is Wilder (causal). All warmup bars emit NaN.

Outputs (np.ndarray, length N, NaN where undefined):
  dist_to_support_atr     (close - nearest_support_below) / ATR     >= 0, small = near
  support_strength        strength score of that support level
  dist_to_resistance_atr  (nearest_resistance_above - close) / ATR  >= 0, small = near
  resistance_strength     strength score of that resistance level
  support_pull            support_strength / (dist_to_support_atr + eps)   "near & strong"
  resistance_pull         resistance_strength / (dist_to_resistance_atr + eps)  headwind
  n_active_levels         diagnostic: # live levels considered at the bar

This module has NO project dependencies (pure numpy/pandas) so it is unit-testable
in isolation and droppable into any harness. The __main__ block loads one symbol
from data/ohlcv.duckdb and prints summary stats for eyeballing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

EPS = 1e-9


# --------------------------------------------------------------------------- #
# Causal building blocks
# --------------------------------------------------------------------------- #
def wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
               window: int = 14) -> np.ndarray:
    """Wilder ATR (causal). NaN for the first `window` bars."""
    high = np.asarray(high, float)
    low = np.asarray(low, float)
    close = np.asarray(close, float)
    prev_close = np.empty_like(close)
    prev_close[0] = np.nan
    prev_close[1:] = close[:-1]
    tr = np.maximum.reduce([
        high - low,
        np.abs(high - prev_close),
        np.abs(low - prev_close),
    ])
    # Wilder smoothing == EMA with alpha = 1/window, seeded on the first `window` TRs.
    atr = np.full_like(tr, np.nan)
    if len(tr) <= window:
        return atr
    atr[window] = np.nanmean(tr[1:window + 1])
    for i in range(window + 1, len(tr)):
        atr[i] = (atr[i - 1] * (window - 1) + tr[i]) / window
    return atr


def fractal_pivots(high: np.ndarray, low: np.ndarray, k: int):
    """Return (is_swing_high, is_swing_low) bool arrays.

    Bar i is a swing high if its high is the strict maximum of [i-k, i+k]
    (symmetric, strict -> no flat-plateau false pivots). Confirmed only at i+k.
    """
    n = len(high)
    sh = np.zeros(n, bool)
    sl = np.zeros(n, bool)
    for i in range(k, n - k):
        win_h = high[i - k:i + k + 1]
        win_l = low[i - k:i + k + 1]
        if high[i] == win_h.max() and (win_h == high[i]).sum() == 1:
            sh[i] = True
        if low[i] == win_l.min() and (win_l == low[i]).sum() == 1:
            sl[i] = True
    return sh, sl


# --------------------------------------------------------------------------- #
# Level bookkeeping
# --------------------------------------------------------------------------- #
@dataclass
class _Level:
    price: float
    touches: int
    last_touch_bar: int
    vol_sum: float
    kind: str  # "S" (from swing lows) or "R" (from swing highs)
    members: list = field(default_factory=list)  # bar indices of constituent pivots

    def strength(self, t: int, recency_halflife: float, med_vol: float) -> float:
        age = t - self.last_touch_bar
        recency = 0.5 ** (age / recency_halflife)
        # avg pivot-bar volume relative to trailing median bar volume, clipped.
        vol_ratio = (self.vol_sum / max(self.touches, 1)) / (med_vol + EPS)
        vol_ratio = float(np.clip(vol_ratio, 0.2, 5.0))
        return self.touches * recency * vol_ratio


@dataclass
class SRParams:
    atr_window: int = 14
    fractal_k: int = 3            # 7-bar fractal; pivot confirmed k bars later
    cluster_tol_atr: float = 0.5  # merge pivots within this many ATRs (at formation)
    recency_halflife: float = 126.0   # bars (~6 months of trading days)
    max_lookback: int = 252       # drop a level untouched for > this many bars
    vol_median_window: int = 60   # trailing window for volume normalization


# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #
def compute_sr_arrays(high, low, close, volume, params: SRParams = SRParams()):
    """Single causal forward pass. Returns a dict of feature arrays (len N)."""
    high = np.asarray(high, float)
    low = np.asarray(low, float)
    close = np.asarray(close, float)
    volume = np.asarray(volume, float)
    n = len(close)

    atr = wilder_atr(high, low, close, params.atr_window)
    sh, sl = fractal_pivots(high, low, params.fractal_k)

    # Trailing median volume (causal: shift so bar t sees only bars < t).
    med_vol = (pd.Series(volume)
               .rolling(params.vol_median_window, min_periods=10)
               .median()
               .shift(1)
               .to_numpy())

    out = {key: np.full(n, np.nan) for key in (
        "dist_to_support_atr", "support_strength",
        "dist_to_resistance_atr", "resistance_strength",
        "support_pull", "resistance_pull",
    )}
    out["n_active_levels"] = np.zeros(n)

    levels: list[_Level] = []

    for t in range(n):
        # 1+2) Confirm the k-bars-ago pivot (point-in-time gate) and prune stale.
        levels = _step(levels, t, sh, sl, atr, high, low, volume, params)

        out["n_active_levels"][t] = len(levels)

        # 3) Features at bar t (only confirmed levels are present).
        if np.isnan(atr[t]) or atr[t] <= 0 or np.isnan(med_vol[t]) or not levels:
            continue
        c = close[t]
        a = atr[t]

        # nearest support strictly below, nearest resistance strictly above.
        sup = [lv for lv in levels if lv.price < c]
        res = [lv for lv in levels if lv.price > c]

        if sup:
            best = max(sup, key=lambda lv: lv.price)  # closest below
            d = (c - best.price) / a
            s = best.strength(t, params.recency_halflife, med_vol[t])
            out["dist_to_support_atr"][t] = d
            out["support_strength"][t] = s
            out["support_pull"][t] = s / (d + EPS)
        if res:
            best = min(res, key=lambda lv: lv.price)  # closest above
            d = (best.price - c) / a
            s = best.strength(t, params.recency_halflife, med_vol[t])
            out["dist_to_resistance_atr"][t] = d
            out["resistance_strength"][t] = s
            out["resistance_pull"][t] = s / (d + EPS)

    return out


def _absorb(levels: list[_Level], low_or_high: float, bar: int, vol: float,
            kind: str, tol: float) -> None:
    """Merge a confirmed pivot into the nearest compatible level, or create one.

    Levels are kept kind-agnostic for proximity (a former resistance that price
    has risen above is a valid support and vice-versa), but we remember the
    originating side for diagnostics. Matching is by price within `tol`.
    """
    price = float(low_or_high)
    best = None
    best_dist = tol
    for lv in levels:
        dist = abs(lv.price - price)
        if dist <= best_dist:
            best, best_dist = lv, dist
    if best is None:
        levels.append(_Level(price=price, touches=1, last_touch_bar=bar,
                             vol_sum=vol, kind=kind, members=[bar]))
    else:
        # volume-weighted price update, accumulate touch + volume.
        total_vol = best.vol_sum + vol
        best.price = (best.price * best.vol_sum + price * vol) / (total_vol + EPS)
        best.vol_sum = total_vol
        best.touches += 1
        best.last_touch_bar = bar
        best.members.append(bar)


def _step(levels, t, sh, sl, atr, high, low, volume, params):
    """Advance the level set by one bar: confirm the pivot that formed k bars ago,
    then prune stale levels. SINGLE SOURCE OF TRUTH for level evolution — used by
    both compute_sr_arrays (features) and level_snapshot (inspection). Returns the
    (possibly new) levels list.
    """
    k = params.fractal_k
    i = t - k
    if i >= 0 and (sh[i] or sl[i]) and not np.isnan(atr[i]):
        tol = params.cluster_tol_atr * atr[i]
        if sh[i]:
            _absorb(levels, high[i], i, volume[i], "R", tol)
        if sl[i]:
            _absorb(levels, low[i], i, volume[i], "S", tol)
    if levels:
        cutoff = t - params.max_lookback
        levels = [lv for lv in levels if lv.last_touch_bar >= cutoff]
    return levels


def level_snapshot(high, low, close, volume, params: SRParams = SRParams(),
                   as_of: Optional[int] = None):
    """Inspection helper: replay level evolution up to bar `as_of` (default last)
    and return the active levels at that bar, each as a dict including its
    constituent pivot bar-indices and its strength. Uses the SAME `_step` as the
    feature path, so what you see is exactly what the detector saw.

    Returns (levels_at_asof, swing_high_mask, swing_low_mask, atr).
    """
    high = np.asarray(high, float)
    low = np.asarray(low, float)
    close = np.asarray(close, float)
    volume = np.asarray(volume, float)
    n = len(close)
    if as_of is None:
        as_of = n - 1

    atr = wilder_atr(high, low, close, params.atr_window)
    sh, sl = fractal_pivots(high, low, params.fractal_k)
    med_vol = (pd.Series(volume)
               .rolling(params.vol_median_window, min_periods=10)
               .median().shift(1).to_numpy())
    mv = med_vol[as_of]
    if np.isnan(mv):
        mv = float(np.nanmedian(volume[:as_of + 1]))

    levels: list[_Level] = []
    for t in range(as_of + 1):
        levels = _step(levels, t, sh, sl, atr, high, low, volume, params)

    snap = []
    for lv in levels:
        snap.append(dict(
            price=lv.price,
            origin="resistance" if lv.kind == "R" else "support",
            touches=lv.touches,
            vol_sum=lv.vol_sum,
            first_touch_bar=min(lv.members) if lv.members else lv.last_touch_bar,
            last_touch_bar=lv.last_touch_bar,
            members=list(lv.members),
            strength=lv.strength(as_of, params.recency_halflife, mv),
        ))
    snap.sort(key=lambda d: d["price"])
    return snap, sh, sl, atr


def compute_sr_features(df: pd.DataFrame, params: SRParams = SRParams()
                        ) -> pd.DataFrame:
    """Convenience wrapper: OHLCV DataFrame -> feature DataFrame (same index).

    Expects lowercase columns: high, low, close, volume.
    """
    cols = {c.lower(): c for c in df.columns}
    arr = compute_sr_arrays(
        df[cols["high"]].to_numpy(float),
        df[cols["low"]].to_numpy(float),
        df[cols["close"]].to_numpy(float),
        df[cols["volume"]].to_numpy(float),
        params,
    )
    return pd.DataFrame(arr, index=df.index)


# --------------------------------------------------------------------------- #
# Smoke test / eyeball harness
# --------------------------------------------------------------------------- #
def _smoke(symbol: str = "AAPL", start: str = "2015-01-01") -> None:
    import duckdb
    from pathlib import Path

    # Locate the OHLCV store relative to repo root.
    here = Path(__file__).resolve()
    repo_root = here.parents[2]
    db = repo_root / "data" / "ohlcv.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    df = con.execute(
        "SELECT date, open, high, low, close, volume FROM ohlcv "
        "WHERE symbol = ? AND date >= ? ORDER BY date",
        [symbol, start],
    ).df()
    con.close()
    if df.empty:
        print(f"No rows for {symbol} since {start}")
        return
    df = df.set_index("date")
    feats = compute_sr_features(df)
    joined = df.join(feats)

    n = len(joined)
    have_sup = feats["dist_to_support_atr"].notna().sum()
    print(f"{symbol}: {n} bars, {have_sup} with a support below "
          f"({have_sup / n:.0%}), median active levels "
          f"{feats['n_active_levels'].median():.0f}")
    print("\nfeature summary:")
    print(feats[["dist_to_support_atr", "support_strength", "support_pull",
                 "dist_to_resistance_atr", "resistance_strength"]]
          .describe().round(3).to_string())
    print("\n10 most recent bars:")
    print(joined[["close", "dist_to_support_atr", "support_strength",
                  "support_pull", "dist_to_resistance_atr"]]
          .tail(10).round(3).to_string())


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    _smoke(sym)
