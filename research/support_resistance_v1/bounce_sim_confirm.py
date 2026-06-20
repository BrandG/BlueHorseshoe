"""Door #1 — wait-for-confirmation bounce sim (the "let the knife flatten" test).

bounce_sim.py entered on FIRST contact with a confirmed support zone -> 47-66%
stop-outs (Brand's exact worry: catching the knife). Brand's favorite setups were
"falling knife *flattens out* THEN spikes." This script tests that confirmation:

  Enter only after a FLAT SHELF forms *inside* the confirmed support zone -- the same
  close-range flatness test detect_events uses (window of SHELF_BARS whose CLOSE range
  <= FLAT_BAND * ATR), but WITHOUT requiring the departure (waiting for the departure
  would be door #2, "follow the break"). Point-in-time: we enter at the close of the
  shelf-end bar, which is the first bar the flatness is knowable. We do NOT peek at
  whether/which way price departs.

Still long-only, still STOP-aware, still counts the breaks (a shelf can fail down
through the stop just as a first-touch can). Three comparisons per setting:

  * REAL  first-touch   -- reproduces bounce_sim.py exactly (same retests, same geometry)
  * REAL  shelf-confirm -- door #1 at the real level
  * RAND  shelf-confirm -- door #1 at a random nearby line (same shelf logic)

If shelf-confirm cuts the stop-out rate and beats the random line where first-touch
didn't, that's the opening. Two stop placements reported: LEVEL-anchored (clean
one-variable A/B vs the published numbers) and SHELF-floor (the thesis-true "stop
below the shelf").
"""
import sys, os
import numpy as np, duckdb

sys.path.insert(0, os.path.dirname(__file__))
from fusion import fuse_levels          # noqa: E402
from detector_v3 import range_score, SRParamsV3  # noqa: E402
from bounce_sim import retests          # noqa: E402  (identical first-touch entry logic)

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")
START = "2016-01-01"
ER_MAX = 0.11
HOLD = 25            # bars (~5 weeks) — recovery study said moves run 2-4 weeks
ZONE_ATR = 0.40     # half-width of the entry zone (hw), shared with first-touch
APPROACH = 10       # bars of "price was above the zone" to call it a pullback
GAP = 10            # min bars between entries off the same level
SETTINGS = [(1.0, 2.0), (1.5, 2.0), (1.0, 3.0)]   # (STOP_ATR, TP_ATR)

# shelf (consolidation) detection — mirrors SRParamsV3 defaults
_VP = SRParamsV3()
SHELF_BARS = _VP.shelf_bars          # 5
FLAT_BAND = _VP.flat_band            # 0.8  (CLOSE range <= FLAT_BAND*ATR -> flat)
SHELF_ZONE_ATR = 0.50               # shelf mean must sit within this many ATR of the level
ANTI_SEP_ATR = 1.5                  # 'anti-structure' baseline line must be this far from EVERY real level


def shelf_entries(level, hw, cb, h, l, c, atr, n):
    """Yield (entry_bar, shelf_low) where a flat shelf forms AT the level after it's
    confirmed: a SHELF_BARS window whose close-range <= FLAT_BAND*ATR, whose mean sits
    within SHELF_ZONE_ATR of the level, and that was approached from above (a pullback
    that flattened). Entry = shelf-end bar close (point-in-time). Deduped by GAP."""
    last = -10**9
    sb = SHELF_BARS
    for t in range(max(cb + 1, sb), n - 1):
        a = atr[t]
        if np.isnan(a) or a <= 0:
            continue
        if t - last < GAP:
            continue
        w0 = t - sb + 1
        win_c = c[w0:t + 1]
        if win_c.max() - win_c.min() > FLAT_BAND * a:        # not flat -> no shelf
            continue
        shelf_mean = float(win_c.mean())
        if abs(shelf_mean - level) > SHELF_ZONE_ATR * a:     # shelf not at the level
            continue
        lo = max(cb, w0 - APPROACH)
        from_above = c[lo:w0].max() > level + hw if w0 > lo else False
        if not from_above:                                   # require a pullback into it
            continue
        last = t
        yield t, float(l[w0:t + 1].min())


