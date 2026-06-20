"""Universe bracket tally — the real test of 'buy at pure-support, 1.5:1 bracket'.

For every PIT pure-support approach across the range-bound universe, score a 1.5:1 bracket
(target = 1.5x stop distance) at several stop widths (Brand's 1% plus wider + ATR-based,
since he's fine going wider). Outcome: won (+1.5R), stopped (-1R), open (forward return in
R at horizon). Report win/stop/open % and EXPECTANCY (mean R) -- a 1.5:1 needs >40% wins to
profit. A RANDOM-entry baseline (same brackets, random bars) says whether entering AT support
beats entering anywhere. Stop-aware, so a dip that takes out the stop is a real loss even if
price later recovers (Brand's criterion).
"""
import sys, os
import numpy as np, duckdb

sys.path.insert(0, os.path.dirname(__file__))
from reversal_profile import build_pivots, cluster_pivots       # noqa: E402
from detector import wilder_atr                                  # noqa: E402
from detector_v3 import range_score                             # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")
START = "2016-01-01"
ER_MAX = 0.11
WARMUP = 80; NEAR = 0.5; APPROACH = 10; GAP = 15; H = 20; TARGET_MULT = 1.5
STOPS = [("1%", "pct", 0.01), ("2%", "pct", 0.02), ("3%", "pct", 0.03),
         ("1.0ATR", "atr", 1.0), ("1.5ATR", "atr", 1.5)]


def stop_price(entry, a, kind, val):
    return entry * (1 - val) if kind == "pct" else entry - val * a


def score(t, entry, stop_px, h, l, c, n):
    """+1.5R won / -1R stopped / forward-return-in-R open."""
    tgt = entry + TARGET_MULT * (entry - stop_px)
    end = min(t + H, n - 1)
    for k in range(t + 1, end + 1):
        if l[k] <= stop_px:
            return -1.0, "stopped"
        if h[k] >= tgt:
            return TARGET_MULT, "won"
    return (c[end] - entry) / (entry - stop_px), "open"


def tally_add(acc, R, kind):
    acc["n"] += 1; acc["R"] += R; acc[kind] += 1


def run(universe, con):
    real = {s[0]: {"n": 0, "R": 0.0, "won": 0, "stopped": 0, "open": 0} for s in STOPS}
    rand = {s[0]: {"n": 0, "R": 0.0, "won": 0, "stopped": 0, "open": 0} for s in STOPS}
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
        entries = []
        last = -10**9
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
            last = t
            entries.append(t)
        for t in entries:                                  # real: at support
            for name, kind, val in STOPS:
                sp = stop_price(c[t], atr[t], kind, val)
                if sp >= c[t]:
                    continue
                R, oc = score(t, c[t], sp, h, l, c, n)
                tally_add(real[name], R, oc)
        if entries:                                        # baseline: same count, random bars
            rb = rng.integers(WARMUP, n - H, size=len(entries))
            for t in rb:
                for name, kind, val in STOPS:
                    sp = stop_price(c[t], atr[t], kind, val)
                    if sp >= c[t]:
                        continue
                    R, oc = score(int(t), c[t], sp, h, l, c, n)
                    tally_add(rand[name], R, oc)
    return real, rand


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

    real, rand = run(universe, con)
    con.close()

    print(f"\n1.5:1 bracket at pure-support (target = 1.5x stop). 'edge' = real - random expectancy.\n")
    print(f"{'stop':>8} {'n':>7} {'won%':>6} {'stop%':>6} {'open%':>6} {'exp(R)':>8} "
          f"{'randExp':>8} {'edge(R)':>8}")
    for name, _, _ in STOPS:
        a = real[name]; b = rand[name]
        if a["n"] == 0:
            continue
        ax = a["R"] / a["n"]; bx = b["R"] / b["n"] if b["n"] else float("nan")
        print(f"{name:>8} {a['n']:>7} {a['won']/a['n']:>6.0%} {a['stopped']/a['n']:>6.0%} "
              f"{a['open']/a['n']:>6.0%} {ax:>+8.3f} {bx:>+8.3f} {ax-bx:>+8.3f}")
    print("\n(win% needed for 1.5:1 breakeven ≈ 40%.)")


if __name__ == "__main__":
    main()
