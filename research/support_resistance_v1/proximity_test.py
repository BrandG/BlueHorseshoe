"""Proximity test — does being near a strong support level predict a bounce?

The bridge from detecting levels to testing them. For every bar in a range-bound universe
we PIT-detect reversal levels (only pivots confirmed by that bar), measure the distance DOWN
to the nearest support level (ATR units), and record the forward return. The hypothesis
(Brand's original): close to a strong support -> price bounces.

Two rigor guards, learned from the prior campaign that died on exactly this question:
  * POINT-IN-TIME levels (cluster_pivots enforces b+k<=t) -- no level knows a future touch.
  * PULLBACK-MATCHED control -- 'near support' is confounded with 'has fallen' (which
    mean-reverts on its own). We expose each bin's pullback depth, then ask whether near-a-
    -level beats far-from-level among bars matched on pullback depth. If not, the level adds
    nothing beyond 'price is low'.

Overlapping forward windows -> stats are autocorrelated; treat these as effect sizes, formal
significance needs Newey-West (next pass). Reports distance bins, character split, strong vs
weak, and the matched control.
"""
import sys, os
import numpy as np, duckdb

sys.path.insert(0, os.path.dirname(__file__))
from reversal_profile import build_pivots, cluster_pivots       # noqa: E402
from detector import wilder_atr                                  # noqa: E402
from detector_v3 import range_score                             # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")
START = "2016-01-01"
ER_MAX = 0.11
WARMUP = 80
HORIZONS = [10, 20]
DIST_BINS = [0.0, 0.5, 1.0, 2.0, 4.0, np.inf]
PB_LO, PB_HI = 1.0, 3.0      # 'pulled back' = close this many ATR below the recent-20 high
NEAR, FAR = 0.75, 1.5        # matched control: near a level vs far from any level


def collect(universe, con):
    recs = []   # each: (sym, dist, char, strong, pullback, {H: (fwdR, mfe, mae)})
    for sym in universe:
        d = con.execute("SELECT high,low,close FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",
                        [sym, START]).df()
        h, l, c = (d[x].to_numpy(float) for x in ("high", "low", "close"))
        n = len(c)
        if n < WARMUP + max(HORIZONS) + 5:
            continue
        atr = wilder_atr(h, l, c, 14)
        atr = np.where(np.isnan(atr) | (atr <= 0), np.nanmedian(atr), atr)
        pivots = build_pivots(h, l, 3)
        Hmax = max(HORIZONS)
        for t in range(WARMUP, n - Hmax):
            a = atr[t]
            levels, _ = cluster_pivots(pivots, atr, c, as_of=t)
            below = [L for L in levels if L["price"] < c[t]]
            if not below:
                continue
            near = max(below, key=lambda L: L["price"])          # closest support below
            dist = (c[t] - near["price"]) / a
            strengths = [L["strength"] for L in levels]
            strong = near["strength"] >= np.median(strengths)
            pull = (h[t - 20:t].max() - c[t]) / a                # depth below recent high
            outs = {}
            for H in HORIZONS:
                outs[H] = ((c[t + H] - c[t]) / a,
                           (h[t + 1:t + H + 1].max() - c[t]) / a,
                           (c[t] - l[t + 1:t + H + 1].min()) / a)
            recs.append((sym, dist, near["character"], strong, pull, outs))
    return recs


def _stat(rows, H, idx=0):
    if not rows:
        return 0, float("nan"), float("nan")
    vals = np.array([r[5][H][idx] for r in rows])
    return len(rows), float(vals.mean()), float((vals > 0).mean())


def main():
    con = duckdb.connect(DB, read_only=True)
    cand = [s.strip() for s in open(os.path.join(HERE, "symbols.txt"))]
    universe = []
    for s in cand:
        d = con.execute("SELECT close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",
                        [s, START]).df()
        c = d.close.to_numpy(float); v = d.volume.to_numpy(float)
        if len(c) < 900 or not (5 <= c[-1] <= 500):
            continue
        if np.median(c[-120:] * v[-120:]) < 3e6:
            continue
        rs = range_score(c)
        if not np.isnan(rs) and rs <= ER_MAX:
            universe.append(s)
    print(f"range-bound universe: {len(universe)} symbols", flush=True)

    recs = collect(universe, con)
    con.close()
    print(f"observations (bars with a support below): {len(recs)}\n")

    for H in HORIZONS:
        print(f"================  HORIZON {H} bars  ================")
        print(f"{'dist-to-support (ATR)':>22} {'n':>7} {'fwdR':>8} {'win%':>6} "
              f"{'MFE':>6} {'MAE':>6} {'avgPullback':>11}")
        for lo, hi in zip(DIST_BINS[:-1], DIST_BINS[1:]):
            rows = [r for r in recs if lo <= r[1] < hi]
            n, fwd, win = _stat(rows, H, 0)
            _, mfe, _ = _stat(rows, H, 1); _, mae, _ = _stat(rows, H, 2)
            pull = np.mean([r[4] for r in rows]) if rows else float("nan")
            lab = f"[{lo:.1f},{hi:.1f})" if np.isfinite(hi) else f"[{lo:.1f},inf)"
            print(f"{lab:>22} {n:>7} {fwd:>+8.3f} {win:>6.0%} {mfe:>6.2f} {mae:>6.2f} {pull:>11.2f}")

        print(f"\n  near-support (dist<1.0) by LEVEL CHARACTER:")
        near_rows = [r for r in recs if r[1] < 1.0]
        for ch in ("flip", "support", "resistance"):
            rows = [r for r in near_rows if r[2] == ch]
            n, fwd, win = _stat(rows, H, 0)
            print(f"    {ch:>11}: n={n:>6}  fwdR={fwd:>+.3f}  win={win:.0%}")
        sr = [r for r in near_rows if r[3]]; wk = [r for r in near_rows if not r[3]]
        print(f"    {'strong':>11}: n={len(sr):>6}  fwdR={_stat(sr,H,0)[1]:>+.3f}  win={_stat(sr,H,0)[2]:.0%}")
        print(f"    {'weak':>11}: n={len(wk):>6}  fwdR={_stat(wk,H,0)[1]:>+.3f}  win={_stat(wk,H,0)[2]:.0%}")

        # pullback-matched control: among similarly pulled-back bars, near vs far from a level
        pb = [r for r in recs if PB_LO <= r[4] <= PB_HI]
        nearL = [r for r in pb if r[1] < NEAR]
        farL = [r for r in pb if r[1] > FAR]
        nstrong = [r for r in nearL if r[3]]
        print(f"\n  CONTROL (pulled back {PB_LO}-{PB_HI} ATR below recent high):")
        print(f"    near a level (<{NEAR}):  n={len(nearL):>6}  fwdR={_stat(nearL,H,0)[1]:>+.3f}  win={_stat(nearL,H,0)[2]:.0%}")
        print(f"    near a STRONG level:    n={len(nstrong):>6}  fwdR={_stat(nstrong,H,0)[1]:>+.3f}  win={_stat(nstrong,H,0)[2]:.0%}")
        print(f"    far from any level (>{FAR}): n={len(farL):>6}  fwdR={_stat(farL,H,0)[1]:>+.3f}  win={_stat(farL,H,0)[2]:.0%}")
        d_near = _stat(nearL, H, 0)[1]; d_far = _stat(farL, H, 0)[1]
        print(f"    --> level edge (near - far): {d_near - d_far:+.3f} ATR\n")


if __name__ == "__main__":
    main()
