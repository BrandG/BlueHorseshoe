"""Recovery-time study: after price touches a fused S/R level and reacts, how long
until the bounce actually PAYS (reaches +K ATR)?  Answers Brand's "what's the
average recovery time frame" -> sets the hold period.

For every reaction touch on a fused level:
  support bounce (departed up): bars from the shelf until high first reaches
    touch_price + K*ATR, for K in TARGETS, censored at HORIZON bars; plus the MFE
    (max favorable excursion, ATR) and the bar it peaked.
  resistance reject (departed down): symmetric on the downside.
Aggregated over the RANGE-BOUND universe (low Kaufman efficiency ratio).

This is a descriptive timing study (looks forward from each historical touch on
purpose) -- not a point-in-time trading signal.
"""
import sys, os
import numpy as np, duckdb

sys.path.insert(0, os.path.dirname(__file__))
from fusion import fuse_levels  # noqa: E402
from detector_v3 import range_score  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")
START = "2016-01-01"
HORIZON = 40            # bars (~2 months) to allow the bounce to play out
TARGETS = [1.0, 1.5, 2.0, 3.0]   # ATR profit targets
ER_MAX = 0.11          # range-bound universe cutoff


def recovery_for_touch(side, sb, P, h, l, atr, n):
    """Return (dict target->bars_or_None, mfe_atr, mfe_bar) for one touch."""
    a = atr[sb]
    if np.isnan(a) or a <= 0:
        return None
    end = min(sb + HORIZON, n - 1)
    if end <= sb:
        return None
    res = {}
    if side == "up":
        seg = h[sb + 1:end + 1]
        for K in TARGETS:
            hit = np.where(seg >= P + K * a)[0]
            res[K] = int(hit[0] + 1) if len(hit) else None
        mfe = (seg.max() - P) / a
        mfe_bar = int(np.argmax(seg) + 1)
    else:
        seg = l[sb + 1:end + 1]
        for K in TARGETS:
            hit = np.where(seg <= P - K * a)[0]
            res[K] = int(hit[0] + 1) if len(hit) else None
        mfe = (P - seg.min()) / a
        mfe_bar = int(np.argmin(seg) + 1)
    return res, mfe, mfe_bar


def main():
    con = duckdb.connect(DB, read_only=True)
    cand = [s.strip() for s in open(os.path.join(HERE, "symbols.txt"))]
    # build range-bound liquid universe
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
    print(f"range-bound universe: {len(universe)} symbols (ER<= {ER_MAX})", flush=True)

    # collect per-side recovery stats
    bars = {"up": {K: [] for K in TARGETS}, "down": {K: [] for K in TARGETS}}
    reached = {"up": {K: 0 for K in TARGETS}, "down": {K: 0 for K in TARGETS}}
    ntouch = {"up": 0, "down": 0}
    mfe_bars = {"up": [], "down": []}
    mfe_atr = {"up": [], "down": []}

    for si, s in enumerate(universe):
        d = con.execute("SELECT high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? "
                        "ORDER BY date", [s, START]).df()
        h, l, c, v = (d[x].to_numpy(float) for x in ("high", "low", "close", "volume"))
        n = len(c)
        levels, atr, _, _ = fuse_levels(h, l, c, v)
        for lv in levels:
            for (_, sb, P, _, dr) in lv["reactions"]:
                side = "up" if dr > 0 else "down"
                out = recovery_for_touch(side, sb, P, h, l, atr, n)
                if out is None:
                    continue
                res, mfe, mfe_bar = out
                ntouch[side] += 1
                mfe_atr[side].append(mfe); mfe_bars[side].append(mfe_bar)
                for K in TARGETS:
                    if res[K] is not None:
                        bars[side][K].append(res[K]); reached[side][K] += 1
        if (si + 1) % 25 == 0:
            print(f"  {si+1}/{len(universe)}", flush=True)
    con.close()

    def pct(x): return np.percentile(x, [25, 50, 75]) if x else [np.nan]*3
    for side, label in (("up", "SUPPORT bounce (time to rise +K ATR)"),
                        ("down", "RESISTANCE reject (time to fall +K ATR)")):
        nt = ntouch[side]
        print(f"\n===== {label} =====  ({nt} touches)")
        print(f"  {'target':>8} {'%reached/40bar':>14} {'median bars':>12} {'IQR bars':>14}")
        for K in TARGETS:
            b = bars[side][K]; p = pct(b)
            frac = reached[side][K] / nt if nt else float('nan')
            print(f"  +{K:>4.1f}ATR {frac:>13.0%} {p[1]:>12.0f} {f'{p[0]:.0f}-{p[2]:.0f}':>14}")
        mb = pct(mfe_bars[side]); ma = pct(mfe_atr[side])
        print(f"  MFE within {HORIZON}b: median {np.median(mfe_atr[side]):.2f} ATR, "
              f"peaks at median bar {np.median(mfe_bars[side]):.0f} (IQR {mb[0]:.0f}-{mb[2]:.0f})")
    print("\ndone.")


if __name__ == "__main__":
    main()
