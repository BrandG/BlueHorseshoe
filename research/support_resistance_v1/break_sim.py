"""Door #2 — follow the break, don't fade it (long-only momentum on S/R).

bounce_sim/door#1 FADED the level (buy the dip into support) and price broke through
60-72% of the time. Brand: the edge may be in trading the BREAK, not the bounce, and
his own count was 5 long / 2 short breakouts. Long-only, that's UPSIDE breaks of a
resistance level (resistance-turned-support). Two entry styles:

  * BREAKOUT  -- price was below the level, then closes decisively above it
                 (close >= level + BREAK_ATR*ATR). Enter that close (chase momentum).
                 Stop = entry - STOP_ATR*ATR (fixed ATR stop; the level is the signal).
  * RETEST    -- after a fresh upside break, wait for a pullback whose low re-touches
                 the level zone, enter there (former resistance now support).
                 Stop = level - STOP_ATR*ATR (below reclaimed support).

Point-in-time: every trigger is knowable at the bar we act on; no peeking forward.
Counts the failures (a break that rolls back over and stops out). Baselines: same
break logic on a 'nearby' random line and on an 'anti-structure' line (>=ANTI_SEP_ATR
from every real level) -- so we learn whether breaking a REAL resistance beats breaking
an arbitrary line (i.e. is it S/R, or just generic upward momentum?).
"""
import sys, os
import numpy as np, duckdb

sys.path.insert(0, os.path.dirname(__file__))
from fusion import fuse_levels          # noqa: E402
from detector_v3 import range_score     # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")
START = "2016-01-01"
ER_MAX = 0.11           # range-bound ceiling (default regime)
ER_MIN_TREND = 0.25     # trending floor (door #2's proper home: breaks continue in trends)
HOLD = 25
ZONE_ATR = 0.40          # retest zone half-width (hw)
APPROACH = 10            # bars price must have spent below the level before the break
GAP = 10                 # min bars between breaks of the same level
BREAK_ATR = 0.50         # close must clear the level by this many ATR to count as a break
RETEST_WIN = 20          # bars after a break to wait for the pullback retest
ANTI_SEP_ATR = 1.5       # anti-structure line this far from every real level
SETTINGS = [(1.0, 2.0), (1.5, 2.0), (1.0, 3.0)]   # (STOP_ATR, TP_ATR)


def break_bars(level, cb, c, atr, n):
    """Yield fresh upside-break bars: prior close at/below the level, this close
    decisively above it, after the level spent APPROACH bars below. Deduped by GAP."""
    last = -10**9
    for t in range(max(cb + 1, APPROACH + 1), n - 1):
        a = atr[t]
        if np.isnan(a) or a <= 0:
            continue
        if t - last < GAP:
            continue
        if c[t - 1] > level:                                 # not a fresh cross
            continue
        if c[t] < level + BREAK_ATR * a:                     # not a decisive break
            continue
        lo = max(cb, t - APPROACH)
        if c[lo:t].min() >= level:                           # wasn't really below before
            continue
        last = t
        yield t


def breakout_entries(level, hw, cb, h, l, c, atr, n):
    """Momentum: enter at the breakout close. shelf_low slot carries None (entry-stop)."""
    for t in break_bars(level, cb, c, atr, n):
        yield t, None


def retest_entries(level, hw, cb, h, l, c, atr, n):
    """After a fresh break, enter on the first pullback whose low re-touches the level
    zone within RETEST_WIN bars. shelf_low slot carries the level (level-anchored stop)."""
    last = -10**9
    for tb in break_bars(level, cb, c, atr, n):
        end = min(tb + RETEST_WIN, n - 1)
        for t in range(tb + 1, end + 1):
            if t - last < GAP:
                continue
            a = atr[t]
            if np.isnan(a) or a <= 0:
                continue
            if (l[t] <= level + hw) and (l[t] >= level - hw):   # pulled back to reclaimed support
                last = t
                yield t, level
                break


def simulate(entry_bar, entry, stop, tp, h, l, c, n):
    risk = entry - stop
    if risk <= 0:
        return None
    end = min(entry_bar + HOLD, n - 1)
    for k in range(entry_bar + 1, end + 1):
        if l[k] <= stop:
            return (-1.0, k - entry_bar, "stop")
        if h[k] >= tp:
            return ((tp - entry) / risk, k - entry_bar, "win")
    return ((c[end] - entry) / risk, end - entry_bar, "timeout")


def _blank():
    return {s: {"R": [], "bars_win": [], "n": 0, "win": 0, "stop": 0, "to": 0} for s in SETTINGS}


