"""Price-histogram (Volume-Profile style) S/R locator — Brand's "banding" idea.

Throw out the time axis, histogram the prices, and the peaks are where the market
keeps trading = S/R. Two weightings folded in per Brand's feedback so the peaks
match his taste instead of just "where price drifted slowly":
  * RECENCY — each bar weighted 0.5^(age/halflife); recent congestion outranks old.
  * VOLUME — each bar deposits its VOLUME across the prices it spanned (true
    volume-by-price); high-volume nodes = real acceptance/defense, not slow drift.

compute_profile() returns the histogram and its peaks (candidate levels). All
point-in-time: only bars <= as_of contribute, recency measured to as_of.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from scipy.signal import find_peaks
from scipy.ndimage import gaussian_filter1d

from detector import wilder_atr


@dataclass
class ProfileParams:
    atr_window: int = 14
    bin_atr: float = 0.25           # histogram bin width in ATR
    recency_halflife: float = 378.0  # bars (~1.5y); recent bars weigh more
    smooth_sigma: float = 1.5       # gaussian smoothing in bins
    prominence_frac: float = 0.06   # peak must rise this frac of max above surroundings
    min_sep_atr: float = 1.0        # merge peaks closer than this (keep the taller)
    window_bars: int = 630          # how much recent history to profile (~2.5y)


def compute_profile(high, low, close, volume, params: ProfileParams = ProfileParams(),
                    as_of: int | None = None, weight_mode: str = "volume"):
    """Return (bin_centers, weights, peaks). peaks = list of dicts {price, weight}
    sorted by weight desc, deduped to >= min_sep_atr apart.

    weight_mode: 'volume' -> volume x recency (true volume-by-price, default; used by
    fusion). 'frequency' -> recency only = time-at-price (how often price visited each
    level, recent bars weighing more), independent of how heavy the volume was."""
    high = np.asarray(high, float); low = np.asarray(low, float)
    close = np.asarray(close, float); volume = np.asarray(volume, float)
    n = len(close)
    if as_of is None:
        as_of = n - 1
    atr_arr = wilder_atr(high, low, close, params.atr_window)
    a = atr_arr[as_of]
    if np.isnan(a) or a <= 0:
        a = np.nanmedian(atr_arr[:as_of + 1])

    lo_bar = max(0, as_of - params.window_bars + 1)
    sl = slice(lo_bar, as_of + 1)
    H, L, V = high[sl], low[sl], volume[sl]
    pmin, pmax = L.min(), H.max()
    binw = params.bin_atr * a
    nb = max(8, int(np.ceil((pmax - pmin) / binw)))
    edges = np.linspace(pmin, pmax, nb + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    weights = np.zeros(nb)

    idx = np.arange(lo_bar, as_of + 1)
    rec = 0.5 ** ((as_of - idx) / params.recency_halflife)
    if weight_mode == "frequency":
        vol = rec                              # recency-weighted occupancy (time at price)
    else:
        vol = np.where(V > 0, V, 1.0) * rec    # volume x recency (fallback to occupancy)

    # deposit each bar's weight across the bins its [low,high] spans
    blo = np.clip(((L - pmin) / binw).astype(int), 0, nb - 1)
    bhi = np.clip(((H - pmin) / binw).astype(int), 0, nb - 1)
    for k in range(len(V)):
        span = bhi[k] - blo[k] + 1
        weights[blo[k]:bhi[k] + 1] += vol[k] / span

    sm = gaussian_filter1d(weights, params.smooth_sigma)
    pk, _ = find_peaks(sm, prominence=params.prominence_frac * sm.max())
    cand = sorted(({"price": float(centers[p]), "weight": float(sm[p])} for p in pk),
                  key=lambda d: -d["weight"])
    # non-max suppression by price separation
    kept = []
    for c in cand:
        if all(abs(c["price"] - k["price"]) >= params.min_sep_atr * a for k in kept):
            kept.append(c)
    return centers, sm, kept, a, lo_bar
