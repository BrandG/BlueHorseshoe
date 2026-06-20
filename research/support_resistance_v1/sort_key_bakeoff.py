"""Sort-key bake-off: does ANY ranking key sort pure-support firings by realized R?

The live RangeSupport sleeve currently emits a flat score -> candidates fall out in
ALPHABETICAL order. This asks whether a real key separates the winners from the losers.
We already know S/R-as-SELECTION is ~closed (edge = bracket + exit), so the honest bar is:
rank every historical firing by a key, tercile it, and test whether top-tercile per-trade R
exceeds bottom-tercile with cluster-by-symbol robust SE (overlapping windows -> naive SE lies).

Reuses the validated harness verbatim: same universe (symbols.txt, ER-gated), same entry
(pure-support, NEAR/APPROACH/GAP gates), same bracket (1-ATR stop, no-target exit at H bars),
same cluster-robust machinery as significance_bracket.py. Only addition: per-firing keys.

Keys tested (direction noted in output via sign of top-minus-bottom):
  touches        # Brand's suggestion: number of support hits
  strength       # detector's recency-weighted x swing-depth score
  recency_sum    # how recent the touches are (sum of half-life weights)
  fresh          # -bars since last touch (higher = more recently defended)
  proximity      # -dist_atr (higher = entry closer to the level)
  headroom_atr   # ATR distance up to the next overhead band (room for the no-TP ratchet)

Robustness on any key that separates: interleaved calendar-quarter split (A & B) + 24mo holdout.
"""
import sys, os
import numpy as np, duckdb
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from reversal_profile import build_pivots, cluster_pivots                  # noqa: E402
from detector import wilder_atr                                            # noqa: E402
from detector_v3 import range_score                                        # noqa: E402
from target_sweep import START, ER_MAX, WARMUP, NEAR, APPROACH, GAP        # noqa: E402
from significance_bracket import (run_trade, cluster_ols_d, quarter_parity,  # noqa: E402
                                  HOLDOUT_START, H_MAX)

H = 25                       # validated horizon
STOP_ATR = 1.0


def collect_keyed(universe, con):
    """One row per pure-support firing: (sym, date, R_at_H, {key: value})."""
    rows = []
    for sym in universe:
        d = con.execute("SELECT date,high,low,close FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",
                        [sym, START]).df()
        dates = d["date"].to_numpy("datetime64[D]")
        h, l, c = (d[x].to_numpy(float) for x in ("high", "low", "close"))
        n = len(c)
        if n < WARMUP + H_MAX + 5:
            continue
        atr = wilder_atr(h, l, c, 14)
        atr = np.where(np.isnan(atr) | (atr <= 0), np.nanmedian(atr), atr)
        pivots = build_pivots(h, l, 3)
        last = -10**9
        for t in range(WARMUP, n - H_MAX):
            a = atr[t]
            levels, _ = cluster_pivots(pivots, atr, c, as_of=t)
            ps = [L for L in levels if L["character"] == "support" and L["price"] < c[t]]
            if not ps:
                continue
            near = max(ps, key=lambda L: L["price"])
            if (c[t] - near["price"]) / a > NEAR:
                continue
            lo = max(0, t - APPROACH)
            if c[lo:t].max() <= near["price"] + NEAR * a:
                continue
            if t - last < GAP:
                continue
            last = t
            r = run_trade(t, h, l, c, atr, n, H)
            above = [L["price"] for L in levels if L["price"] > c[t]]   # any overhead band
            headroom = (min(above) - c[t]) / a if above else np.inf     # open sky -> inf
            rows.append((sym, dates[t], r, {
                "touches": float(near["touches"]),
                "strength": near["strength"],
                "recency_sum": near["recency_sum"],
                "fresh": float(-(t - near["last"])),          # higher = touched more recently
                "proximity": float(-(c[t] - near["price"]) / a),  # higher = closer to level
                "headroom_atr": headroom,
            }))
    return rows


def tercile_edge(rows, key, mask=None):
    """Mean R in bottom/mid/top tercile of `key`, and cluster-t on (top - bottom).

    Returns dict with tercile means, n, the top-minus-bottom edge, cluster_t, and whether
    the three means are monotone. `mask` optionally restricts to a subset of rows.
    """
    rr = [r for r in rows if (mask is None or mask(r))]
    vals = np.array([r[3][key] for r in rr], float)
    y = np.array([r[2] for r in rr], float)
    syms = np.array([r[0] for r in rr])
    finite = np.isfinite(vals)
    # inf (open-sky headroom) always belongs in the top bucket; rank by value with inf highest.
    order_val = np.where(finite, vals, np.nanmax(vals[finite]) + 1.0 if finite.any() else 0.0)
    q1, q2 = np.quantile(order_val, [1 / 3, 2 / 3])
    t1 = order_val <= q1
    t3 = order_val > q2
    t2 = ~t1 & ~t3
    means = [y[t1].mean(), y[t2].mean(), y[t3].mean()]
    ns = [int(t1.sum()), int(t2.sum()), int(t3.sum())]
    # cluster-by-symbol t on top-minus-bottom
    sel = t1 | t3
    d = t3[sel].astype(float)
    symids = {s: i for i, s in enumerate(sorted(set(syms[sel])))}
    g = np.array([symids[s] for s in syms[sel]])
    beta, se, tcl = cluster_ols_d(y[sel], d, g)
    mono = (means[0] <= means[1] <= means[2]) or (means[0] >= means[1] >= means[2])
    return {"means": means, "ns": ns, "edge": beta, "t": tcl, "mono": mono}


def main():
    con = duckdb.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                      "data", "ohlcv.duckdb"), read_only=True)
    cand = [s.strip() for s in open(os.path.join(os.path.dirname(__file__), "symbols.txt"))]
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
    rows = collect_keyed(universe, con)
    con.close()

    y = np.array([r[2] for r in rows])
    base = y.mean()
    print(f"universe {len(universe)} names | n={len(rows)} pure-support firings | H={H} bars | "
          f"R = 1-ATR risk")
    print(f"baseline mean R (all firings, no sort) = {base:+.3f}R\n")
    print(f"{'key':14} {'botT R':>8} {'midT R':>8} {'topT R':>8} {'top-bot':>9} {'clstr_t':>8} "
          f"{'mono':>5}   {'holdout/split (top-bot edge)':>0}")
    print("-" * 100)

    keys = ["touches", "strength", "recency_sum", "fresh", "proximity", "headroom_atr"]
    for key in keys:
        res = tercile_edge(rows, key)
        # robustness on the top-bottom edge
        subs = []
        for lab, mask in (("A", lambda r: quarter_parity(r[1]) == 0),
                          ("B", lambda r: quarter_parity(r[1]) == 1),
                          ("hold24", lambda r: r[1] >= HOLDOUT_START)):
            try:
                e = tercile_edge(rows, key, mask)["edge"]
                subs.append(f"{lab}={e:+.3f}")
            except Exception:
                subs.append(f"{lab}=n/a")
        m = res["means"]
        print(f"{key:14} {m[0]:+8.3f} {m[1]:+8.3f} {m[2]:+8.3f} {res['edge']:+9.3f} "
              f"{res['t']:+8.2f} {str(res['mono']):>5}   {'  '.join(subs)}")
    print("\nRead: a key 'sorts' if top-bot is sizeable, cluster_t |>=2|, mono=True, and the "
          "sign holds in A & B & hold24. Otherwise it's alphabetical-with-extra-steps.")


if __name__ == "__main__":
    main()
