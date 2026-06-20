"""Wedges — sloped S/R trendlines: lines of ANY slope through >=3 reversal pivots.

Generalizes the horizontal price histogram. A horizontal level is pivots that share a
PRICE (they stack into a histogram peak); a wedge is pivots that are COLLINEAR at a
nonzero slope. Same primitive ("several confirmed reversal points fall on one line"),
the histogram is just the slope-0 case.

  * RESISTANCE line: connects swing HIGHS (price reversed DOWN off the line). Valid only
    if price mostly stayed BELOW it between touches (closes above = the line was broken).
  * SUPPORT line: connects swing LOWS (price reversed UP). Valid if price mostly stayed
    ABOVE it between touches.

Each line evaluated at the current bar collapses to one 'dynamic level' price (where the
line sits today) -> feeds the same proximity/strength machinery as a histogram peak.

A line needs >=MIN_TOUCH pivots within TOUCH_ATR of it, spanning >=MIN_SPAN bars, with
< MAX_VIOL_FRAC of the bars between first/last touch violating it by > VIOL_ATR.
"""
from __future__ import annotations
import numpy as np
from detector import wilder_atr


def swing_pivots(high, low, k=4):
    """Fractal pivots. Swing high at i if high[i] is the unique max of [i-k, i+k];
    swing low symmetric. Returns (highs, lows), each a list of (bar, price)."""
    n = len(high)
    highs, lows = [], []
    for i in range(k, n - k):
        if np.argmax(high[i - k:i + k + 1]) == k:
            highs.append((i, float(high[i])))
        if np.argmin(low[i - k:i + k + 1]) == k:
            lows.append((i, float(low[i])))
    return highs, lows


def _line_at(p1, t1, slope, t):
    return p1 + slope * (t - t1)


def find_trendlines(pivots, close, atr_arr, n, kind, halflife=126.0,
                    touch_atr=0.5, min_touch=3, min_span=20,
                    viol_atr=1.0, max_viol_frac=0.15, max_stale=63):
    """pivots: list of (bar, price) of one type. kind: 'res' or 'sup'.
    Returns deduped candidate lines, each a dict with slope, price_now, touches, etc.
    max_stale: drop a line if its LAST touch is older than this many bars (a trendline
    not touched recently is a ruler in empty space, not a live level)."""
    P = sorted(pivots)
    m = len(P)
    cands = []
    for ai in range(m):
        for bi in range(ai + 1, m):
            (t1, p1), (t2, p2) = P[ai], P[bi]
            if t2 - t1 < min_span:
                continue
            slope = (p2 - p1) / (t2 - t1)
            # inlier pivots within an ATR-scaled band of the line
            inl = [(t, p) for (t, p) in P
                   if abs(p - _line_at(p1, t1, slope, t)) <= touch_atr * atr_arr[t]]
            if len(inl) < min_touch:
                continue
            ts = [t for t, _ in inl]
            first, last = min(ts), max(ts)
            if last - first < min_span:
                continue
            if (n - 1 - last) > max_stale:          # not touched recently -> not a live level
                continue
            # violation: between first & last touch, did price live on the wrong side?
            seg = np.arange(first, last + 1)
            ln = _line_at(p1, t1, slope, seg)
            if kind == "res":
                viol = close[first:last + 1] - ln > viol_atr * atr_arr[first:last + 1]
            else:
                viol = ln - close[first:last + 1] > viol_atr * atr_arr[first:last + 1]
            if viol.mean() > max_viol_frac:
                continue
            price_now = float(_line_at(p1, t1, slope, n - 1))
            strength = sum(0.5 ** ((n - 1 - t) / halflife) for t in ts)
            cands.append({"kind": kind, "slope": slope, "price_now": price_now,
                          "touches": len(inl), "inliers": inl, "first": first, "last": last,
                          "p1": p1, "t1": t1, "strength": strength})
    # dedupe: two lines sharing >=2 pivots are the same line; keep the stronger
    cands.sort(key=lambda d: (-d["touches"], -d["strength"]))
    kept = []
    for c in cands:
        cs = set(c["inliers"])
        if all(len(cs & set(k["inliers"])) < 2 for k in kept):
            kept.append(c)
    return kept


def find_wedges(high, low, close, atr_window=14, **kw):
    high = np.asarray(high, float); low = np.asarray(low, float); close = np.asarray(close, float)
    atr_arr = wilder_atr(high, low, close, atr_window)
    atr_arr = np.where(np.isnan(atr_arr) | (atr_arr <= 0), np.nanmedian(atr_arr), atr_arr)
    n = len(close)
    highs, lows = swing_pivots(high, low, k=kw.pop("k", 4))
    res = find_trendlines(highs, close, atr_arr, n, "res", **kw)
    sup = find_trendlines(lows, close, atr_arr, n, "sup", **kw)
    return res, sup, atr_arr, (highs, lows)


if __name__ == "__main__":
    import sys, os, duckdb
    HERE = os.path.dirname(os.path.abspath(__file__))
    DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")
    sym = sys.argv[1].upper() if len(sys.argv) > 1 else "VZ"
    nd = int(sys.argv[2]) if len(sys.argv) > 2 else 252
    con = duckdb.connect(DB, read_only=True)
    d = con.execute("SELECT high,low,close FROM ohlcv WHERE symbol=? ORDER BY date DESC LIMIT ?",
                    [sym, nd]).df().iloc[::-1]
    con.close()
    h, l, c = (d[x].to_numpy(float) for x in ("high", "low", "close"))
    res, sup, atr_arr, (highs, lows) = find_wedges(h, l, c)
    print(f"{sym}: {len(highs)} swing highs, {len(lows)} swing lows, "
          f"close={c[-1]:.2f}, ATR={atr_arr[-1]:.2f}")
    for tag, lines in (("RESISTANCE", res), ("SUPPORT", sup)):
        print(f"\n{tag} wedges ({len(lines)}):")
        for L in sorted(lines, key=lambda d: -d["strength"]):
            dr = "rising" if L["slope"] > 0 else "falling"
            slope_day = L["slope"]
            print(f"  now {L['price_now']:7.2f}  {dr:7} ({slope_day:+.3f}/day)  "
                  f"touches={L['touches']}  span bars[{L['first']}..{L['last']}]  "
                  f"strength={L['strength']:.2f}")
