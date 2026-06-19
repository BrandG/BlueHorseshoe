"""Reversal-point support/resistance detection — production port of the validated research.

Ported verbatim (numerically) from ``research/support_resistance_v1/{reversal_profile,detector,
detector_v3}.py`` so the live ``RangeSupportStrategy`` fires on exactly the entries the backtest
validated. The research swept every bar walk-forward; production only needs the LATEST bar, so the
public entry point :func:`evaluate_support_entry` clusters once at ``as_of = n-1`` instead of looping.

Levels are built from reversal TURNING POINTS (a swing high = a turn-down = a resistance touch; a
swing low = a turn-up = a support touch), clustered by price within a tight ATR tolerance; any cluster
with >= ``MIN_TOUCH`` touches is a level. Character comes from BEHAVIOUR: only-turn-ups => support,
only-turn-downs => resistance, both => flip. The validated entry is a *pure-support* approach (a level
that has only ever been support), with price within ``NEAR_ATR`` of it from above after a recent pullback.

Pure functions, no I/O, no DB — safe to call inside ProcessPoolExecutor workers.
"""
from __future__ import annotations

import numpy as np

# --- validated parameters (research/support_resistance_v1/HANDOFF.md "Key parameters as left") ---
K = 3                 # fractal pivot half-window
TOL_ATR = 0.4         # cluster tolerance (ATR)
MIN_TOUCH = 3         # >= this many touches = a level
HALFLIFE = 126.0      # recency half-life (bars) for the band price / strength
ATR_WINDOW = 14
NEAR_ATR = 0.5        # price must be within this many ATR above the support to enter
APPROACH = 10         # look-back bars that must contain a pullback from above
ER_WINDOW = 100       # Kaufman efficiency-ratio window (range-bound gate)
ER_MAX = 0.11         # range-bound iff range_score <= this


def wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
               window: int = ATR_WINDOW) -> np.ndarray:
    """Wilder ATR (causal). NaN for the first ``window`` bars. Matches the research harness."""
    high = np.asarray(high, float)
    low = np.asarray(low, float)
    close = np.asarray(close, float)
    prev_close = np.empty_like(close)
    prev_close[0] = np.nan
    prev_close[1:] = close[:-1]
    tr = np.maximum.reduce([high - low, np.abs(high - prev_close), np.abs(low - prev_close)])
    atr = np.full_like(tr, np.nan)
    if len(tr) <= window:
        return atr
    atr[window] = np.nanmean(tr[1:window + 1])
    for i in range(window + 1, len(tr)):
        atr[i] = (atr[i - 1] * (window - 1) + tr[i]) / window
    return atr


def swing_pivots(high, low, k: int = K):
    """Fractal reversal points. Swing high at i if high[i] is the unique max of [i-k, i+k]
    (price turned down); swing low symmetric (turned up). Returns (highs, lows) as
    lists of (bar, price)."""
    high = np.asarray(high, float)
    low = np.asarray(low, float)
    n = len(high)
    highs, lows = [], []
    for i in range(k, n - k):
        if np.argmax(high[i - k:i + k + 1]) == k:
            highs.append((i, float(high[i])))
        if np.argmin(low[i - k:i + k + 1]) == k:
            lows.append((i, float(low[i])))
    return highs, lows


def _travel_price(b, kind, high, low, span=20):
    """How far price ran away from the pivot afterwards, in PRICE units (swing depth)."""
    lo = max(0, b - span)
    hi = min(len(high), b + span + 1)
    if kind == "R":
        return max(0.0, high[b] - low[lo:hi].min())
    return max(0.0, high[lo:hi].max() - low[b])


def build_pivots(high, low, k: int = K):
    """Enriched pivot list: (bar, price, kind 'R'|'S', swing_travel_price)."""
    high = np.asarray(high, float)
    low = np.asarray(low, float)
    highs, lows = swing_pivots(high, low, k)
    return ([(b, p, "R", _travel_price(b, "R", high, low)) for b, p in highs] +
            [(b, p, "S", _travel_price(b, "S", high, low)) for b, p in lows])


