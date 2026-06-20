"""Reversal-point histogram — S/R from where price actually TURNED, not time-at-price.

Brand's refinement of the volume/frequency profile: don't histogram every price the bar
passed through (that smears in a lot of "just passing through" prices). Histogram only
the REVERSAL turning points — a swing high (price rose, turned DOWN = a resistance touch)
or a swing low (fell, turned UP = a support touch). The approach/bounce can come in at
any slope; we keep only the horizontal turning-point PRICE.

A one-off reversal contributes a single point and won't form a peak; a price the market
keeps turning at (touch -> leave -> come back) stacks multiple reversals into a peak. So
the histogram peak IS the "comes back again" confirmation. Recency-weighted so recent
turns matter more. Peaks (incl. shoulders) come from the second-derivative detector.
"""
from __future__ import annotations
import numpy as np
from scipy.ndimage import gaussian_filter1d

from detector import wilder_atr


def swing_pivots(high, low, k=3):
    """Fractal reversal points. Swing high at i if high[i] is the unique max of [i-k,i+k]
    (price turned down); swing low symmetric (turned up). Returns highs, lows as
    lists of (bar, price)."""
    n = len(high)
    highs, lows = [], []
    for i in range(k, n - k):
        if np.argmax(high[i - k:i + k + 1]) == k:
            highs.append((i, float(high[i])))
        if np.argmin(low[i - k:i + k + 1]) == k:
            lows.append((i, float(low[i])))
    return highs, lows


