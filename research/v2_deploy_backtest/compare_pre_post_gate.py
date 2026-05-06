"""Compare FTMO Step-1 pass rate on the deploy ledger vs the gate-overlaid ledger.

Runs the sim only at the deployed sizing (RISK_PER_TRADE_PCT = 0.0025) under
both intra-trade models. Prints a side-by-side table.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "ftmo_sizing_sim"))
sys.path.insert(0, str(REPO / "src"))

from sim import SizingConfig, run_cohort, load_ftmo_config  # noqa: E402

PRE = REPO / "research" / "v2_deploy_backtest" / "deploy_ledger.csv"
POST = REPO / "research" / "v2_deploy_backtest" / "gated_ledger.csv"
FTMO_CONFIG = REPO / "src" / "bh_ftmo_swing_config.json"
OUT = REPO / "research" / "v2_deploy_backtest" / "pre_post_gate_results.json"

DEPLOYED_SIZING = 0.0025
N_STARTS = 500


def run(ledger_path: Path, ftmo, sizing_pct: float) -> dict:
    df = pd.read_csv(ledger_path)
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df["exit_ts"] = pd.to_datetime(df["exit_ts"])
    sizing = SizingConfig(mode="fixed", risk_per_trade_pct=sizing_pct)
    out = {"n_trades": int(len(df)),
           "mean_r": float(df["r"].mean()),
           "cum_r": float(df["r"].sum())}
    for model in ("realistic", "conservative"):
        c = run_cohort(df, ftmo, sizing, n_starts=N_STARTS,
                       intra_trade_model=model, seed=42)
        c.pop("results", None)
        out[model] = c
    return out


def main() -> int:
    ftmo = load_ftmo_config(str(FTMO_CONFIG), phase="step1")
    print(f"Sizing: {DEPLOYED_SIZING*100:.2f}% per trade  (deployed)")
    print(f"FTMO Step 1: target={ftmo.profit_target_pct*100:.0f}%, "
          f"daily DD={ftmo.daily_loss_pct*100:.0f}%, max DD={ftmo.max_loss_pct*100:.0f}%, "
          f"{N_STARTS} random starts")
    print()

    print("Running pre-gate ledger...")
    pre = run(PRE, ftmo, DEPLOYED_SIZING)
    print("Running post-gate (gated) ledger...")
    post = run(POST, ftmo, DEPLOYED_SIZING)

    print()
    print(f"{'metric':35s}  {'pre-gate':>14s}   {'post-gate':>14s}")
    print("-" * 70)
    print(f"{'trades':35s}  {pre['n_trades']:>14,d}   {post['n_trades']:>14,d}")
    print(f"{'mean R/trade (pure-R)':35s}  {pre['mean_r']:>+14.4f}   {post['mean_r']:>+14.4f}")
    print(f"{'cum R':35s}  {pre['cum_r']:>+14.1f}   {post['cum_r']:>+14.1f}")
    for model in ("realistic", "conservative"):
        print()
        print(f"  {model.upper()}:")
        print(f"    {'pass rate':33s}  {pre[model]['pass_rate']*100:>13.1f}%   "
              f"{post[model]['pass_rate']*100:>13.1f}%")
        print(f"    {'failed / n':33s}  {pre[model]['failed']:>5d}/{pre[model]['n_starts']:<6d}   "
              f"{post[model]['failed']:>5d}/{post[model]['n_starts']:<6d}")
        for fr in sorted(set(pre[model].get("fail_reasons", {})) |
                         set(post[model].get("fail_reasons", {}))):
            a = pre[model].get("fail_reasons", {}).get(fr, 0)
            b = post[model].get("fail_reasons", {}).get(fr, 0)
            print(f"    {('fail['+fr+']'):33s}  {a:>14d}   {b:>14d}")
        med_a = pre[model].get("median_days_to_pass")
        med_b = post[model].get("median_days_to_pass")
        print(f"    {'median days to pass':33s}  "
              f"{(f'{med_a:.0f}d' if med_a is not None else 'n/a'):>14s}   "
              f"{(f'{med_b:.0f}d' if med_b is not None else 'n/a'):>14s}")

    OUT.write_text(json.dumps({"pre": pre, "post": post,
                                "deployed_sizing": DEPLOYED_SIZING,
                                "n_starts": N_STARTS},
                               indent=2, default=str))
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