def cluster_pivots(pivots, atr_arr, close, as_of, k: int = K, tol_atr: float = TOL_ATR,
                   min_touch: int = MIN_TOUCH, halflife: float = HALFLIFE):
    """Cluster a precomputed enriched pivot list as-of bar ``as_of``, POINT-IN-TIME: a pivot at
    bar b is only visible once confirmed (b + k <= as_of). Returns (levels, atr_at_as_of)."""
    a = atr_arr[as_of]
    if np.isnan(a) or a <= 0:
        a = np.nanmedian(atr_arr[:as_of + 1])
    pts = [(b, p, kd, tv) for (b, p, kd, tv) in pivots if b + k <= as_of]   # PIT confirm lag
    pts.sort(key=lambda z: z[1])
    if not pts:
        return [], a

    tol = tol_atr * a
    clusters, cur = [], [pts[0]]
    for pt in pts[1:]:
        cmean = np.mean([q[1] for q in cur])         # centroid linkage
        if pt[1] - cmean <= tol:
            cur.append(pt)
        else:
            clusters.append(cur)
            cur = [pt]
    clusters.append(cur)

    levels = []
    for cl in clusters:
        if len(cl) < min_touch:
            continue
        bars = [b for b, _, _, _ in cl]
        prices = [p for _, p, _, _ in cl]
        recs = [0.5 ** ((as_of - b) / halflife) for b in bars]
        mags = [tv / a for _, _, _, tv in cl]
        wsum = sum(recs) or 1e-9
        price = float(np.dot(recs, prices) / wsum)   # recency-weighted band price
        strength = float(sum(r * m for r, m in zip(recs, mags)))
        n_down = sum(1 for _, _, kd, _ in cl if kd == "R")   # turn-downs = acted as resistance
        n_up = sum(1 for _, _, kd, _ in cl if kd == "S")     # turn-ups   = acted as support
        character = "flip" if (n_down and n_up) else ("resistance" if n_down else "support")
        levels.append({"price": price, "touches": len(cl), "strength": strength,
                       "first": min(bars), "last": max(bars), "n_down": n_down,
                       "n_up": n_up, "character": character})
    levels.sort(key=lambda d: d["price"])
    return levels, a


def range_score(close, window: int = ER_WINDOW) -> float:
    """Kaufman efficiency ratio, averaged. LOW = choppy/range-bound (good for S/R);
    HIGH (->1) = clean trend (price rarely revisits a level). NaN if too short."""
    c = np.asarray(close, float)
    if len(c) <= window + 5:
        return np.nan
    diff = np.abs(np.diff(c))
    er = []
    for t in range(window, len(c)):
        noise = diff[t - window:t].sum()
        if noise > 0:
            er.append(abs(c[t] - c[t - window]) / noise)
    return float(np.mean(er)) if er else np.nan


def is_range_bound(close, window: int = ER_WINDOW, er_max: float = ER_MAX) -> bool:
    """True iff the name is range-bound enough for S/R to mean something (ER <= er_max)."""
    rs = range_score(close, window)
    return bool(not np.isnan(rs) and rs <= er_max)


def evaluate_support_entry(high, low, close, *, k: int = K, tol_atr: float = TOL_ATR,
                           min_touch: int = MIN_TOUCH, halflife: float = HALFLIFE,
                           atr_window: int = ATR_WINDOW, near_atr: float = NEAR_ATR,
                           approach: int = APPROACH):
    """Is the LATEST bar a validated pure-support entry? Mirrors the research entry rule
    (``target_sweep.collect`` at ``t = as_of``): price within ``near_atr`` ATR above the nearest
    pure-support level, after a pullback from above in the prior ``approach`` bars.

    Returns a dict {entry_price, atr, support_price, dist_atr, touches, strength} or None.
    Does NOT apply the range-bound / liquidity / price gates — the caller does (see the sleeve).
    """
    high = np.asarray(high, float)
    low = np.asarray(low, float)
    close = np.asarray(close, float)
    n = len(close)
    if n < atr_window + 2 * k + approach + 5:
        return None
    atr_arr = wilder_atr(high, low, close, atr_window)
    as_of = n - 1
    a = atr_arr[as_of]
    if np.isnan(a) or a <= 0:
        a = np.nanmedian(atr_arr[:as_of + 1])
    if not a > 0:
        return None
    pivots = build_pivots(high, low, k)
    levels, _ = cluster_pivots(pivots, atr_arr, close, as_of, k=k, tol_atr=tol_atr,
                               min_touch=min_touch, halflife=halflife)
    supports = [L for L in levels if L["character"] == "support" and L["price"] < close[as_of]]
    if not supports:
        return None
    near = max(supports, key=lambda L: L["price"])      # nearest support below price
    dist = (close[as_of] - near["price"]) / a
    if dist > near_atr:                                  # must be within near_atr ATR, from above
        return None
    lo = max(0, as_of - approach)
    if close[lo:as_of].max() <= near["price"] + near_atr * a:   # require a recent pullback from above
        return None
    return {"entry_price": float(close[as_of]), "atr": float(a),
            "support_price": float(near["price"]), "dist_atr": float(dist),
            "touches": int(near["touches"]), "strength": float(near["strength"])}
