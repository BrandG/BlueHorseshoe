"""short_discovery_v1 — where does each indicator family have a SHORT edge?

The Bud book is structurally long-skewed (most cells are long). This scans the SHORT direction
of each indicator family across the curated liquid universe to find deployable short cells that
would balance the book and add throughput.

Methodology (scan-then-gate, per research/README.md):
- Reuse the fidelity-checked fire detection in research/_lib/fx_replay.py. For each family, take a
  representative param template from CELLS and flip direction to "short" (the mean-reversion
  evaluators auto-map to the overbought/rollover trigger; sma/ema params are direction-agnostic).
- Bracketed R net of spread, standard discovery geometry 1%/1%/14d (discover the SIGNAL first;
  geometry-tune later).
- Splits: in-sample before last 24mo; holdout = last 24mo; A/B interleaved quarters in-sample.
- **Matched-random-SHORT control**: each candidate must beat random shorts on the SAME pair/geometry
  (nets out pair downtrend — a short edge on a pair that just fell is drift, not signal).
- No premature gating: the full ranked landscape is printed; the rigor gate (positive A∧B∧holdout,
  expectancy-CI, beats random) just TAGS the deployable survivors.

Read-only. Run: ./run.sh python research/short_discovery_v1/run.py [--smoke]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "research"))

from bud.briefing import CELLS, Cell  # noqa: E402
from _lib import fx_replay as FR  # noqa: E402
from _lib import harness as H  # noqa: E402

TP, SL, HOLD_DAYS = 0.010, 0.010, 14
HOLDOUT_MONTHS = 24
LBARS = FR.LOOKBACK_BARS
# Fast (vectorized) families with plausible short setups. atr/macd/ichimoku (slow per-bar) deferred.
FAMILIES = ["bb", "rsi", "cci", "stoch", "sma", "ema"]


def representative_params(strategy):
    """(params, entry_mode) from the first CELL of this strategy — a valid short template."""
    for c in CELLS:
        if c.strategy == strategy:
            return dict(c.params), c.entry_mode
    return None


def bracket_short(P, ev):
    hi, lo, cl, ts = P["hi"], P["lo"], P["cl"], P["ts"]
    entry, fwd_start, entry_idx = ev["entry"], ev["fwd_start"], ev["entry_idx"]
    stop_dist = SL * entry
    if stop_dist <= 0:
        return None
    target_R = TP / SL
    k = fwd_start + int(((ts[fwd_start:] - ts[entry_idx]) <= np.timedelta64(HOLD_DAYS, "D")).sum())
    if k <= fwd_start:
        return None
    target, stop = entry - target_R * stop_dist, entry + stop_dist
    R = None
    for j in range(fwd_start, k):
        if hi[j] >= stop:
            R = -1.0; break
        if lo[j] <= target:
            R = target_R; break
    if R is None:
        R = (entry - cl[k - 1]) / stop_dist
    return R - ev["spread"] / stop_dist


def random_short_meanR(P, rng, n_target, since=None):
    n = len(P["cl"]); ts = P["ts"]
    elig = np.arange(LBARS, n - 1)
    if since is not None:
        elig = elig[ts[elig] >= np.datetime64(since)]
    if len(elig) == 0:
        return np.nan
    rs = []
    for i in rng.choice(elig, size=min(max(400, n_target * 20), len(elig)), replace=True):
        i = int(i)
        ev = {"entry": float(P["cl"][i]), "fwd_start": i + 1, "entry_idx": i, "spread": float(P["spread"][i])}
        out = bracket_short(P, ev)
        if out is not None:
            rs.append(out)
    return float(np.mean(rs)) if rs else np.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--min-n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=20260626)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    universe = sorted({c.pair for c in CELLS})
    P_by_pair = FR.load_pairs(universe, smoke=args.smoke)
    universe = [p for p in universe if p in P_by_pair]
    max_ts = max(pd.Timestamp(P["ts"][-1]) for P in P_by_pair.values())
    holdout_cut = max_ts - pd.DateOffset(months=HOLDOUT_MONTHS)
    print(f"# short discovery  families={FAMILIES}  pairs={len(universe)}  "
          f"holdout_cut={holdout_cut.date()}  geom={TP*100:g}/{SL*100:g}/{HOLD_DAYS}  smoke={args.smoke}")

    templates = {f: representative_params(f) for f in FAMILIES}
    rows = []
    for fam in FAMILIES:
        tmpl = templates[fam]
        if tmpl is None:
            continue
        params, emode = tmpl
        for pair in universe:
            P = P_by_pair[pair]
            cell = Cell(fam, pair, "short", emode, params)
            evs = FR.fire_events(cell, P)
            recs = []
            for e in evs:
                r = bracket_short(P, e)
                if r is not None:
                    recs.append((e["entry_ts"], r))
            if len(recs) < args.min_n:
                continue
            df = pd.DataFrame(recs, columns=["ts", "R"]).sort_values("ts")
            net = df["R"].to_numpy()
            full = H.summarize_R(net, L=HOLD_DAYS * 6 - 1)
            se = max(full.get("nw_se", np.nan), full.get("clustered_se", np.nan))
            ci_low = full["mean_R"] - 1.96 * se
            q = df["ts"].dt.year * 4 + (df["ts"].dt.month - 1) // 3
            ins = df[df["ts"] < holdout_cut]; hod = df[df["ts"] >= holdout_cut]
            a = ins[q[ins.index] % 2 == 0]["R"]; b = ins[q[ins.index] % 2 == 1]["R"]
            rand_full = random_short_meanR(P, rng, len(df))
            edge = full["mean_R"] - rand_full
            robust = len(a) and len(b) and len(hod) and a.mean() > 0 and b.mean() > 0 and hod["R"].mean() > 0
            passes = bool(full["mean_R"] > 0 and robust and ci_low > 0 and edge > 0)
            verdict = "DISCOVER" if passes else ("promising" if full["mean_R"] > 0 and edge > 0 else "none")
            rows.append({
                "strategy": fam, "pair": pair, "n": len(df), "mean_R": full["mean_R"],
                "ci_low": ci_low, "nw_t": full.get("nw_t", np.nan),
                "A": a.mean() if len(a) else np.nan, "B": b.mean() if len(b) else np.nan,
                "hold": hod["R"].mean() if len(hod) else np.nan,
                "rand": rand_full, "edge": edge, "verdict": verdict,
            })

    df = pd.DataFrame(rows)
    if df.empty:
        print("no candidates met min-n"); return
    df = df.sort_values(["verdict", "edge"], ascending=[True, False])
    pd.set_option("display.width", 230, "display.max_columns", 40)
    cols = ["strategy", "pair", "n", "mean_R", "ci_low", "nw_t", "A", "B", "hold", "rand", "edge", "verdict"]
    print(df[cols].to_string(index=False, float_format=lambda x: f"{x:6.3f}"))
    out = Path(__file__).resolve().parent / "discovery.csv"
    df.to_csv(out, index=False)
    print(f"\nwrote {out}")
    disc = df[df["verdict"] == "DISCOVER"]
    print(f"\nDISCOVER — deployable short candidates (positive A∧B∧holdout, CI>0, beats random short):")
    for r in disc.itertuples():
        print(f"  {r.strategy}:{r.pair}:short  mean {r.mean_R:.3f}R  edge+{r.edge:.3f}  "
              f"(A {r.A:.3f} B {r.B:.3f} hold {r.hold:.3f}, n={r.n})")
    if disc.empty:
        print("  (none cleared the full gate — see 'promising' rows for param-tuning candidates)")


if __name__ == "__main__":
    main()