def build_reversal_profile(high, low, close, volume=None, k=3, bin_atr=0.25,
                           halflife=126.0, smooth_sigma=1.5, weight_mode="count",
                           atr_window=14, as_of=None):
    """Histogram of reversal-point prices, recency-weighted.

    weight_mode: 'count' -> each reversal = 1 (x recency). 'magnitude' -> each reversal
    weighted by its swing prominence in ATR (a deep turn defends harder than a shallow one).
    Returns (centers, weights, pivots, atr) where pivots = list of (bar, price, 'R'|'S')."""
    high = np.asarray(high, float); low = np.asarray(low, float); close = np.asarray(close, float)
    n = len(close)
    if as_of is None:
        as_of = n - 1
    atr_arr = wilder_atr(high, low, close, atr_window)
    a = atr_arr[as_of]
    if np.isnan(a) or a <= 0:
        a = np.nanmedian(atr_arr[:as_of + 1])

    highs, lows = swing_pivots(high, low, k)
    pivots = ([(b, p, "R") for b, p in highs if b <= as_of] +
              [(b, p, "S") for b, p in lows if b <= as_of])
    if not pivots:
        return np.array([]), np.array([]), [], a

    pmin = low[:as_of + 1].min(); pmax = high[:as_of + 1].max()
    binw = bin_atr * a
    nb = max(8, int(np.ceil((pmax - pmin) / binw)))
    edges = np.linspace(pmin, pmax, nb + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    weights = np.zeros(nb)

    for (b, p, kind) in pivots:
        rec = 0.5 ** ((as_of - b) / halflife)
        w = rec
        if weight_mode == "magnitude":
            w *= _prominence_atr(b, kind, high, low, a)
        bi = int(np.clip((p - pmin) / binw, 0, nb - 1))
        weights[bi] += w                                   # deposit at the turning-point price

    sm = gaussian_filter1d(weights, smooth_sigma)
    return centers, sm, pivots, a


def _travel_price(b, kind, high, low, span=20):
    """How far price ran away from the pivot afterwards, in PRICE units (swing depth)."""
    lo = max(0, b - span); hi = min(len(high), b + span + 1)
    if kind == "R":
        return max(0.0, high[b] - low[lo:hi].min())
    return max(0.0, high[lo:hi].max() - low[b])


def _prominence_atr(b, kind, high, low, a, span=20):
    """Swing depth in ATR (used by build_reversal_profile's magnitude weighting)."""
    return _travel_price(b, kind, high, low, span) / a


def cluster_levels(high, low, close, k=3, tol_atr=0.4, min_touch=3, halflife=126.0,
                   atr_window=14, as_of=None):
    """Detect S/R levels DIRECTLY from reversal points (Brand's definition), not via a
    smoothed histogram peak. Cluster turning points by price with a TIGHT tolerance; any
    cluster with >= min_touch touches is a level. Recency & swing-depth are a STRENGTH
    score, never a gate -- so old-but-real (42-43) and sharp few-touch extremes (51-52)
    both survive, and close neighbors (42.0 vs 42.8) stay as separate bands.

    Returns levels sorted by price, each: price (recency-weighted), touches, strength,
    recency_sum, first/last bar, kind ('support'/'resistance' vs current close), members.
    """
    high = np.asarray(high, float); low = np.asarray(low, float); close = np.asarray(close, float)
    n = len(close)
    if as_of is None:
        as_of = n - 1
    atr_arr = wilder_atr(high, low, close, atr_window)
    a = atr_arr[as_of]
    if np.isnan(a) or a <= 0:
        a = np.nanmedian(atr_arr[:as_of + 1])

    pivots = build_pivots(high, low, k)
    return cluster_pivots(pivots, atr_arr, close, as_of, k=k, tol_atr=tol_atr,
                          min_touch=min_touch, halflife=halflife)


def build_pivots(high, low, k=3):
    """Enriched pivot list: (bar, price, kind 'R'|'S', swing_travel_price). Travel = how
    far price ran away from the pivot afterwards (price units); divided by ATR at cluster
    time. Computed once so a walk-forward test doesn't recompute per bar."""
    highs, lows = swing_pivots(high, low, k)
    return ([(b, p, "R", _travel_price(b, "R", high, low)) for b, p in highs] +
            [(b, p, "S", _travel_price(b, "S", high, low)) for b, p in lows])


def cluster_pivots(pivots, atr_arr, close, as_of, k=3, tol_atr=0.4, min_touch=3,
                   halflife=126.0):
    """Cluster a precomputed enriched pivot list as-of bar `as_of`, POINT-IN-TIME: a pivot
    at bar b is only visible once confirmed (b + k <= as_of). Returns (levels, atr_at_as_of)."""
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
            clusters.append(cur); cur = [pt]
    clusters.append(cur)

    levels = []
    for cl in clusters:
        if len(cl) < min_touch:
            continue
        bars = [b for b, _, _, _ in cl]; prices = [p for _, p, _, _ in cl]
        recs = [0.5 ** ((as_of - b) / halflife) for b in bars]
        mags = [tv / a for _, _, _, tv in cl]
        wsum = sum(recs) or 1e-9
        price = float(np.dot(recs, prices) / wsum)   # recency-weighted band price
        strength = float(sum(r * m for r, m in zip(recs, mags)))   # recent, deep turns weigh most
        n_down = sum(1 for _, _, kd, _ in cl if kd == "R")   # turn-downs = acted as resistance
        n_up = sum(1 for _, _, kd, _ in cl if kd == "S")     # turn-ups   = acted as support
        # character from BEHAVIOR (not position vs price): both sides -> 'flip' (strongest)
        character = "flip" if (n_down and n_up) else ("resistance" if n_down else "support")
        levels.append({"price": price, "touches": len(cl), "strength": strength,
                       "recency_sum": float(sum(recs)), "first": min(bars), "last": max(bars),
                       "n_down": n_down, "n_up": n_up, "character": character,
                       "actionable": "buy-zone" if price < close[as_of] else "stall-zone",
                       "members": [(b, p, kd) for b, p, kd, _ in cl]})
    levels.sort(key=lambda d: d["price"])
    return levels, a


def find_zones(levels, atr, zone_atr=1.5):
    """Group adjacent level-bands into reinforced zones: a price region holding several
    >=3-touch bands within zone_atr is stronger than one isolated band. Returns zones with
    >=2 bands: {lo, hi, n_bands, strength, touches}."""
    zones = []
    cur = []
    for lv in sorted(levels, key=lambda d: d["price"]):
        if cur and lv["price"] - cur[-1]["price"] > zone_atr * atr:
            if len(cur) >= 2:
                zones.append(_mk_zone(cur))
            cur = []
        cur.append(lv)
    if len(cur) >= 2:
        zones.append(_mk_zone(cur))
    return zones


def _mk_zone(bands):
    return {"lo": min(b["price"] for b in bands), "hi": max(b["price"] for b in bands),
            "n_bands": len(bands), "strength": sum(b["strength"] for b in bands),
            "touches": sum(b["touches"] for b in bands)}