def first_touch_entries(level, hw, cb, h, l, c, atr, n):
    """Adapter: bounce_sim's first-touch retests, shelf_low=None (level-anchored stop)."""
    for t in retests(level, hw, cb, h, l, c, atr, n):
        yield t, None


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


def run(universe, con, entries_fn, baseline=None, stop_mode="level", seed=7):
    """baseline: None -> real level; 'nearby' -> arbitrary line close +/- U(-2,2)*ATR
    (lands inside the range, often near structure); 'antistructure' -> a line >= ANTI_SEP_ATR
    from EVERY detected level (a genuinely null line). stop_mode: 'level' -> stop =
    level - STOP_ATR*ATR (clean A/B); 'shelf' -> stop = shelf_low - STOP_ATR*ATR."""
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
            cb = cbs[1]                        # confirmed at the 2nd reaction
            a0 = atr[cb] if not np.isnan(atr[cb]) else np.nanmedian(atr)
            L = lv["price"]
            if baseline == "nearby":           # arbitrary nearby line (often near structure)
                L = c[cb] + float(rng.uniform(-2.0, 2.0)) * a0
            elif baseline == "antistructure":  # line far from EVERY real level -> genuinely null
                L = None
                for _ in range(60):
                    cand = c[cb] + float(rng.uniform(-3.0, 3.0)) * a0
                    if cand < pmin or cand > pmax:
                        continue
                    if all(abs(cand - rp) >= ANTI_SEP_ATR * a0 for rp in real_prices):
                        L = cand; break
                if L is None:                  # range too dense with structure -> skip
                    continue
            hw = ZONE_ATR * a0
            for t, shelf_low in entries_fn(L, hw, cb, h, l, c, atr, n):
                a = atr[t]
                if np.isnan(a) or a <= 0:
                    continue
                entry = c[t]
                for stop_atr, tp_atr in SETTINGS:
                    if stop_mode == "shelf" and shelf_low is not None:
                        stop = shelf_low - stop_atr * a
                    else:
                        stop = L - stop_atr * a
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
    return (f"  {tag:<22} {a['n']:>6} {freq:>9.2f} {a['win']/n:>6.0%} {a['stop']/n:>6.0%} "
            f"{a['to']/n:>8.0%} {meanR:>+8.3f} {mwb:>9.0f}")


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

    ft, symyears = run(universe, con, first_touch_entries, baseline=None, stop_mode="level")
    sh_real, _ = run(universe, con, shelf_entries, baseline=None, stop_mode="level")
    sh_near, _ = run(universe, con, shelf_entries, baseline="nearby", stop_mode="level")
    sh_anti, _ = run(universe, con, shelf_entries, baseline="antistructure", stop_mode="level")
    sh_real_sf, _ = run(universe, con, shelf_entries, baseline=None, stop_mode="shelf")
    sh_near_sf, _ = run(universe, con, shelf_entries, baseline="nearby", stop_mode="shelf")
    sh_anti_sf, _ = run(universe, con, shelf_entries, baseline="antistructure", stop_mode="shelf")
    con.close()

    hdr = (f"  {'variant':<24} {'n':>6} {'trd/syr':>9} {'win%':>6} {'stop%':>6} "
           f"{'tmout%':>8} {'meanR':>8} {'medWbar':>9}")
    for st in SETTINGS:
        print(f"\n=== stop {st[0]:.1f} ATR / target {st[1]:.1f} ATR ===")
        print(hdr)
        print("  -- stop anchored at LEVEL (clean A/B vs published first-touch) --")
        print(_row("first-touch  REAL", ft[st], symyears))
        print(_row("shelf-confirm REAL", sh_real[st], symyears))
        print(_row("shelf-confirm RAND nearby", sh_near[st], symyears))
        print(_row("shelf-confirm RAND anti-str", sh_anti[st], symyears))
        print("  -- stop anchored at SHELF floor (thesis-true 'stop below the shelf') --")
        print(_row("shelf-confirm REAL", sh_real_sf[st], symyears))
        print(_row("shelf-confirm RAND nearby", sh_near_sf[st], symyears))
        print(_row("shelf-confirm RAND anti-str", sh_anti_sf[st], symyears))
    print("\ndone.")


if __name__ == "__main__":
    main()