def run(universe, con, entries_fn, baseline=None, seed=7):
    """baseline: None real level; 'nearby' close+/-U(-2,2)*ATR; 'antistructure' far from
    all levels. Stop anchor: if entries_fn passes a level (retest) -> stop=level-STOP*ATR;
    if it passes None (breakout) -> stop=entry-STOP*ATR."""
    acc = _blank()
    symyears = 0.0
    for si, sym in enumerate(universe):
        d = con.execute("SELECT high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? "
                        "ORDER BY date", [sym, START]).df()
        h, l, c, v = (d[x].to_numpy(float) for x in ("high", "low", "close", "volume"))
        n = len(c)
        symyears += n / 252.0
        levels, atr, _, _ = fuse_levels(h, l, c, v)
        real_prices = [lv["price"] for lv in levels]
        pmin, pmax = float(np.nanmin(c)), float(np.nanmax(c))
        rng = np.random.default_rng(seed + si)
        for lv in levels:
            cbs = sorted(e[0] for e in lv["reactions"])
            cb = cbs[1]
            a0 = atr[cb] if not np.isnan(atr[cb]) else np.nanmedian(atr)
            L = lv["price"]
            if baseline == "nearby":
                L = c[cb] + float(rng.uniform(-2.0, 2.0)) * a0
            elif baseline == "antistructure":
                L = None
                for _ in range(60):
                    cand = c[cb] + float(rng.uniform(-3.0, 3.0)) * a0
                    if cand < pmin or cand > pmax:
                        continue
                    if all(abs(cand - rp) >= ANTI_SEP_ATR * a0 for rp in real_prices):
                        L = cand; break
                if L is None:
                    continue
            hw = ZONE_ATR * a0
            for t, anchor in entries_fn(L, hw, cb, h, l, c, atr, n):
                a = atr[t]
                if np.isnan(a) or a <= 0:
                    continue
                entry = c[t]
                for stop_atr, tp_atr in SETTINGS:
                    base = anchor if anchor is not None else entry      # retest=level, breakout=entry
                    stop = base - stop_atr * a
                    tp = entry + tp_atr * a
                    out = simulate(t, entry, stop, tp, h, l, c, n)
                    if out is None:
                        continue
                    R, bars, kind = out
                    A = acc[(stop_atr, tp_atr)]
                    A["R"].append(R); A["n"] += 1
                    A[{"win": "win", "stop": "stop", "timeout": "to"}[kind]] += 1
                    if kind == "win":
                        A["bars_win"].append(bars)
    return acc, symyears


def _row(tag, a, symyears):
    n = a["n"] or 1
    freq = a["n"] / symyears if symyears else float("nan")
    mwb = np.median(a["bars_win"]) if a["bars_win"] else float("nan")
    meanR = np.mean(a["R"]) if a["R"] else float("nan")
    return (f"  {tag:<26} {a['n']:>6} {freq:>9.2f} {a['win']/n:>6.0%} {a['stop']/n:>6.0%} "
            f"{a['to']/n:>8.0%} {meanR:>+8.3f} {mwb:>9.0f}")


def main():
    regime = sys.argv[1] if len(sys.argv) > 1 else "range"   # "range" (symbols.txt, ER<=0.11) | "trend" (symbols_trend.txt)
    con = duckdb.connect(DB, read_only=True)
    src = "symbols_trend.txt" if regime == "trend" else "symbols.txt"
    cand = [s.strip() for s in open(os.path.join(HERE, src)) if s.strip()]
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
        if np.isnan(rs):
            continue
        # range regime gates ER here; trend regime is pre-selected in symbols_trend.txt
        if regime == "range" and rs > ER_MAX:
            continue
        universe.append(s)
    print(f"{regime} universe: {len(universe)} symbols (source {src})\n", flush=True)

    bo_real, symyears = run(universe, con, breakout_entries, baseline=None)
    bo_near, _ = run(universe, con, breakout_entries, baseline="nearby")
    bo_anti, _ = run(universe, con, breakout_entries, baseline="antistructure")
    rt_real, _ = run(universe, con, retest_entries, baseline=None)
    rt_near, _ = run(universe, con, retest_entries, baseline="nearby")
    rt_anti, _ = run(universe, con, retest_entries, baseline="antistructure")
    con.close()

    hdr = (f"  {'variant':<26} {'n':>6} {'trd/syr':>9} {'win%':>6} {'stop%':>6} "
           f"{'tmout%':>8} {'meanR':>8} {'medWbar':>9}")
    for st in SETTINGS:
        print(f"\n=== stop {st[0]:.1f} ATR / target {st[1]:.1f} ATR ===")
        print(hdr)
        print("  -- BREAKOUT entry (momentum; stop = entry - STOP*ATR) --")
        print(_row("breakout REAL", bo_real[st], symyears))
        print(_row("breakout RAND nearby", bo_near[st], symyears))
        print(_row("breakout RAND anti-str", bo_anti[st], symyears))
        print("  -- RETEST entry (reclaimed support; stop = level - STOP*ATR) --")
        print(_row("retest REAL", rt_real[st], symyears))
        print(_row("retest RAND nearby", rt_near[st], symyears))
        print(_row("retest RAND anti-str", rt_anti[st], symyears))
    print("\ndone.")


if __name__ == "__main__":
    main()
