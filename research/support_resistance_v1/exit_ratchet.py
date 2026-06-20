"""Brand's exit idea: ratchet the stop up to (close - 1 ATR) at the end of every UP day, ratchet-only.

Different from the earlier ATR-chandelier (exit_ratchet vs trailing_sweep):
  * trails off the CLOSE, not the running high  -> calmer, doesn't chase intraday spikes
  * advances ONLY on up-close days              -> a pullback never moves it, never re-widens
  * 1-ATR distance                              -> locks a floor ~1 ATR under recent up-closes
Goal: capture part of the +0.39R(fixed) -> +0.9R(oracle) giveback the fixed time-exit leaves on the
table, AND (Brand's capital point) exit winners when they roll over -> free capital sooner -> better
R-per-bar. A ratcheting stop should also make LONGER horizons safe, so we sweep H.

Head-to-head vs the fixed-stop no-target incumbent, gap-aware fills (if a bar opens below the stop you
fill at the open), matched random baseline. Reports mean R, median, win%, mean bars held, R/bar
(capital efficiency), and edge over random. Two ATR conventions for the trail: entry-ATR (clean R
unit) and current-ATR. Expensive clustering done once; rules/H swept cheaply.
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
H_GRID = [25, 40, 60, 120]
H_MAX = max(H_GRID)


def simulate(t, o, h, l, c, atr, n, H, rule):
    """Return (R_gapaware, bars_held). rule in {'fixed','upday','upday_curatr'}.
    Stop in force during bar k is set from data through k-1 (no lookahead)."""
    entry = c[t]; a = atr[t]; risk = a
    stop = entry - a
    end = min(t + H, n - 1)
    for k in range(t + 1, end + 1):
        if l[k] <= stop:                                  # exit; gap-aware fill
            fill = o[k] if o[k] <= stop else stop
            return (fill - entry) / risk, k - t
        if rule == "upday" and c[k] > c[k - 1]:
            stop = max(stop, c[k] - a)                     # trail at close - 1*entryATR, up days only
        elif rule == "upday_curatr" and c[k] > c[k - 1]:
            stop = max(stop, c[k] - atr[k])                # ... using current ATR
    return (c[end] - entry) / risk, end - t


def collect(universe, con):
    ctx = []
    for si, sym in enumerate(universe):
        d = con.execute("SELECT open,high,low,close FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",
                        [sym, START]).df()
        o, h, l, c = (d[x].to_numpy(float) for x in ("open", "high", "low", "close"))
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
        ctx.append(dict(o=o, h=h, l=l, c=c, atr=atr, n=n, entries=entries, rand=rand))
    return ctx


def run(ctx, key, H, rule):
    R, B = [], []
    for x in ctx:
        for t in x[key]:
            r, b = simulate(t, x["o"], x["h"], x["l"], x["c"], x["atr"], x["n"], H, rule)
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

    rules = [("fixed (incumbent)", "fixed"),
             ("UP-DAY ratchet (Brand, entryATR)", "upday"),
             ("UP-DAY ratchet (curATR)", "upday_curatr")]
    for H in H_GRID:
        print(f"================ H={H} bars ================")
        print(f"  {'exit rule':34} {'meanR':>7} {'edge':>7} {'medR':>6} {'win%':>5} "
              f"{'meanBars':>8} {'R/bar':>8}")
        # oracle reference (peak, gap-irrelevant) once per H
        for label, rule in rules:
            Rr, Br = run(ctx, "entries", H, rule)
            Rn, _ = run(ctx, "rand", H, rule)
            print(f"  {label:34} {Rr.mean():>+7.3f} {Rr.mean()-Rn.mean():>+7.3f} "
                  f"{np.median(Rr):>+6.2f} {(Rr>0).mean():>5.0%} {Br.mean():>8.1f} "
                  f"{Rr.sum()/Br.sum():>+8.4f}")
        print()


if __name__ == "__main__":
    main()
