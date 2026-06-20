"""Survivorship / gap-through-stop probe for the pure-support bracket (Brand's challenge).

The DB is survivor-only (only ~3 real crashed delistings with history), so we can't run a clean
dead-names test. Two adapted views of the SAME question — 'does the 1-ATR stop actually cap the
one brutal touch, or do dying/gapping names blow through it?':

PART A — GAP-AWARE fill on the survivor universe (n~1046 support trades + matched random).
  Each stopped trade is realized two ways:
    R_ideal : exit exactly at the stop price (what every prior script assumed).
    R_gap   : if the bar OPENS below the stop you fill at the OPEN (gap), else at the stop.
  If R_gap ~= R_ideal, the stop holds and our expectancy isn't inflated by ignoring gaps.
  Reports the slippage, the share of stops that gapped through, and the worst gap fills.

PART B — CASE STUDY the handful of real decliners (ACER->2% of peak, AENZ->3%, ADMS->19%, ...).
  Run support entries over each doomed name's whole life with the gap-aware stop and PRINT EVERY
  TRADE. Tests Brand's thesis directly: a name marches to ~zero, but do our stop-capped per-trade
  results still net positive? No ER gate here (decliners trend) — we want to see what happens when
  a name we might have traded dies.
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
H = 25
DECLINERS = ["ACER", "AENZ", "ADMS", "AHP", "ADRE"]


def load(con, sym):
    d = con.execute("SELECT date,open,high,low,close FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",
                    [sym, START]).df()
    return (d["date"].to_numpy("datetime64[D]"),
            *(d[x].to_numpy(float) for x in ("open", "high", "low", "close")))


def trade_both(t, o, h, l, c, atr, n):
    """Return (R_ideal, R_gap, stopped, gapped). R unit = 1-ATR initial risk."""
    entry = c[t]; a = atr[t]; risk = a; stop = entry - STOP_ATR * a
    end = min(t + H, n - 1)
    for k in range(t + 1, end + 1):
        if l[k] <= stop:
            r_ideal = (stop - entry) / risk
            gapped = o[k] <= stop
            fill = o[k] if gapped else stop          # realistic fill on a gap-down open
            return r_ideal, (fill - entry) / risk, True, gapped
    r = (c[end] - entry) / risk
    return r, r, False, False


def support_entries(o, h, l, c, atr, n):
    pivots = build_pivots(h, l, 3)
    last = -10**9; out = []
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
        last = t; out.append(t)
    return out


def atr_of(h, l, c):
    a = wilder_atr(h, l, c, 14)
    return np.where(np.isnan(a) | (a <= 0), np.nanmedian(a), a)


def part_a(con):
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
    ideal, gap, stopped, gapped = [], [], [], []
    rideal, rgap = [], []
    for si, sym in enumerate(universe):
        _, o, h, l, c = load(con, sym); n = len(c)
        if n < WARMUP + H + 5:
            continue
        atr = atr_of(h, l, c)
        ent = support_entries(o, h, l, c, atr, n)
        for t in ent:
            ri, rg, st, gp = trade_both(t, o, h, l, c, atr, n)
            ideal.append(ri); gap.append(rg); stopped.append(st); gapped.append(gp)
        rng = np.random.default_rng(11 + si)
        for t in rng.integers(WARMUP, n - H, size=len(ent)):
            ri, rg, st, gp = trade_both(int(t), o, h, l, c, atr, n)
            rideal.append(ri); rgap.append(rg)
    ideal = np.array(ideal); gap = np.array(gap)
    stopped = np.array(stopped); gapped = np.array(gapped)
    rideal = np.array(rideal); rgap = np.array(rgap)
    nstop = stopped.sum()
    print(f"PART A — gap-aware fill on survivor universe ({len(universe)} names, H={H})")
    print(f"  pure-support  n={len(ideal)}:  mean R_ideal {ideal.mean():+.3f}  "
          f"R_gap {gap.mean():+.3f}  (gap slippage {gap.mean()-ideal.mean():+.3f}R)")
    print(f"     stopped trades: {nstop} ({nstop/len(ideal):.0%});  of those, "
          f"GAPPED through the stop: {gapped.sum()} ({(gapped.sum()/nstop if nstop else 0):.0%})")
    if gapped.any():
        worst = np.sort(gap[gapped])[:6]
        print(f"     worst gap fills (R): {', '.join(f'{v:+.2f}' for v in worst)}")
    print(f"  random         n={len(rideal)}:  mean R_ideal {rideal.mean():+.3f}  "
          f"R_gap {rgap.mean():+.3f}  (slippage {rgap.mean()-rideal.mean():+.3f}R)")
    print(f"  -> if R_gap ~= R_ideal, the stop holds and expectancy isn't gap-inflated.\n")


def part_b(con):
    print(f"PART B — case study: support trades on names that DIED (gap-aware, no ER gate, H={H})")
    for sym in DECLINERS:
        dates, o, h, l, c = load(con, sym); n = len(c)
        if n < WARMUP + H + 5:
            print(f"  {sym}: too few bars ({n})"); continue
        atr = atr_of(h, l, c)
        ent = support_entries(o, h, l, c, atr, n)
        rows = [(dates[t], *trade_both(t, o, h, l, c, atr, n)) for t in ent]
        if not rows:
            print(f"  {sym}: no support entries"); continue
        rg = np.array([r[2] for r in rows])               # R_gap
        peak, lastpx = c.max(), c[-1]
        print(f"  {sym}: peak {peak:.1f} -> last {lastpx:.2f} ({100*lastpx/peak:.0f}% of peak), "
              f"{len(rows)} trades  | sum {rg.sum():+.2f}R  mean {rg.mean():+.3f}R  "
              f"win {(rg>0).mean():.0%}  {'NET +' if rg.sum()>0 else 'NET -'}")
        for dt, ri, rgp, st, gp in rows:
            tag = "GAP-THRU" if gp else ("stop" if st else "horizon")
            print(f"        {str(dt)}  R={rgp:+.2f}  ({tag})")
    print()


def main():
    con = duckdb.connect(DB, read_only=True)
    part_a(con)
    part_b(con)
    con.close()


if __name__ == "__main__":
    main()
