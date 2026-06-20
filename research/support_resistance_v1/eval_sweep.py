"""Parameter-sweep scorer for the v2 rejection-confirmed S/R detector.

Objective (read-only, the quantitative "would I have drawn this line"): after a
level CONFIRMS, how often is it RESPECTED (price returns and bounces) vs BROKEN
(body closes through), compared to a MATCHED RANDOM-LINE baseline. The headline
number is LIFT = respect_rate(real) - respect_rate(random). A parameter set that
finds real structure scores lift >> 0 while keeping a usable level count.

Reads a slice of the grid (one JSON combo per line) and a shared symbol list, so
N agents can each run a slice against identical symbols. Streams one symbol at a
time => tiny memory. Writes one CSV row per combo.

Usage:
  python eval_sweep.py --combos combos_slice_0.jsonl --symbols symbols.txt \
      --out results_0.csv [--start 2016-01-01] [--baseline-seed 7]
"""
import sys, os, json, argparse, time
import numpy as np, pandas as pd, duckdb

sys.path.insert(0, os.path.dirname(__file__))
from detector_v2 import detect_zones, prepare, SRParamsV2  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")


def _rate(resp, brk):
    tot = resp + brk
    return resp / tot if tot else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--combos", required=True)
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--baseline-seed", type=int, default=7)
    a = ap.parse_args()

    combos = [json.loads(ln) for ln in open(a.combos) if ln.strip()]
    params = [SRParamsV2(**c) for c in combos]
    syms = [s.strip() for s in open(a.symbols) if s.strip()]
    con = duckdb.connect(DB, read_only=True)
    print(f"{len(combos)} combos x {len(syms)} symbols -> {a.out}", flush=True)

    # per-combo accumulators: [Rresp, Rbrk, Bresp, Bbrk, confirmed, touch_sum, touch_n]
    acc = [[0, 0, 0, 0, 0, 0, 0] for _ in combos]
    nsym = 0
    t0 = time.time()
    # SYMBOL-OUTER: load + prepare(ATR/pivots/medv) ONCE per symbol, reuse across combos.
    for si, s in enumerate(syms):
        d = con.execute("SELECT high,low,close,volume FROM ohlcv WHERE symbol=? "
                        "AND date>=? ORDER BY date", [s, a.start]).df()
        if len(d) < 300:
            continue
        h, l, c, v = (d[x].to_numpy(float) for x in ("high", "low", "close", "volume"))
        prep_cache = {}
        for ci, P in enumerate(params):
            key = (P.atr_window, P.fractal_k, P.vol_median_window)
            prep = prep_cache.get(key)
            if prep is None:
                prep = prep_cache[key] = prepare(h, l, c, v, P)
            zones, st = detect_zones(h, l, c, v, P, prep=prep)
            ac = acc[ci]
            ac[0] += st["tests_respected"]; ac[1] += st["tests_broken"]
            ac[4] += st["n_confirmed"]
            for z in zones:
                if z.confirmed:
                    ac[5] += len(z.touch_bars); ac[6] += 1
            rng = np.random.default_rng(a.baseline_seed + si)
            _, stb = detect_zones(h, l, c, v, P, price_rng=rng, prep=prep)
            ac[2] += stb["tests_respected"]; ac[3] += stb["tests_broken"]
        nsym += 1
        if nsym % 25 == 0:
            print(f"  {nsym}/{len(syms)} symbols ({time.time()-t0:.0f}s)", flush=True)

    rows = []
    for combo, ac in zip(combos, acc):
        rows.append({**combo,
                     "nsym": nsym,
                     "confirmed": ac[4],
                     "lvls_per_sym": round(ac[4] / nsym, 3) if nsym else 0,
                     "n_tests": ac[0] + ac[1],
                     "respect": round(_rate(ac[0], ac[1]), 4),
                     "base_respect": round(_rate(ac[2], ac[3]), 4),
                     "lift": round(_rate(ac[0], ac[1]) - _rate(ac[2], ac[3]), 4),
                     "med_touches": round(ac[5] / ac[6], 2) if ac[6] else 0.0})
    pd.DataFrame(rows).to_csv(a.out, index=False)
    print(f"done. {len(rows)} combos in {time.time()-t0:.0f}s -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
