"""exit_geometry_v2 — per-family TP/SL/hold sweep for Bud's DEPLOYED cells (hardened).

exit_geometry_v1 tuned only the long-MR bucket (bb/rsi/ema long mid → 1.5%/1%/10d). Every
other deployed family still runs the untuned uniform 1%/1%/14d. This study sweeps a TP×SL×hold
grid per (strategy, direction, entry_mode) bucket, SELECTS the best geometry on in-sample (A+B),
and only recommends a change if it clears ALL of:
  - beats the deployed baseline's holdout mean_R by >= MARGIN (OOS, drops noise picks),
  - positive mean_R in A ∧ B ∧ holdout,
  - beats baseline on EDGE-OVER-RANDOM in the holdout (matched-random with the SAME geometry —
    nets out pair drift, the v1 lesson: a wide-TP short into a falling pair beats zero but not
    random-same-geometry),
  - does not materially worsen throughput (mean R per holding-day; Bud optimises $/day-per-slot).

Unit = R (fixed-risk sizing → 1R = constant $). Spread charged as spread/stop_dist. Read-only.
Fire events are cached (.cache/) so the slow detection runs once. Run:
  ./run.sh python research/exit_geometry_v2/run.py [--smoke] [--no-cache]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "research"))

from bud.briefing import LOOKBACK_BARS, ranked_cells, uses_long_mr_exit  # noqa: E402
from bud.auto_trader import deploy_predicate  # noqa: E402
from _lib import fx_replay as FR  # noqa: E402

TP_PCTS = [0.005, 0.0075, 0.010, 0.0125, 0.015, 0.020, 0.025, 0.030]
SL_PCTS = [0.005, 0.0075, 0.010, 0.0125, 0.015]
HOLD_DAYS = [10, 14, 21]
HOLDOUT_MONTHS = 24
MARGIN = 0.02          # min holdout improvement to call a change (drops noise)
THROUGHPUT_FLOOR = 0.9  # selected r_per_day must be >= this * baseline r_per_day
CACHE = Path(__file__).resolve().parent / ".cache"


def baseline_geom(cell):
    if uses_long_mr_exit(cell.strategy, cell.direction, cell.entry_mode):
        return (0.015, 0.010, 10)
    return (0.010, 0.010, 14)


def _bracket(P, entry, side, fwd_start, entry_idx, spread, tp, sl, hold_days):
    hi, lo, cl, ts = P["hi"], P["lo"], P["cl"], P["ts"]
    stop_dist = sl * entry
    if stop_dist <= 0:
        return None
    target_R = tp / sl
    k = fwd_start + int(((ts[fwd_start:] - ts[entry_idx]) <= np.timedelta64(hold_days, "D")).sum())
    if k <= fwd_start:
        return None
    R, exit_j = None, k - 1
    if side == 1:
        target, stop = entry + target_R * stop_dist, entry - stop_dist
        for j in range(fwd_start, k):
            if lo[j] <= stop:
                R, exit_j = -1.0, j; break
            if hi[j] >= target:
                R, exit_j = target_R, j; break
        if R is None:
            R = (cl[k - 1] - entry) / stop_dist
    else:
        target, stop = entry - target_R * stop_dist, entry + stop_dist
        for j in range(fwd_start, k):
            if hi[j] >= stop:
                R, exit_j = -1.0, j; break
            if lo[j] <= target:
                R, exit_j = target_R, j; break
        if R is None:
            R = (entry - cl[k - 1]) / stop_dist
    hold_actual = (ts[exit_j] - ts[entry_idx]) / np.timedelta64(1, "D")
    return R - spread / stop_dist, float(hold_actual)


def agg(evs, tp, sl, hold):
    rs, holds = [], []
    for P, e in evs:
        out = _bracket(P, e["entry"], e["side"], e["fwd_start"], e["entry_idx"], e["spread"], tp, sl, hold)
        if out:
            rs.append(out[0]); holds.append(out[1])
    if not rs:
        return None
    rs = np.asarray(rs); mh = float(np.mean(holds))
    return {"n": len(rs), "mean_R": float(rs.mean()),
            "mean_hold_d": mh, "r_per_day": float(rs.mean() / mh) if mh > 0 else np.nan}


def random_mean_R(bucket_pairs, P_by_pair, side, tp, sl, hold, n_target, rng, since=None):
    """Pooled mean R of random entries (same geometry/side) across the bucket's pairs."""
    per = max(50, (n_target * 20) // max(1, len(bucket_pairs)))
    rs = []
    for pair in bucket_pairs:
        P = P_by_pair[pair]; n = len(P["cl"]); ts = P["ts"]
        elig = np.arange(LOOKBACK_BARS, n - 1)
        if since is not None:
            elig = elig[ts[elig] >= np.datetime64(since)]
        if len(elig) == 0:
            continue
        for i in rng.choice(elig, size=min(per, len(elig)), replace=True):
            i = int(i)
            out = _bracket(P, float(P["cl"][i]), side, i + 1, i, float(P["spread"][i]), tp, sl, hold)
            if out:
                rs.append(out[0])
    return float(np.mean(rs)) if rs else np.nan


def cached_events(cell, P, use_cache):
    sig = json.dumps([cell.strategy, cell.pair, cell.direction, cell.entry_mode,
                      sorted(cell.params.items()), len(P["cl"]),
                      str(P["ts"][-1])], default=str, sort_keys=True)
    fp = CACHE / (hashlib.md5(sig.encode()).hexdigest() + ".json")
    if use_cache and fp.exists():
        evs = json.loads(fp.read_text())
        for e in evs:
            e["entry_ts"] = pd.Timestamp(e["entry_ts"])
        return evs
    evs = FR.fire_events(cell, P)
    CACHE.mkdir(exist_ok=True)
    ser = [{"entry_idx": int(e["entry_idx"]), "fwd_start": int(e["fwd_start"]),
            "entry": float(e["entry"]), "side": int(e["side"]),
            "entry_ts": e["entry_ts"].isoformat(), "symbol": e["symbol"],
            "spread": float(e["spread"])} for e in evs]
    fp.write_text(json.dumps(ser))
    return evs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--min-n", type=int, default=40)
    ap.add_argument("--candidate-sl", type=float, default=None,
                    help="test ONLY this SL%% per bucket (TP/hold = baseline) instead of the grid")
    ap.add_argument("--seed", type=int, default=20260625)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    cells = [c for c in ranked_cells() if deploy_predicate(c)]
    pairs = sorted({c.pair for c in cells})
    P_by_pair = FR.load_pairs(pairs, smoke=args.smoke)
    cells = [c for c in cells if c.pair in P_by_pair]
    max_ts = max(pd.Timestamp(P["ts"][-1]) for P in P_by_pair.values())
    holdout_cut = max_ts - pd.DateOffset(months=HOLDOUT_MONTHS)
    print(f"# deployed cells={len(cells)} pairs={len(pairs)} holdout_cut={holdout_cut.date()} "
          f"max_ts={max_ts.date()} smoke={args.smoke}")

    buckets = {}
    for cell in cells:
        P = P_by_pair[cell.pair]
        for e in cached_events(cell, P, not args.no_cache):
            buckets.setdefault((cell.strategy, cell.direction, cell.entry_mode), []).append((P, e))

    rows = []
    for key, evs in sorted(buckets.items()):
        strat, direction, emode = key
        side = 1 if direction == "long" else -1
        bp = sorted({e["symbol"] for _, e in evs})
        in_s = [(P, e) for P, e in evs if e["entry_ts"] < holdout_cut]
        hod = [(P, e) for P, e in evs if e["entry_ts"] >= holdout_cut]
        qm = [np.datetime64(e["entry_ts"], "M").astype(int) for _, e in in_s]
        A = [in_s[i] for i, q in enumerate(qm) if (q // 3) % 2 == 0]
        B = [in_s[i] for i, q in enumerate(qm) if (q // 3) % 2 == 1]
        rep = next(c for c in cells if (c.strategy, c.direction, c.entry_mode) == key)
        b_tp, b_sl, b_hold = baseline_geom(rep)
        base_in, base_h = agg(in_s, b_tp, b_sl, b_hold), agg(hod, b_tp, b_sl, b_hold)
        if base_in is None or base_in["n"] < args.min_n or base_h is None:
            rows.append({"bucket": f"{strat}:{direction}:{emode}", "verdict": "INSUFFICIENT",
                         "n_in": base_in["n"] if base_in else 0})
            continue

        if args.candidate_sl is not None:  # single-knob test: only SL moves
            tp, sl, hd = b_tp, args.candidate_sl, b_hold
            best_in = agg(in_s, tp, sl, hd)
        else:
            best = None
            for tp in TP_PCTS:
                for sl in SL_PCTS:
                    for hd in HOLD_DAYS:
                        m = agg(in_s, tp, sl, hd)
                        if m and (best is None or m["mean_R"] > best[1]["mean_R"]):
                            best = ((tp, sl, hd), m)
            (tp, sl, hd), best_in = best
        a, b, h = agg(A, tp, sl, hd), agg(B, tp, sl, hd), agg(hod, tp, sl, hd)

        # matched-random edge in the holdout (same geometry, nets out drift)
        base_rand = random_mean_R(bp, P_by_pair, side, b_tp, b_sl, b_hold, base_h["n"], rng, since=holdout_cut)
        best_rand = random_mean_R(bp, P_by_pair, side, tp, sl, hd, h["n"], rng, since=holdout_cut)
        base_edge = base_h["mean_R"] - base_rand
        best_edge = h["mean_R"] - best_rand

        same = abs(tp - b_tp) < 1e-9 and abs(sl - b_sl) < 1e-9 and hd == b_hold
        beats_oos = h["mean_R"] > base_h["mean_R"] + MARGIN
        robust = a and b and a["mean_R"] > 0 and b["mean_R"] > 0 and h["mean_R"] > 0
        beats_random = best_edge > base_edge + MARGIN
        keeps_throughput = best_in["r_per_day"] >= THROUGHPUT_FLOOR * base_in["r_per_day"]
        if same or not (beats_oos and robust and beats_random):
            verdict = "KEEP"
        elif not keeps_throughput:
            verdict = "TUNE*slow"
        else:
            verdict = "TUNE"

        rows.append({
            "bucket": f"{strat}:{direction}:{emode}", "n_in": base_in["n"], "n_hold": base_h["n"],
            "base_geom": f"{b_tp*100:.2g}/{b_sl*100:.2g}/{b_hold}", "base_hold_R": base_h["mean_R"],
            "base_edge": base_edge, "base_rday": base_in["r_per_day"],
            "best_geom": f"{tp*100:.2g}/{sl*100:.2g}/{hd}", "best_hold_R": h["mean_R"],
            "best_A": a["mean_R"] if a else np.nan, "best_B": b["mean_R"] if b else np.nan,
            "best_edge": best_edge, "best_rday": best_in["r_per_day"],
            "oosΔ": h["mean_R"] - base_h["mean_R"], "edgeΔ": best_edge - base_edge, "verdict": verdict,
        })

    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250, "display.max_columns", 40)
    cols = ["bucket", "n_in", "n_hold", "base_geom", "base_hold_R", "base_edge", "base_rday",
            "best_geom", "best_hold_R", "best_A", "best_B", "best_edge", "best_rday",
            "oosΔ", "edgeΔ", "verdict"]
    print(df[[c for c in cols if c in df.columns]].to_string(index=False, float_format=lambda x: f"{x:6.3f}"))
    out = Path(__file__).resolve().parent / "sweep.csv"
    df.to_csv(out, index=False)
    print(f"\nwrote {out}")
    tune = df[df["verdict"].astype(str).str.startswith("TUNE")] if "verdict" in df else df.iloc[:0]
    print("\nSurviving TUNE (beats baseline OOS, positive A∧B∧holdout, beats random-same-geometry):")
    for r in tune.itertuples():
        flag = " [SLOWER slot — check throughput]" if r.verdict == "TUNE*slow" else ""
        print(f"  {r.bucket}: {r.base_geom} -> {r.best_geom}  holdout {r.base_hold_R:.3f}->{r.best_hold_R:.3f} "
              f"(edgeΔ {r.edgeΔ:+.3f}){flag}")
    if tune.empty:
        print("  (none survive the drift + throughput gates — uniform baseline holds)")


if __name__ == "__main__":
    main()
