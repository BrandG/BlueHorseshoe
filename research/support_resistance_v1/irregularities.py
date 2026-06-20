"""Find ALL irregularities in a price-frequency profile — peaks AND shoulders.

The dominant peaks (VZ 40, 47.5) are easy. The hard part is the SHOULDERS — bumps on
the flank of a bigger mode (VZ 42, 49) that mark resistance active only in one window,
so they never become a global maximum and prominence-based find_peaks skips them.

Method = the second-derivative (a.k.a. shoulder) technique from spectroscopy peak
deconvolution: a bump is a locally CONCAVE-DOWN region whether or not it is a true
maximum, so the minima of the profile's 2nd derivative locate every bump center —
peaks and shoulders alike. Run across several smoothing scales (ATR-relative) so both
narrow and broad irregularities surface, then dedupe by price.
"""
from __future__ import annotations
import numpy as np
from scipy.signal import find_peaks
from scipy.ndimage import gaussian_filter1d


def find_irregularities(centers, prof, atr, sigmas_atr=(0.3, 0.5, 0.8),
                        prom_frac=0.05, min_sep_atr=0.35):
    """centers, prof: the (lightly smoothed) frequency profile and its bin centers.
    Returns bumps sorted by price: {price, kind('peak'|'shoulder'), concavity, scale_atr}.
    A bump is a 'peak' if it coincides with a local max of the profile, else 'shoulder'."""
    centers = np.asarray(centers, float); prof = np.asarray(prof, float)
    if len(centers) < 5:
        return []
    binw = centers[1] - centers[0]
    raw_pk, _ = find_peaks(prof)                     # true local maxima of the profile
    peak_prices = centers[raw_pk]

    found = []
    for s_atr in sigmas_atr:
        s = max(1.0, s_atr * atr / binw)             # smoothing scale in bins
        d2 = gaussian_filter1d(prof, s, order=2)     # 2nd derivative at this scale
        neg = -d2                                    # concave-down -> positive
        if neg.max() <= 0:
            continue
        pk, _ = find_peaks(neg, prominence=prom_frac * neg.max())
        for p in pk:
            if neg[p] <= 0:                          # must be genuinely concave-down
                continue
            price = float(centers[p])
            is_peak = (len(peak_prices) and np.min(np.abs(peak_prices - price)) <= 1.5 * binw)
            found.append({"price": price, "kind": "peak" if is_peak else "shoulder",
                          "concavity": float(neg[p]), "scale_atr": s_atr})

    found.sort(key=lambda d: -d["concavity"])         # dedupe across scales, keep strongest
    kept = []
    for f in found:
        if all(abs(f["price"] - k["price"]) >= min_sep_atr * atr for k in kept):
            kept.append(f)
    kept.sort(key=lambda d: d["price"])
    return kept


if __name__ == "__main__":
    import sys, os
    import duckdb
    sys.path.insert(0, os.path.dirname(__file__))
    from profile import compute_profile, ProfileParams
    HERE = os.path.dirname(os.path.abspath(__file__))
    DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")
    sym = sys.argv[1].upper() if len(sys.argv) > 1 else "VZ"
    nd = int(sys.argv[2]) if len(sys.argv) > 2 else 252
    con = duckdb.connect(DB, read_only=True)
    d = con.execute("SELECT high,low,close,volume FROM ohlcv WHERE symbol=? ORDER BY date DESC LIMIT ?",
                    [sym, nd]).df().iloc[::-1]
    con.close()
    h, l, c, v = (d[x].to_numpy(float) for x in ("high", "low", "close", "volume"))
    pp = ProfileParams(recency_halflife=126.0, window_bars=len(c))
    centers, prof, peaks, a, _ = compute_profile(h, l, c, v, pp, weight_mode="frequency")
    irr = find_irregularities(centers, prof, a)
    print(f"{sym}: ATR={a:.2f}  prominence-peaks={[round(p['price'],2) for p in peaks]}")
    print(f"  {len(irr)} irregularities (2nd-derivative, multi-scale):")
    for f in irr:
        print(f"    {f['price']:7.2f}  {f['kind']:8}  concavity={f['concavity']:.4g}  @scale {f['scale_atr']}ATR")
