"""Trailing-stop exit sweep on the pure-support entry (frontier move #2).

The no-target time exit realizes +0.355R but leaves the run on the table: survivors' MFE
runs a median ~4R and the oracle (exit at the peak) ceiling is +0.90R. A trailing stop is the
natural tool to close that gap. We keep the SAME entry (pure-support approach) and the SAME
1-ATR initial risk (R is measured in that unit), and sweep an ATR-chandelier trail:

  stop_0 = entry - 1*ATR
  each bar (using only highs through the prior bar — no lookahead):
    if low <= stop: exit at stop          # realized R can be >0 once the trail locks gains
    else: stop = max(stop, run_max_high - M*ATR)   # ratchet up only, once activated

Two knobs:
  * M  = trail width in ATR (tight locks fast but whipsaws; wide lets it breathe).
  * A  = activation threshold in R — don't start trailing until MFE >= A, so early
         range-bound chop doesn't stop us out before the move develops. A=0 trails immediately.
Plus a breakeven-only reference (jump stop to entry after +1R, never trail).

The expensive step (per-bar pivot clustering to find entries) is done ONCE and cached; the
M/A/H grid is then swept cheaply over the cached contexts. Random-entry baseline uses the same
per-symbol random indices so the EDGE is comparable across the grid. References printed:
no-target (+0.355 target), oracle ceiling (+0.90), and best fixed target.
"""
import sys, os
import numpy as np, duckdb

sys.path.insert(0, os.path.dirname(__file__))
from reversal_profile import build_pivots, cluster_pivots       # noqa: E402
from detector import wilder_atr                                  # noqa: E402
from detector_v3 import range_score                             # noqa: E402
from target_sweep import START, ER_MAX, WARMUP, NEAR, APPROACH, GAP  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")
STOP_ATR = 1.0
M_GRID = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
A_GRID = [0.0, 1.0, 2.0]
H_GRID = [20, 40]
H_MAX = max(H_GRID)


def trailing_trade(t, h, l, c, atr, n, M, A, H):
    """Realized R under an ATR-chandelier trail. R unit = 1-ATR initial risk (atr at entry)."""
    entry = c[t]; a = atr[t]; risk = a
    stop = entry - STOP_ATR * a
    run_max = entry
    activated = (A <= 0)
    end = min(t + H, n - 1)
    for k in range(t + 1, end + 1):
        if l[k] <= stop:                       # stop in force this bar was set through k-1
            return (stop - entry) / risk
        run_max = max(run_max, h[k])
        if not activated and (run_max - entry) / risk >= A:
            activated = True
        if activated:
            stop = max(stop, run_max - M * a)
    return (c[end] - entry) / risk


def breakeven_trade(t, h, l, c, atr, n, H, be_at=1.0):
    """Reference: 1-ATR stop, jump to breakeven after +be_at R, never trail. No target."""
    entry = c[t]; a = atr[t]; risk = a
    stop = entry - STOP_ATR * a; run_max = entry
    end = min(t + H, n - 1)
    for k in range(t + 1, end + 1):
        if l[k] <= stop:
            return (stop - entry) / risk
        run_max = max(run_max, h[k])
        if (run_max - entry) / risk >= be_at:
            stop = max(stop, entry)
    return (c[end] - entry) / risk


def notarget_oracle(t, h, l, c, atr, n, H):
    """(+0.355 no-target realized, oracle peak) for reference — within horizon H."""
    entry = c[t]; a = atr[t]; risk = a; stop = entry - STOP_ATR * a
    end = min(t + H, n - 1); mfe = 0.0; stopped = False
    for k in range(t + 1, end + 1):
        if l[k] <= stop:
            stopped = True; break
        mfe = max(mfe, (h[k] - entry) / risk)
    nt = -1.0 if stopped else (c[end] - entry) / risk
    orc = -1.0 if stopped else mfe
    return nt, orc


def collect_contexts(universe, con):
    """Cluster once; return per-symbol arrays + real-entry and matched random-entry indices."""
    ctx = []
    for si, sym in enumerate(universe):
        d = con.execute("SELECT high,low,close FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",
                        [sym, START]).df()
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
        rand = [int(x) for x in rng.integers(WARMUP, n - H_MAX, size=len(entries))]
        ctx.append(dict(h=h, l=l, c=c, atr=atr, n=n, entries=entries, rand=rand))
    return ctx


def run_fn(ctx, fn):
    """Apply trade fn(t,h,l,c,atr,n) over all real and matched-random entries."""
    real, rand = [], []
    for x in ctx:
        for t in x["entries"]:
            real.append(fn(t, x["h"], x["l"], x["c"], x["atr"], x["n"]))
        for t in x["rand"]:
            rand.append(fn(t, x["h"], x["l"], x["c"], x["atr"], x["n"]))
    return np.array(real), np.array(rand)


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
    ctx = collect_contexts(universe, con)
    con.close()
    n_real = sum(len(x["entries"]) for x in ctx)
    print(f"universe {len(universe)} names, {len(ctx)} with entries, n={n_real} trades, "
          f"R = 1-ATR initial risk\n")

    for H in H_GRID:
        # references at this horizon (each entry returns (no_target_R, oracle_R))
        ref_real, ref_rand = run_fn(ctx, lambda t, h, l, c, a, n: notarget_oracle(t, h, l, c, a, n, H))
        nt_real = ref_real[:, 0]; nt_rand = ref_rand[:, 0]; orc_real = ref_real[:, 1]
        be_real, be_rand = run_fn(ctx, lambda t, h, l, c, a, n: breakeven_trade(t, h, l, c, a, n, H))
        print(f"================  HORIZON H={H} bars  ================")
        print(f"  reference  no-target : real {nt_real.mean():+.3f}R  rand {nt_rand.mean():+.3f}R  "
              f"edge {nt_real.mean()-nt_rand.mean():+.3f}  (win {(nt_real>0).mean():.0%})")
        print(f"  reference  oracle peak: {orc_real.mean():+.3f}R  (unreachable ceiling)")
        print(f"  reference  breakeven@1R: real {be_real.mean():+.3f}R  rand {be_rand.mean():+.3f}R  "
              f"edge {be_real.mean()-be_rand.mean():+.3f}  (win {(be_real>0).mean():.0%})")
        print(f"\n  chandelier trail  (real mean R / edge over random / win% / median R):")
        print(f"  {'A/M':>5} " + " ".join(f"{M:>14.1f}" for M in M_GRID))
        for A in A_GRID:
            cells = []
            for M in M_GRID:
                real, rand = run_fn(
                    ctx, lambda t, h, l, c, a, n, M=M, A=A: trailing_trade(t, h, l, c, a, n, M, A, H))
                cells.append(f"{real.mean():+.3f}/{real.mean()-rand.mean():+.3f}/"
                             f"{(real>0).mean():.0%}/{np.median(real):+.2f}")
            print(f"  A={A:>3.0f} " + " ".join(f"{s:>14}" for s in cells))
        print()


if __name__ == "__main__":
    main()
