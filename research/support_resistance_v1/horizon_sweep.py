"""Horizon sweep + capital-efficiency view of the pure-support / 1-ATR-stop / no-target exit.

Frontier #3. Two questions:
  (1) Where does HOLDING stop helping? Extending H=20->40 lifted expectancy +0.347->+0.456R
      (trailing_sweep). Sweep H to find the plateau / fade.
  (2) Brand's capital point: losers stop out EARLY, winners take long. So per-trade R understates
      the strategy — capital on a loser is freed in a few bars and recycled into the next trade.
      The honest figure is R PER BAR-OF-CAPITAL-DEPLOYED = sum(R) / sum(bars_held), not mean R.

Same entry (pure-support approach), same 1-ATR initial risk (R unit), NO trailing, NO target:
exit at the 1-ATR stop (early, R=-1) or at the H-bar horizon (R=final close). For each trade we
record (R, bars_held, stopped) so we can split exit timing by outcome and compute R/bar.

Random-entry baseline uses matched per-symbol random indices so edge (both in mean-R and in R/bar)
is comparable. Expensive per-bar clustering done once; H grid swept cheaply over cached contexts.
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
H_GRID = [10, 20, 30, 40, 60, 80, 120]
H_MAX = max(H_GRID)


def run_trade(t, h, l, c, atr, n, H):
    """Return (R, bars_held, stopped). No trailing, no target; exit at stop or H-bar horizon."""
    entry = c[t]; a = atr[t]; risk = a; stop = entry - STOP_ATR * a
    end = min(t + H, n - 1)
    for k in range(t + 1, end + 1):
        if l[k] <= stop:
            return (stop - entry) / risk, k - t, True
    return (c[end] - entry) / risk, end - t, False


def collect_contexts(universe, con):
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


def gather(ctx, key, H):
    out = []
    for x in ctx:
        for t in x[key]:
            out.append(run_trade(t, x["h"], x["l"], x["c"], x["atr"], x["n"], H))
    R = np.array([o[0] for o in out])
    B = np.array([o[1] for o in out], float)
    S = np.array([o[2] for o in out])
    return R, B, S


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
    print(f"universe {len(universe)} names, {len(ctx)} with entries, n={n_real} trades "
          f"(H_MAX={H_MAX} → entries need {H_MAX} bars of room), R = 1-ATR initial risk\n")

    print("Per-trade expectancy and EXIT TIMING by horizon")
    print(f"{'H':>4} {'meanR':>7} {'rand':>7} {'edge':>7} {'win%':>5} {'stop%':>6} "
          f"{'loserBars(med/mn)':>17} {'winBars(med/mn)':>16} {'allBars(mn)':>11}")
    for H in H_GRID:
        R, B, S = gather(ctx, "entries", H)
        Rr, _, _ = gather(ctx, "rand", H)
        win = R > 0
        lb = B[S]; wb = B[win]
        print(f"{H:>4} {R.mean():>+7.3f} {Rr.mean():>+7.3f} {R.mean()-Rr.mean():>+7.3f} "
              f"{win.mean():>5.0%} {S.mean():>6.0%} "
              f"{np.median(lb):>7.1f}/{lb.mean():<8.1f} {np.median(wb):>6.1f}/{wb.mean():<8.1f} "
              f"{B.mean():>11.1f}")

    print("\nCAPITAL EFFICIENCY — R earned per bar of capital deployed (sum R / sum bars held)")
    print(f"{'H':>4} {'R/bar(real)':>12} {'R/bar(rand)':>12} {'edge/bar':>9} "
          f"{'loser≤5bars%':>13} {'capital tied in losers%':>23}")
    for H in H_GRID:
        R, B, S = gather(ctx, "entries", H)
        Rr, Br, _ = gather(ctx, "rand", H)
        rpb = R.sum() / B.sum()
        rpbr = Rr.sum() / Br.sum()
        early = (B[S] <= 5).mean() if S.any() else float("nan")
        cap_loser = B[S].sum() / B.sum()      # share of bar-capital consumed by losing trades
        print(f"{H:>4} {rpb:>+12.4f} {rpbr:>+12.4f} {rpb-rpbr:>+9.4f} "
              f"{early:>13.0%} {cap_loser:>23.0%}")


if __name__ == "__main__":
    main()
