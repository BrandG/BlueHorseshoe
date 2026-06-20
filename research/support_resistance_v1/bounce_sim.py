"""Honest long-only support-bounce simulation — answers Brand's worries with data.

NOT the rosy recovery study. Here we take the trade you'd actually take and let a
STOP work against us:

  For each CONFIRMED support level (>=2 reactions), after it's confirmed, every time
  price PULLS BACK into the zone from above (a retest -- we do NOT peek at whether it
  bounces), go LONG at that close with:
     stop   = level - STOP_ATR * ATR      (below the level)
     target = entry + TP_ATR  * ATR
     hold   = HOLD bars max
  Outcome walks forward bar-by-bar: stop first -> loss (-1R); target first -> +TP/STOP R;
  else timeout at the close. This counts the BREAKS, not just the bounces, so the
  "stopped before profit" rate is real.

Long-only (shorts unavailable). Random-line baseline = same retest logic on a level
placed at a random nearby price, so we see if real S/R beats an arbitrary line.
Reports win/stop/timeout %, mean R, time-to-win, and TRADE FREQUENCY per symbol-year.
"""
import sys, os
import numpy as np, duckdb

sys.path.insert(0, os.path.dirname(__file__))
from fusion import fuse_levels  # noqa: E402
from detector_v3 import range_score  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")
START = "2016-01-01"
ER_MAX = 0.11
HOLD = 25            # bars (~5 weeks) — recovery study said moves run 2-4 weeks
ZONE_ATR = 0.40     # half-width of the entry zone
APPROACH = 10       # bars of "price was above the zone" to call it a pullback
GAP = 10            # min bars between retests of the same level
SETTINGS = [(1.0, 2.0), (1.5, 2.0), (1.0, 3.0)]   # (STOP_ATR, TP_ATR)


def retests(level, hw, cb, h, l, c, atr, n):
    """Yield retest entry bars: price pulls back into [L-2hw, L+hw] from above,
    after the level is confirmed (cb). Deduped by GAP bars."""
    last = -10**9
    for t in range(cb + 1, n - 1):
        a = atr[t]
        if np.isnan(a) or a <= 0:
            continue
        if t - last < GAP:
            continue
        in_zone = (l[t] <= level + hw) and (l[t] >= level - 2 * hw)
        if not in_zone:
            continue
        lo = max(cb, t - APPROACH)
        from_above = c[lo:t].max() > level + hw if t > lo else False
        if in_zone and from_above:
            last = t
            yield t


def simulate(entry_bar, level, h, l, c, atr, n, stop_atr, tp_atr):
    a = atr[entry_bar]
    entry = c[entry_bar]
    stop = level - stop_atr * a
    risk = entry - stop
    if risk <= 0:
        return None
    tp = entry + tp_atr * a
    end = min(entry_bar + HOLD, n - 1)
    for k in range(entry_bar + 1, end + 1):
        if l[k] <= stop:
            return (-1.0, k - entry_bar, "stop")
        if h[k] >= tp:
            return ((tp - entry) / risk, k - entry_bar, "win")
    return ((c[end] - entry) / risk, end - entry_bar, "timeout")


def run(universe, con, randomize=False, seed=7):
    acc = {s: {"R": [], "bars_win": [], "n": 0, "win": 0, "stop": 0, "to": 0}
           for s in SETTINGS}
    symyears = 0.0
    for si, sym in enumerate(universe):
        d = con.execute("SELECT high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? "
                        "ORDER BY date", [sym, START]).df()
        h, l, c, v = (d[x].to_numpy(float) for x in ("high", "low", "close", "volume"))
        n = len(c)
        symyears += n / 252.0
        levels, atr, _, _ = fuse_levels(h, l, c, v)
        rng = np.random.default_rng(seed + si)
        for lv in levels:
            cbs = sorted(e[0] for e in lv["reactions"])
            cb = cbs[1]                        # confirmed at the 2nd reaction
            L = lv["price"]
            if randomize:                      # baseline: arbitrary nearby line
                a0 = atr[cb] if not np.isnan(atr[cb]) else np.nanmedian(atr)
                L = c[cb] + float(rng.uniform(-2.0, 2.0)) * a0
            hw = ZONE_ATR * (atr[cb] if not np.isnan(atr[cb]) else np.nanmedian(atr))
            for t in retests(L, hw, cb, h, l, c, atr, n):
                for st in SETTINGS:
                    out = simulate(t, L, h, l, c, atr, n, *st)
                    if out is None:
                        continue
                    R, bars, kind = out
                    a = acc[st]
                    a["R"].append(R); a["n"] += 1
                    a[{"win": "win", "stop": "stop", "timeout": "to"}[kind]] += 1
                    if kind == "win":
                        a["bars_win"].append(bars)
    return acc, symyears


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
    print(f"range-bound universe: {len(universe)} symbols\n", flush=True)

    real, symyears = run(universe, con, randomize=False)
    base, _ = run(universe, con, randomize=True)
    con.close()

    print(f"{'setting':>14} {'n':>6} {'trades/sym-yr':>13} {'win%':>6} {'stop%':>6} "
          f"{'timeout%':>8} {'meanR':>7} {'medWinBars':>11}   (baseline meanR / win%)")
    for st in SETTINGS:
        a = real[st]; b = base[st]
        n = a["n"] or 1; bn = b["n"] or 1
        freq = a["n"] / symyears
        mwb = np.median(a["bars_win"]) if a["bars_win"] else float("nan")
        print(f"  stop{st[0]:.1f}/tp{st[1]:.1f} {a['n']:>6} {freq:>13.2f} "
              f"{a['win']/n:>6.0%} {a['stop']/n:>6.0%} {a['to']/n:>8.0%} "
              f"{np.mean(a['R']):>+7.3f} {mwb:>11.0f}   "
              f"(base {np.mean(b['R']):+.3f} / {b['win']/bn:.0%})")
    print("\ndone.")


if __name__ == "__main__":
    main()
