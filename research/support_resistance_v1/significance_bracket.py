"""Significance gate on the WINNER: pure-support entry, 1-ATR stop, no-target exit at H bars.

Frontier #5. The earlier significance.py tested the proximity (near-vs-far, close-to-close) edge;
this tests the actual bracketed realized-R result. Trades from one symbol overlap in time (holds
of H bars, entries GAP=15 apart, so neighbours overlap) -> naive SE lies. Robust views:

  HEADLINE  cluster-by-symbol robust SE — absorbs ALL within-symbol serial correlation from
            overlapping windows; strictly more general than Newey-West (handoff's own note).
  PER-SYMBOL each symbol contributes ONE number; t across the 60 -> immune to within-symbol
            autocorrelation by construction.
  NW        Newey-West (lag=H-1) on the daily-mean-R series — the memory-standard cross-check.

TWO nulls, because random entries in this rangey universe also make money (drift/beta):
  (A) is mean realized R > 0?                      -> the trade makes money
  (B) is mean R > a matched RANDOM entry?          -> the SUPPORT timing adds value beyond drift
      tested as R ~ d (d=1 real, 0 random), cluster-by-symbol SE on the d coefficient.

ROBUSTNESS (on the edge over random, per bud_validation_split_interleaved):
  * interleaved calendar-QUARTER split A/B (quarter parity -> COVID lands in BOTH halves);
    edge must be > 0 in A AND B.
  * recent-24mo HOLDOUT (entries on/after 2024-06-19): edge must hold there too.
"""
import sys, os
import numpy as np, duckdb
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from reversal_profile import build_pivots, cluster_pivots       # noqa: E402
from detector import wilder_atr                                  # noqa: E402
from detector_v3 import range_score                             # noqa: E402
from target_sweep import START, ER_MAX, WARMUP, NEAR, APPROACH, GAP  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")
STOP_ATR = 1.0
H_GRID = [20, 25, 30]
H_MAX = max(H_GRID)
HOLDOUT_START = np.datetime64("2024-06-19")     # last 24 months


def run_trade(t, h, l, c, atr, n, H):
    entry = c[t]; a = atr[t]; risk = a; stop = entry - STOP_ATR * a
    end = min(t + H, n - 1)
    for k in range(t + 1, end + 1):
        if l[k] <= stop:
            return (stop - entry) / risk
    return (c[end] - entry) / risk


def cluster_mean_t(y, groups):
    """Cluster-robust SE of a plain mean (intercept-only OLS). Returns (mean, se, t)."""
    y = np.asarray(y, float); n = len(y); mu = y.mean(); resid = y - mu
    meat = 0.0
    for g in np.unique(groups):
        meat += resid[groups == g].sum() ** 2
    G = len(np.unique(groups)); adj = G / (G - 1) if G > 1 else 1.0
    se = np.sqrt(adj * meat / n ** 2)
    return mu, se, float(mu / se if se else np.nan)


def cluster_ols_d(y, d, groups):
    """OLS y ~ 1 + d, cluster-robust SE on d coef (= mean(d=1)-mean(d=0)). Returns (beta,se,t)."""
    X = np.column_stack([np.ones_like(d, float), d.astype(float)])
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    resid = y - X @ beta
    meat = np.zeros((2, 2))
    for g in np.unique(groups):
        m = groups == g; Xg = X[m]; eg = resid[m]
        s = Xg.T @ eg; meat += np.outer(s, s)
    G = len(np.unique(groups)); adj = G / (G - 1) if G > 1 else 1.0
    V = adj * (XtX_inv @ meat @ XtX_inv); se = np.sqrt(V[1, 1])
    return float(beta[1]), float(se), float(beta[1] / se if se else np.nan)


def per_symbol_t(real_by_sym, rand_by_sym=None):
    """If rand given: t over per-symbol (mean_real - mean_rand). Else t over per-symbol mean_real."""
    diffs = []
    for s, rr in real_by_sym.items():
        if not rr:
            continue
        if rand_by_sym is None:
            diffs.append(np.mean(rr))
        elif rand_by_sym.get(s):
            diffs.append(np.mean(rr) - np.mean(rand_by_sym[s]))
    diffs = np.array(diffs); m = diffs.mean(); se = diffs.std(ddof=1) / np.sqrt(len(diffs))
    return m, float(m / se if se else np.nan), len(diffs), int((diffs > 0).sum())


