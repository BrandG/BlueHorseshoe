"""Significance test for the proximity 'level edge' (near support - far from any level,
pullback-matched). 122k overlapping observations are heavily autocorrelated, so a naive
SE lies. Four robust views:

  1. CLUSTER-BY-SYMBOL robust SE on fwd ~ near_dummy. Clustering on symbol absorbs ALL
     within-symbol serial correlation from overlapping forward windows -- strictly more
     general than Newey-West (which assumes one lag shape). This is the headline.
  2. PER-SYMBOL t-test: each symbol contributes ONE number (its own near-minus-far mean),
     t-test across the 60 -> immune to within-symbol autocorrelation by construction.
  3. NEWEY-WEST on the daily near-minus-far PORTFOLIO spread (lag = horizon).
  4. SPLIT-HALF: the edge must show up in BOTH the first and second half of the sample.

Reported for H=10 and H=20, and for the variants that actually predicted (plain-support,
weak) vs the strength score that didn't.
"""
import sys, os
import numpy as np, duckdb
from collections import defaultdict

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
PB_LO, PB_HI = 1.0, 3.0
NEAR, FAR = 0.75, 1.5


def collect(universe, con):
    """One row per pullback-matched bar: (sym, t_global, group, char, strong, {H:fwdR})."""
    rows = []
    gt = 0
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
            pull = (h[t - 20:t].max() - c[t]) / a
            if not (PB_LO <= pull <= PB_HI):                 # matched subsample only
                continue
            levels, _ = cluster_pivots(pivots, atr, c, as_of=t)
            below = [L for L in levels if L["price"] < c[t]]
            if not below:
                continue
            near = max(below, key=lambda L: L["price"])
            dist = (c[t] - near["price"]) / a
            if dist < NEAR:
                group = "near"
            elif dist > FAR:
                group = "far"
            else:
                continue
            strong = near["strength"] >= np.median([L["strength"] for L in levels])
            outs = {H: (c[t + H] - c[t]) / a for H in HORIZONS}
            rows.append((sym, t, group, near["character"], strong, outs))
        gt += 1
    return rows


def cluster_ols(y, d, groups):
    """OLS y ~ 1 + d with cluster-robust SE on the d coefficient (= mean(d=1)-mean(d=0)).
    Returns (beta, se, t). groups = integer cluster ids."""
    X = np.column_stack([np.ones_like(d, float), d.astype(float)])
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    resid = y - X @ beta
    meat = np.zeros((2, 2))
    for g in np.unique(groups):
        m = groups == g
        Xg = X[m]; eg = resid[m]
        s = Xg.T @ eg
        meat += np.outer(s, s)
    G = len(np.unique(groups))
    adj = G / (G - 1) if G > 1 else 1.0
    V = adj * (XtX_inv @ meat @ XtX_inv)
    se = np.sqrt(V[1, 1])
    return float(beta[1]), float(se), float(beta[1] / se if se else np.nan)


def newey_west_mean(x, lag):
    """NW t-stat for the mean of a (possibly autocorrelated) series."""
    x = np.asarray(x, float); n = len(x); mu = x.mean(); e = x - mu
    g0 = (e @ e) / n
    var = g0
    for k in range(1, lag + 1):
        if k >= n:
            break
        gk = (e[k:] @ e[:-k]) / n
        var += 2 * (1 - k / (lag + 1)) * gk
    se = np.sqrt(var / n)
    return mu, float(mu / se if se else np.nan)


def per_symbol_ttest(rows, H):
    """Each symbol's own (mean near - mean far); t-test the per-symbol diffs across symbols."""
    bysym = defaultdict(lambda: {"near": [], "far": []})
    for sym, t, grp, ch, st, outs in rows:
        bysym[sym][grp].append(outs[H])
    diffs = []
    for sym, gg in bysym.items():
        if gg["near"] and gg["far"]:
            diffs.append(np.mean(gg["near"]) - np.mean(gg["far"]))
    diffs = np.array(diffs)
    m = diffs.mean(); se = diffs.std(ddof=1) / np.sqrt(len(diffs))
    npos = int((diffs > 0).sum())
    return m, float(m / se if se else np.nan), len(diffs), npos


def edge_report(rows, H, sel=lambda r: True, tag=""):
    sub = [r for r in rows if (r[2] == "far") or (r[2] == "near" and sel(r))]
    y = np.array([r[5][H] for r in sub])
    d = np.array([1 if r[2] == "near" else 0 for r in sub])
    syms = {s: i for i, s in enumerate(sorted({r[0] for r in sub}))}
    g = np.array([syms[r[0]] for r in sub])
    beta, se, tcl = cluster_ols(y, d, g)
    # daily portfolio spread
    daily = defaultdict(lambda: {"near": [], "far": []})
    for r in sub:
        daily[r[1]][("near" if r[2] == "near" else "far")].append(r[5][H])
    spread = [np.mean(v["near"]) - np.mean(v["far"]) for v in daily.values() if v["near"] and v["far"]]
    nw_mu, nw_t = newey_west_mean(spread, H) if spread else (np.nan, np.nan)
    ps_m, ps_t, ps_n, ps_pos = per_symbol_ttest(sub, H)
    print(f"  H={H} {tag}: edge={beta:+.3f} ATR  "
          f"cluster_t={tcl:+.2f}  NW_t={nw_t:+.2f}  "
          f"perSym t={ps_t:+.2f} ({ps_pos}/{ps_n} sym +)")


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

    rows = collect(universe, con)
    con.close()
    nnear = sum(1 for r in rows if r[2] == "near"); nfar = sum(1 for r in rows if r[2] == "far")
    print(f"matched subsample: {len(rows)} bars ({nnear} near, {nfar} far)\n")

    for H in HORIZONS:
        print(f"---- near (any level) vs far ----")
        edge_report(rows, H, tag="ALL near")
        edge_report(rows, H, sel=lambda r: r[3] == "support", tag="pure-SUPPORT near")
        edge_report(rows, H, sel=lambda r: r[3] == "flip", tag="FLIP near")
        edge_report(rows, H, sel=lambda r: not r[4], tag="WEAK near")
        edge_report(rows, H, sel=lambda r: r[4], tag="STRONG near")
        # split-half robustness on ALL near
        tmax = max(r[1] for r in rows)
        for half, lab in (((lambda r: r[1] <= tmax / 2), "1st-half"),
                          ((lambda r: r[1] > tmax / 2), "2nd-half")):
            sub = [r for r in rows if half(r)]
            edge_report(sub, H, tag=lab)
        print()


if __name__ == "__main__":
    main()
