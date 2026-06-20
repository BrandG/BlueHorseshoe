"""Sweep the up-day ratchet DISTANCE: stop -> close - M*ATR at the end of each up day, ratchet-only.

1 ATR was too tight (exits runners on the first pullback; mean R halved vs fixed). Does a WIDER
ratchet thread the needle — lock gains on the reverters while leaving the runners room? Sweep M and
compare to the fixed-stop incumbent, gap-aware fills, matched random. If any M beats fixed's +0.34R
(H=25), it's a real improvement; if mean R climbs monotonically toward fixed as M widens (i.e. the
best ratchet just *becomes* the fixed stop), the exit is already optimal and trailing can't help.
"""
import sys, os
import numpy as np, duckdb

sys.path.insert(0, os.path.dirname(__file__))
from exit_ratchet import collect                                 # noqa: E402  (reuse clustering)
from detector_v3 import range_score                             # noqa: E402
from target_sweep import START, ER_MAX                           # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")
M_GRID = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
H_GRID = [25, 60]


def simulate(t, o, h, l, c, atr, n, H, M):
    """M is None -> fixed 1-ATR stop, no trail. Else up-day ratchet to close - M*entryATR."""
    entry = c[t]; a = atr[t]; risk = a
    stop = entry - a
    end = min(t + H, n - 1)
    for k in range(t + 1, end + 1):
        if l[k] <= stop:
            fill = o[k] if o[k] <= stop else stop
            return (fill - entry) / risk, k - t
        if M is not None and c[k] > c[k - 1]:
            stop = max(stop, c[k] - M * a)
    return (c[end] - entry) / risk, end - t


def run(ctx, key, H, M):
    R, B = [], []
    for x in ctx:
        for t in x[key]:
            r, b = simulate(t, x["o"], x["h"], x["l"], x["c"], x["atr"], x["n"], H, M)
            R.append(r); B.append(b)
    return np.array(R), np.array(B, float)


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
    ctx = collect(universe, con)
    con.close()
    n = sum(len(x["entries"]) for x in ctx)
    print(f"universe {len(universe)} names, n={n} trades, gap-aware fills, R = 1-ATR risk\n")

    for H in H_GRID:
        print(f"================ H={H} bars ================")
        print(f"  {'up-day ratchet width':24} {'meanR':>7} {'edge':>7} {'medR':>6} {'win%':>5} "
              f"{'meanBars':>8} {'R/bar':>8}")
        for M, lab in [(None, "fixed (no trail)")] + [(m, f"close - {m} ATR") for m in M_GRID]:
            Rr, Br = run(ctx, "entries", H, M)
            Rn, _ = run(ctx, "rand", H, M)
            print(f"  {lab:24} {Rr.mean():>+7.3f} {Rr.mean()-Rn.mean():>+7.3f} "
                  f"{np.median(Rr):>+6.2f} {(Rr>0).mean():>5.0%} {Br.mean():>8.1f} "
                  f"{Rr.sum()/Br.sum():>+8.4f}")
        print()


if __name__ == "__main__":
    main()
