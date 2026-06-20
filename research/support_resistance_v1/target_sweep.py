"""How far do pure-support trades run, and where's the best target?

Keep the 1-ATR stop (defines survival; R is measured in units of that 1-ATR risk). For each
PIT pure-support approach, walk forward H bars and record:
  * mfe  : max favorable excursion in R reached BEFORE the stop is hit (or horizon),
  * stopped : did the low hit the 1-ATR stop within H bars,
  * final : close-at-horizon return in R.
From (mfe, stopped, final) the outcome for ANY fixed target T follows: target hit (mfe>=T) ->
+T; else stopped -> -1; else exit at horizon -> final. So we sweep T cheaply and find the
expectancy-maximizing target, with a random-entry baseline at each T. Also report the MFE
distribution (how high they generally go) and a no-target time-exit for comparison.
"""
import sys, os
import numpy as np, duckdb

sys.path.insert(0, os.path.dirname(__file__))
from reversal_profile import build_pivots, cluster_pivots       # noqa: E402
from detector import wilder_atr                                  # noqa: E402
from detector_v3 import range_score                             # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")
START = "2016-01-01"; ER_MAX = 0.11
WARMUP = 80; NEAR = 0.5; APPROACH = 10; GAP = 15; H = 20; STOP_ATR = 1.0
TARGETS = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]


def trade(t, entry, stop_px, h, l, c, n):
    """Return (mfe_R, stopped, final_R). mfe is max favorable in R before the stop is hit."""
    risk = entry - stop_px
    end = min(t + H, n - 1)
    mfe = 0.0; stopped = False
    for k in range(t + 1, end + 1):
        if l[k] <= stop_px:
            stopped = True; break
        mfe = max(mfe, (h[k] - entry) / risk)
    final = (c[end] - entry) / risk
    return mfe, stopped, final


def collect(universe, con):
    real, rand = [], []
    for si, sym in enumerate(universe):
        d = con.execute("SELECT high,low,close FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",
                        [sym, START]).df()
        h, l, c = (d[x].to_numpy(float) for x in ("high", "low", "close"))
        n = len(c)
        if n < WARMUP + H + 5:
            continue
        atr = wilder_atr(h, l, c, 14)
        atr = np.where(np.isnan(atr) | (atr <= 0), np.nanmedian(atr), atr)
        pivots = build_pivots(h, l, 3)
        rng = np.random.default_rng(11 + si)
        last = -10**9; entries = []
        for t in range(WARMUP, n - H):
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
        for t in entries:
            real.append(trade(t, c[t], c[t] - STOP_ATR * atr[t], h, l, c, n))
        for t in rng.integers(WARMUP, n - H, size=len(entries)):
            rand.append(trade(int(t), c[t], c[t] - STOP_ATR * atr[t], h, l, c, n))
    return real, rand


def exp_at_target(trades, T):
    R = []
    for mfe, stopped, final in trades:
        if mfe >= T:
            R.append(T)
        elif stopped:
            R.append(-1.0)
        else:
            R.append(final)
    R = np.array(R)
    return R.mean(), (R > 0).mean(), (np.array([m for m, _, _ in trades]) >= T).mean()


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

    mfe = np.array([m for m, _, _ in real])
    stp = np.array([s for _, s, _ in real])
    surv = mfe[~stp]                                       # MFE among trades that didn't stop
    print(f"n={len(real)} pure-support trades, 1-ATR stop (R = 1 ATR of risk)\n")
    print("MFE — how far they run (in R) BEFORE stop/horizon:")
    print(f"  ALL trades:      median {np.median(mfe):.2f}R  p75 {np.percentile(mfe,75):.2f}R  "
          f"p90 {np.percentile(mfe,90):.2f}R  max {mfe.max():.1f}R")
    print(f"  SURVIVORS (not stopped, {len(surv)} = {len(surv)/len(real):.0%}): "
          f"median {np.median(surv):.2f}R  p75 {np.percentile(surv,75):.2f}R  "
          f"p90 {np.percentile(surv,90):.2f}R")

    print(f"\nTarget sweep (1-ATR stop, expectancy in R; 'edge' = real - random):")
    print(f"{'target':>8} {'hit%':>6} {'exp(R)':>8} {'randExp':>8} {'edge':>7}")
    best = None
    for T in TARGETS:
        e, _, hit = exp_at_target(real, T)
        re, _, _ = exp_at_target(rand, T)
        print(f"{T:>6.1f}R {hit:>6.0%} {e:>+8.3f} {re:>+8.3f} {e-re:>+7.3f}")
        if best is None or e > best[1]:
            best = (T, e)
    # no-target time exit (let it run to horizon, only the stop caps downside)
    nt = np.array([-1.0 if s else f for _, s, f in real])
    ntr = np.array([-1.0 if s else f for _, s, f in rand])
    oracle = np.array([m if not s else -1.0 for m, s, _ in real])   # exit at the peak (ceiling)
    print(f"\n  no target (exit at 20-bar horizon, stop caps loss): "
          f"real {nt.mean():+.3f}R  random {ntr.mean():+.3f}R  edge {nt.mean()-ntr.mean():+.3f}")
    print(f"  oracle (exit at the MFE peak — unreachable ceiling):  {oracle.mean():+.3f}R")
    print(f"\n  best fixed target: {best[0]:.1f}R at {best[1]:+.3f}R "
          f"(vs +0.104R at the 1.5R target we used).")


if __name__ == "__main__":
    main()