def newey_west_mean(x, lag):
    x = np.asarray(x, float); n = len(x); mu = x.mean(); e = x - mu
    g0 = (e @ e) / n; var = g0
    for k in range(1, lag + 1):
        if k >= n:
            break
        gk = (e[k:] @ e[:-k]) / n
        var += 2 * (1 - k / (lag + 1)) * gk
    se = np.sqrt(var / n)
    return mu, float(mu / se if se else np.nan)


def collect(universe, con):
    """Per trade: (sym, date(np.datetime64), H->R for real) plus matched random R."""
    real, rand = [], []
    for si, sym in enumerate(universe):
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
        last = -10**9; entries = []
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
            last = t; entries.append(t)
        if not entries:
            continue
        rng = np.random.default_rng(11 + si)
        ridx = [int(x) for x in rng.integers(WARMUP, n - H_MAX, size=len(entries))]
        for t in entries:
            real.append((sym, dates[t], {H: run_trade(t, h, l, c, atr, n, H) for H in H_GRID}))
        for t in ridx:
            rand.append((sym, dates[t], {H: run_trade(t, h, l, c, atr, n, H) for H in H_GRID}))
    return real, rand


def quarter_parity(dt):
    dt = dt.astype("datetime64[M]").astype(int)            # months since epoch
    year, month = 1970 + dt // 12, dt % 12                 # month 0-11
    qi = year * 4 + month // 3
    return qi % 2                                          # 0 -> A, 1 -> B


def report(real, rand, H):
    yr = np.array([r[2][H] for r in real]); yn = np.array([r[2][H] for r in rand])
    symids = {s: i for i, s in enumerate(sorted({r[0] for r in real}))}
    gr = np.array([symids[r[0]] for r in real])
    # (A) real mean > 0
    mu, se, tcl = cluster_mean_t(yr, gr)
    rbs = defaultdict(list); nbs = defaultdict(list)
    for r in real: rbs[r[0]].append(r[2][H])
    for r in rand: nbs[r[0]].append(r[2][H])
    psm, pst, psn, pspos = per_symbol_t(rbs)
    # NW on daily-mean-R series
    daily = defaultdict(list)
    for r in real: daily[r[1]].append(r[2][H])
    series = [np.mean(daily[k]) for k in sorted(daily)]
    nwm, nwt = newey_west_mean(series, H - 1)
    # (B) edge over random (pooled, cluster on symbol)
    y = np.concatenate([yr, yn]); d = np.concatenate([np.ones(len(yr)), np.zeros(len(yn))])
    gd = np.concatenate([gr, np.array([symids[r[0]] for r in rand])])
    eb, ese, et = cluster_ols_d(y, d, gd)
    epsm, epst, epsn, epspos = per_symbol_t(rbs, nbs)

    print(f"==== H={H} bars ====")
    print(f"  (A) mean realized R = {mu:+.3f}R   cluster_t={tcl:+.2f}   "
          f"perSym t={pst:+.2f} ({pspos}/{psn} sym +)   NW_t={nwt:+.2f}  (lag {H-1})")
    print(f"  (B) edge over random = {eb:+.3f}R   cluster_t={et:+.2f}   "
          f"perSym t={epst:+.2f} ({epspos}/{epsn} sym +)")
    # robustness on edge over random
    def sub(rows, mask):
        return [r for r in rows if mask(r)]
    print(f"      split-half (interleaved calendar quarters; COVID in BOTH):")
    for lab, mask in (("A(even Q)", lambda r: quarter_parity(r[1]) == 0),
                      ("B(odd Q) ", lambda r: quarter_parity(r[1]) == 1),
                      ("holdout24", lambda r: r[1] >= HOLDOUT_START)):
        rr = sub(real, mask); nn = sub(rand, mask)
        if not rr or not nn:
            print(f"        {lab}: (empty)"); continue
        yy = np.array([x[2][H] for x in rr]); yyn = np.array([x[2][H] for x in nn])
        rm = yy.mean(); edge = yy.mean() - yyn.mean()
        print(f"        {lab}: n={len(rr):>4}  realR={rm:+.3f}  edge={edge:+.3f}  "
              f"({'EDGE>0' if edge > 0 else 'edge<=0 ***'}, {'R>0' if rm > 0 else 'R<=0 ***'})")
    print()


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
    real, rand = collect(universe, con)
    con.close()
    print(f"universe {len(universe)} names, n={len(real)} pure-support trades vs "
          f"{len(rand)} matched-random.  R = 1-ATR initial risk.")
    print(f"holdout = entries on/after {HOLDOUT_START}.\n")
    for H in H_GRID:
        report(real, rand, H)


if __name__ == "__main__":
    main()
