"""Path B pipeline: build 5d deploy ledger -> gate overlay -> sizing sweep.

Reads the per-strategy 5d ledgers from 5day_ledgers/, builds a combined
deploy ledger, runs the gate overlay, and runs the FTMO sizing sweep at
deployed sizing (0.005). Produces a side-by-side comparison vs the canonical
14d portfolio.

This is the moment-of-truth: does the 5d cap's faster turnover let enough
extra trades through the gate overlay to offset the per-trade R hit?
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "ftmo_sizing_sim"))
sys.path.insert(0, str(REPO / "src"))

from sim import SizingConfig, run_cohort, load_ftmo_config  # noqa: E402
from bh_briefing import CELLS  # noqa: E402
from bh_ftmo_v2_paper import DEPLOYED_STRATEGIES  # noqa: E402
from bh_ftmo.trading.safety import MAX_NET_DIRECTION_IMBALANCE  # noqa: E402

LEDGERS_5D = REPO / "research" / "v2_deploy_backtest" / "5day_ledgers"
DEPLOY_5D = REPO / "research" / "v2_deploy_backtest" / "deploy_ledger_5d.csv"
GATED_5D = REPO / "research" / "v2_deploy_backtest" / "gated_ledger_5d.csv"
RESULTS_5D = REPO / "research" / "v2_deploy_backtest" / "path_b_results.json"

DEPLOYED_SIZING = 0.005
N_STARTS = 500
MAX_NEW_ORDERS_PER_RUN = 5

# entry_mode per strategy mirrors DEPLOY_PREDICATE deployment shape
ENTRY_MODE = {
    "macd": "limit", "atr": "limit", "ichimoku": "limit",
    "stoch": "mid", "cci": "mid", "bb": "mid",
    "ema": "mid", "sma": "mid", "rsi": "mid",
}


def build_5d_deploy_ledger() -> pd.DataFrame:
    direction_by = {(c.strategy, c.pair): c.direction
                    for c in CELLS if c.strategy in DEPLOYED_STRATEGIES}
    parts = []
    for strat in DEPLOYED_STRATEGIES:
        em = ENTRY_MODE[strat]
        path = LEDGERS_5D / f"{strat}_5d_{em}.csv"
        if not path.exists():
            print(f"  WARN: missing {path}")
            continue
        df = pd.read_csv(path)
        df["strategy"] = strat
        df["entry_mode"] = em
        df["direction"] = df["pair"].map(lambda p, s=strat: direction_by.get((s, p)))
        df = df.dropna(subset=["direction"])
        parts.append(df)
    ledger = pd.concat(parts, ignore_index=True)
    ledger["entry_ts"] = pd.to_datetime(ledger["entry_ts"])
    ledger["exit_ts"] = pd.to_datetime(ledger["exit_ts"])
    ledger = ledger.sort_values("entry_ts").reset_index(drop=True)
    return ledger[["entry_ts", "exit_ts", "strategy", "pair", "direction", "entry_mode", "r"]]


def gate_overlay(ledger: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    entry_buckets = ledger["entry_ts"].dt.floor("4h").astype("int64").to_numpy()
    entry_ns = ledger["entry_ts"].astype("datetime64[ns]").astype("int64").to_numpy()
    exit_ns = ledger["exit_ts"].astype("datetime64[ns]").astype("int64").to_numpy()

    events = []
    for i in range(len(ledger)):
        events.append((int(entry_ns[i]), 0, i))
        events.append((int(exit_ns[i]), 1, i))
    events.sort()

    open_pairs = set()
    open_idxs = {}
    n_long = n_short = 0
    bucket_count = defaultdict(int)
    kept = []
    skips = Counter()
    pairs = ledger["pair"].to_numpy()
    dirs = ledger["direction"].to_numpy()

    for ts_ns, kind, idx in events:
        if kind == 1:
            if idx in open_idxs:
                d = open_idxs.pop(idx)
                open_pairs.discard(pairs[idx])
                if d == "long":
                    n_long -= 1
                else:
                    n_short -= 1
            continue
        pair = pairs[idx]
        direction = dirs[idx]
        if pair in open_pairs:
            skips["skip_already_open"] += 1
            continue
        bucket = int(entry_buckets[idx])
        if bucket_count[bucket] >= MAX_NEW_ORDERS_PER_RUN:
            skips["skip_per_run_cap"] += 1
            continue
        if direction == "long":
            if (n_long + 1) - n_short > MAX_NET_DIRECTION_IMBALANCE:
                skips["skip_direction_imbalance_long"] += 1
                continue
        else:
            if (n_short + 1) - n_long > MAX_NET_DIRECTION_IMBALANCE:
                skips["skip_direction_imbalance_short"] += 1
                continue
        open_pairs.add(pair)
        open_idxs[idx] = direction
        if direction == "long":
            n_long += 1
        else:
            n_short += 1
        bucket_count[bucket] += 1
        kept.append(idx)

    kept_df = ledger.iloc[kept].reset_index(drop=True)
    return kept_df, {"in": len(ledger), "kept": len(kept), "skips": dict(skips)}


def run_ftmo(ledger: pd.DataFrame, ftmo, sizing_pct: float) -> dict:
    sizing = SizingConfig(mode="fixed", risk_per_trade_pct=sizing_pct)
    out = {}
    for model in ("realistic", "conservative"):
        c = run_cohort(ledger, ftmo, sizing, n_starts=N_STARTS,
                       intra_trade_model=model, seed=42)
        results = c.pop("results", [])
        if results:
            d = [r.days_to_resolution for r in results if r.status == "passed"]
            c["pass_days_p50"] = float(np.median(d)) if d else None
            c["pass_days_p75"] = float(np.percentile(d, 75)) if d else None
        out[model] = c
    return out


def main() -> int:
    print("=== Building 5d deploy ledger ===")
    ledger = build_5d_deploy_ledger()
    ledger.to_csv(DEPLOY_5D, index=False)
    print(f"  trades: {len(ledger):,}  pairs: {ledger['pair'].nunique()}  "
          f"mean_R: {ledger['r'].mean():+.4f}  cum_R: {ledger['r'].sum():+.1f}")
    print(f"  long/short: {(ledger['direction']=='long').sum()}/"
          f"{(ledger['direction']=='short').sum()}")
    print()

    print("=== Gate overlay (5d) ===")
    gated, gate_summary = gate_overlay(ledger)
    gated.to_csv(GATED_5D, index=False)
    retention = gate_summary["kept"] / gate_summary["in"] * 100
    print(f"  in={gate_summary['in']:,}  kept={gate_summary['kept']:,}  retention={retention:.1f}%")
    print(f"  skips: {gate_summary['skips']}")
    print(f"  gated mean_R: {gated['r'].mean():+.4f}  cum_R: {gated['r'].sum():+.1f}")
    print(f"  gated long/short: {(gated['direction']=='long').sum()}/"
          f"{(gated['direction']=='short').sum()}")
    print()

    print(f"=== FTMO sim on gated 5d ledger (sizing={DEPLOYED_SIZING*100:.2f}%) ===")
    ftmo = load_ftmo_config(str(REPO / "src" / "bh_ftmo_swing_config.json"), phase="step1")
    sim_5d = run_ftmo(gated, ftmo, DEPLOYED_SIZING)
    for model, c in sim_5d.items():
        med = c.get("pass_days_p50")
        med_str = f"{med:.0f}d" if med is not None else "n/a"
        print(f"  {model:12s}  pass={c['pass_rate']*100:5.1f}%  "
              f"failed={c['failed']}/{c['n_starts']}  median_pass={med_str}")
    print()

    # Compare against the canonical 14d gated results
    canonical = REPO / "research" / "v2_deploy_backtest" / "sweep_gated_results.json"
    if canonical.exists():
        cdata = json.loads(canonical.read_text())
        # Find the 0.005 sizing result
        canonical_5pct = None
        for sizing, c in cdata.get("sizing_sweep", []):
            try:
                if abs(float(sizing) - DEPLOYED_SIZING) < 1e-9:
                    canonical_5pct = c
                    break
            except (ValueError, TypeError):
                continue
        if canonical_5pct:
            print("=== Comparison vs 14d (canonical) ===")
            print(f"{'metric':35s}  {'14d':>14s}   {'5d':>14s}   {'delta':>10s}")
            print("-" * 80)
            from pathlib import Path as P
            orig_gated = pd.read_csv(REPO / "research" / "v2_deploy_backtest" / "gated_ledger.csv")
            orig_n = len(orig_gated)
            orig_r = orig_gated["r"].mean()
            orig_cum = orig_gated["r"].sum()
            print(f"  {'gated trade count':33s}  {orig_n:>14,d}   {len(gated):>14,d}   "
                  f"{(len(gated)-orig_n)/orig_n*100:>+9.1f}%")
            print(f"  {'gated mean R':33s}  {orig_r:>+14.4f}   {gated['r'].mean():>+14.4f}   "
                  f"{(gated['r'].mean()-orig_r)/abs(orig_r)*100:>+9.1f}%")
            print(f"  {'gated cum R':33s}  {orig_cum:>+14.1f}   {gated['r'].sum():>+14.1f}   "
                  f"{(gated['r'].sum()-orig_cum)/abs(orig_cum)*100:>+9.1f}%")
            for model in ("realistic", "conservative"):
                c14 = canonical_5pct.get(model, {})
                c5 = sim_5d[model]
                p14 = c14.get("pass_rate", 0) * 100
                p5 = c5["pass_rate"] * 100
                m14 = c14.get("pass_days_p50") or c14.get("median_days_to_pass")
                m5 = c5.get("pass_days_p50") or c5.get("median_days_to_pass")
                print(f"  {f'pass rate ({model})':33s}  {p14:>13.1f}%   {p5:>13.1f}%   {p5-p14:>+9.1f}pp")
                if m14 and m5:
                    print(f"  {f'median pass days ({model})':33s}  {m14:>13.0f}d   {m5:>13.0f}d   {m5-m14:>+9.0f}d")

    out = {
        "ledger_5d": str(DEPLOY_5D),
        "gated_5d": str(GATED_5D),
        "deployed_sizing": DEPLOYED_SIZING,
        "n_starts": N_STARTS,
        "gate_summary": gate_summary,
        "sim_5d": sim_5d,
        "gated_5d_stats": {
            "n": int(len(gated)),
            "mean_r": float(gated["r"].mean()) if len(gated) else 0.0,
            "cum_r": float(gated["r"].sum()) if len(gated) else 0.0,
        },
    }
    RESULTS_5D.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {RESULTS_5D}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
