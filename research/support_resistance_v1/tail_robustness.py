"""Tail-robustness check on the no-target +0.355R pure-support result.

Frontier move #1 from HANDOFF.md: the no-target time-exit mean (+0.355R) may lean on a
few unicorn winners (max MFE was ~70R). The no-target metric realizes the close-at-horizon
return `final` (downside capped at -1 by the 1-ATR stop), so we stress the distribution of
that realized-R array:
  * mean (reproduce +0.355) vs median,
  * winsorized means (1% / 5% both tails) and trimmed mean (drop top 1%),
  * mean after deleting the single biggest / top-5 / top-1% winners,
  * share of the total R-sum contributed by the top 1% and top 10 trades,
  * bootstrap 95% CI on the mean,
all alongside the random-entry baseline so the EDGE (real - random) is re-checked under
each robust estimator, not just the raw mean. A real edge should survive de-tailing; an
artifact collapses toward (or below) random once the unicorns are removed.
"""
import sys, os
import numpy as np, duckdb

sys.path.insert(0, os.path.dirname(__file__))
from target_sweep import collect, START, ER_MAX                  # noqa: E402
from detector_v3 import range_score                              # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")


def no_target_R(trades):
    """Realized R under the no-target time exit: -1 if stopped, else close-at-horizon final."""
    return np.array([-1.0 if stopped else final for _, stopped, final in trades])


def winsorized_mean(x, p):
    lo, hi = np.percentile(x, [100 * p, 100 * (1 - p)])
    return np.clip(x, lo, hi).mean()


def trimmed_top_mean(x, p):
    """Mean after dropping the top fraction p of values (left tail kept — it's stop-capped)."""
    hi = np.percentile(x, 100 * (1 - p))
    return x[x <= hi].mean()


def boot_ci(x, reps=10000, seed=7):
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(reps, len(x)))
    means = x[idx].mean(axis=1)
    return np.percentile(means, [2.5, 97.5])


def describe(name, x):
    s = x.sum()
    order = np.sort(x)[::-1]
    top1pct_n = max(1, int(round(0.01 * len(x))))
    top1pct_sum = order[:top1pct_n].sum()
    top10_sum = order[:10].sum()
    print(f"\n=== {name}  (n={len(x)}) ===")
    print(f"  mean            {x.mean():+.4f}R")
    print(f"  median          {np.median(x):+.4f}R")
    print(f"  winsor 1%       {winsorized_mean(x, 0.01):+.4f}R")
    print(f"  winsor 5%       {winsorized_mean(x, 0.05):+.4f}R")
    print(f"  trim top 1%     {trimmed_top_mean(x, 0.01):+.4f}R   (drop {top1pct_n} biggest)")
    print(f"  drop top 1 only {x[x < x.max()].mean() if (x < x.max()).any() else float('nan'):+.4f}R")
    print(f"  drop top 5      {np.sort(x)[:-5].mean():+.4f}R")
    lo, hi = boot_ci(x)
    print(f"  bootstrap 95%CI [{lo:+.4f}, {hi:+.4f}]R   ({'EXCLUDES 0' if lo > 0 else 'includes 0'})")
    print(f"  win rate        {(x > 0).mean():.1%}")
    print(f"  top 1% ({top1pct_n} trades) = {top1pct_sum/s:.1%} of total R-sum;  "
          f"top 10 = {top10_sum/s:.1%}")
    print(f"  biggest winners (R): {', '.join(f'{v:+.1f}' for v in order[:10])}")


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
    print(f"universe: {len(universe)} names")
    real, rand = collect(universe, con)
    con.close()

    rt = no_target_R(real)
    rn = no_target_R(rand)
    describe("REAL pure-support (no-target time exit)", rt)
    describe("RANDOM entry (same exit)", rn)

    print("\n=== EDGE (real - random) under each estimator ===")
    print(f"  mean        {rt.mean()-rn.mean():+.4f}R")
    print(f"  median      {np.median(rt)-np.median(rn):+.4f}R")
    print(f"  winsor 1%   {winsorized_mean(rt,0.01)-winsorized_mean(rn,0.01):+.4f}R")
    print(f"  winsor 5%   {winsorized_mean(rt,0.05)-winsorized_mean(rn,0.05):+.4f}R")
    print(f"  trim top 1% {trimmed_top_mean(rt,0.01)-trimmed_top_mean(rn,0.01):+.4f}R")
    # also: MFE tail context (the 70R unicorn the handoff flagged)
    mfe = np.array([m for m, _, _ in real])
    print(f"\nMFE tail context: max {mfe.max():.1f}R, p99 {np.percentile(mfe,99):.1f}R, "
          f"p90 {np.percentile(mfe,90):.1f}R  (these are PEAKS, not realized by the no-target exit)")


if __name__ == "__main__":
    main()
