"""Sizing sweep on the gated ledger.

Same shape as run_deploy_backtest.py's sweep but pointed at gated_ledger.csv,
and it also prints the equivalent pre-gate row from results.json (computed
earlier) so you can see the gate effect at every sizing in one table.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "ftmo_sizing_sim"))
sys.path.insert(0, str(REPO / "src"))

from sim import SizingConfig, run_cohort, load_ftmo_config  # noqa: E402

GATED = REPO / "research" / "v2_deploy_backtest" / "gated_ledger.csv"
PRE_RESULTS = REPO / "research" / "v2_deploy_backtest" / "results.json"
FTMO_CONFIG = REPO / "src" / "bh_ftmo_swing_config.json"
OUT = REPO / "research" / "v2_deploy_backtest" / "sweep_gated_results.json"

SIZING_SWEEP = [0.0025, 0.005, 0.0075, 0.01, 0.015, 0.02]
N_STARTS = 500


def main() -> int:
    df = pd.read_csv(GATED)
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df["exit_ts"] = pd.to_datetime(df["exit_ts"])
    print(f"Gated ledger: {len(df):,} trades, {df['entry_ts'].min().date()} → {df['entry_ts'].max().date()}")
    print(f"Pure-R: mean={df['r'].mean():+.4f}  cum={df['r'].sum():+.1f}\n")

    ftmo = load_ftmo_config(str(FTMO_CONFIG), phase="step1")
    print(f"FTMO Step 1: target={ftmo.profit_target_pct*100:.0f}%, "
          f"daily DD={ftmo.daily_loss_pct*100:.0f}%, max DD={ftmo.max_loss_pct*100:.0f}%")
    print(f"({N_STARTS} random starts per cohort)\n")

    pre_sweep = {}
    if PRE_RESULTS.exists():
        pre = json.loads(PRE_RESULTS.read_text())
        pre_sweep = pre.get("sweep", {})

    rows = []
    for sizing in SIZING_SWEEP:
        sizing_cfg = SizingConfig(mode="fixed", risk_per_trade_pct=sizing)
        cohort_out = {}
        for model in ("realistic", "conservative"):
            c = run_cohort(df, ftmo, sizing_cfg, n_starts=N_STARTS,
                           intra_trade_model=model, seed=42)
            results = c.pop("results", [])
            if results:
                pass_days = [r.days_to_resolution for r in results if r.status == "passed"]
                if pass_days:
                    c["pass_days_p25"] = float(np.percentile(pass_days, 25))
                    c["pass_days_p50"] = float(np.percentile(pass_days, 50))
                    c["pass_days_p75"] = float(np.percentile(pass_days, 75))
                c["max_dd_p50"] = float(np.median([r.max_dd_pct for r in results]))
                c["max_dd_p95"] = float(np.percentile([r.max_dd_pct for r in results], 95))
            cohort_out[model] = c
        rows.append((sizing, cohort_out))

    print(f"{'sizing':>8s}  {'pre-gate(real)':>15s}  {'post-gate(real)':>16s}  {'post-gate(cons)':>16s}  {'med pass':>10s}  {'p75 pass':>10s}  {'p50 maxDD':>10s}")
    print("-" * 100)
    for sizing, c in rows:
        key = f"{sizing:.4f}"
        pre = pre_sweep.get(key, {}).get("realistic", {})
        pre_pass = pre.get("pass_rate")
        pre_str = f"{pre_pass*100:>13.1f}%" if pre_pass is not None else "          n/a"
        rl = c["realistic"]
        cn = c["conservative"]
        med = rl.get("pass_days_p50")
        p75 = rl.get("pass_days_p75")
        med_str = f"{med:.0f}d" if med is not None else "n/a"
        p75_str = f"{p75:.0f}d" if p75 is not None else "n/a"
        dd_str = f"{rl.get('max_dd_p50', 0)*100:.1f}%"
        print(f"  {sizing*100:>5.2f}%  {pre_str:>15s}  "
              f"{rl['pass_rate']*100:>14.1f}%  {cn['pass_rate']*100:>14.1f}%  "
              f"{med_str:>10s}  {p75_str:>10s}  {dd_str:>10s}")

    OUT.write_text(json.dumps({
        "n_starts": N_STARTS,
        "sizing_sweep": [(s, c) for s, c in rows],
    }, indent=2, default=str))
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
