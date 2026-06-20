"""Build a TRENDING universe for the door #2 break test.

symbols.txt is a range-bound sample (ER tops out ~0.185), so it can't host a
breaks-continue test. Scan the full DuckDB, apply the same price/liquidity filters
bounce_sim/break_sim use, compute Kaufman ER (range_score), and keep the most
DIRECTIONAL liquid names. Writes symbols_trend.txt (one ticker per line) and prints
the ER distribution + selected band so the threshold is honest, not guessed.
"""
import sys, os
import numpy as np, duckdb

sys.path.insert(0, os.path.dirname(__file__))
from detector_v3 import range_score   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")
START = "2016-01-01"
TOP_N = 80          # keep this many most-trending liquid names (~ matches 60 range-bound set)
VOL_FLOOR = 0.015   # median daily (high-low)/close; drops cash/bond ETFs (TBIL/SGOV ~0.001)


def main():
    con = duckdb.connect(DB, read_only=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol, COUNT(*) k FROM ohlcv WHERE date>=? GROUP BY symbol HAVING k>=900",
        [START]).fetchall()]
    print(f"scanning {len(syms)} symbols with >=900 bars...", flush=True)
    scored = []
    for i, s in enumerate(syms):
        if i % 1000 == 0:
            print(f"  {i}/{len(syms)}", flush=True)
        d = con.execute("SELECT high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",
                        [s, START]).df()
        h = d.high.to_numpy(float); l = d.low.to_numpy(float)
        c = d.close.to_numpy(float); v = d.volume.to_numpy(float)
        if len(c) < 900 or not (5 <= c[-1] <= 500):
            continue
        if np.median(c[-120:] * v[-120:]) < 3e6:
            continue
        vol = np.median((h - l) / c)                     # typical daily range; cash ETFs ~0.001
        if vol < VOL_FLOOR:
            continue
        rs = range_score(c)
        if not np.isnan(rs):
            scored.append((s, rs))
    con.close()

    arr = np.array([e[1] for e in scored])
    print(f"\nliquid symbols with ER: {len(arr)}")
    for q in (50, 75, 90, 95, 99, 100):
        print(f"  p{q:>3}: {np.percentile(arr, q):.3f}")
    for thr in (0.15, 0.18, 0.20, 0.25, 0.30):
        print(f"  ER>={thr}: {int((arr >= thr).sum())} symbols")

    top = sorted(scored, key=lambda e: -e[1])[:TOP_N]
    lo = top[-1][1]; hi = top[0][1]
    out = os.path.join(HERE, "symbols_trend.txt")
    with open(out, "w") as f:
        f.write("\n".join(s for s, _ in top) + "\n")
    print(f"\nwrote {len(top)} symbols to {out} (ER band {lo:.3f}..{hi:.3f})")
    print("top 15:", ", ".join(f"{s}:{r:.2f}" for s, r in top[:15]))


if __name__ == "__main__":
    main()
