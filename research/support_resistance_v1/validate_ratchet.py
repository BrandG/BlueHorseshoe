"""Is the 2-ATR up-day ratchet's capital-efficiency edge ROBUST, or did I overfit M=2 to one sample?

M=2 topped the in-sample sweep, so validate fixed vs close-2ATR head-to-head across the SAME splits
we trusted for the main result: interleaved calendar-quarter halves (A even-Q / B odd-Q, COVID in
both) + recent 24-month holdout. Report mean R AND R/bar (sum R / sum bars) for both rules in each
split. The ratchet's R/bar edge is trustworthy only if it beats fixed in A AND B AND holdout; if it
flips anywhere, the +9% was noise/overfit. Gap-aware fills, H=25.
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
H = 25
HOLDOUT_START = np.datetime64("2024-06-19")


def simulate(t, o, h, l, c, atr, n, M):
    """M=None -> fixed 1-ATR stop. Else up-day ratchet to close - M*entryATR. Gap-aware. (R, bars)."""
    entry = c[t]; a = atr[t]; risk = a; stop = entry - a
    end = min(t + H, n - 1)
    for k in range(t + 1, end + 1):
        if l[k] <= stop:
            fill = o[k] if o[k] <= stop else stop
            return (fill - entry) / risk, k - t
        if M is not None and c[k] > c[k - 1]:
            stop = max(stop, c[k] - M * a)
    return (c[end] - entry) / risk, end - t


def quarter_parity(dt):
    m = dt.astype("datetime64[M]").astype(int)
    return ((1970 + m // 12) * 4 + (m % 12) // 3) % 2


def collect(universe, con):
    rows = []   # (date, R_fixed, B_fixed, R_ratchet, B_ratchet)
    for sym in universe:
        d = con.execute("SELECT date,open,high,low,close FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",
                        [sym, START]).df()
        dates = d["date"].to_numpy("datetime64[D]")
        o, h, l, c = (d[x].to_numpy(float) for x in ("open", "high", "low", "close"))
        n = len(c)
        if n < WARMUP + H + 5:
            continue
        atr = wilder_atr(h, l, c, 14)
        atr = np.where(np.isnan(atr) | (atr <= 0), np.nanmedian(atr), atr)
        pivots = build_pivots(h, l, 3)
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
            rf, bf = simulate(t, o, h, l, c, atr, n, None)
            rr, br = simulate(t, o, h, l, c, atr, n, 2.0)
            rows.append((dates[t], rf, bf, rr, br))
    return rows


def stats(rows):
    rf = np.array([r[1] for r in rows]); bf = np.array([r[2] for r in rows], float)
    rr = np.array([r[3] for r in rows]); br = np.array([r[4] for r in rows], float)
    return rf.mean(), rf.sum() / bf.sum(), rr.mean(), rr.sum() / br.sum(), len(rows)


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
    rows = collect(universe, con)
    con.close()

    splits = [("FULL", lambda r: True),
              ("A (even Q)", lambda r: quarter_parity(r[0]) == 0),
              ("B (odd Q)", lambda r: quarter_parity(r[0]) == 1),
              ("holdout 24mo", lambda r: r[0] >= HOLDOUT_START)]
    print(f"universe {len(universe)} names, gap-aware, H={H}. fixed vs up-day ratchet (close-2ATR).\n")
    print(f"{'split':14} {'n':>5} | {'fix meanR':>9} {'fix R/bar':>9} | "
          f"{'rat meanR':>9} {'rat R/bar':>9} | {'R/bar winner':>13}")
    for lab, msk in splits:
        sub = [r for r in rows if msk(r)]
        if not sub:
            print(f"{lab:14} {0:>5} | (empty)"); continue
        fm, fb, rm, rb, nn = stats(sub)
        winner = "ratchet" if rb > fb else "FIXED"
        print(f"{lab:14} {nn:>5} | {fm:>+9.3f} {fb:>+9.4f} | {rm:>+9.3f} {rb:>+9.4f} | {winner:>13}")
    print("\nratchet's R/bar edge is trustworthy only if it wins in A AND B AND holdout.")


if __name__ == "__main__":
    main()
