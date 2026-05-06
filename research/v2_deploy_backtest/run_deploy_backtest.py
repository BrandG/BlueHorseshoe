"""Run the FTMO sizing sim on the 33-cell deployed v2 portfolio.

Inputs:
  research/v2_deploy_backtest/deploy_ledger.csv  (built by build_deploy_ledger.py)
  src/bh_ftmo_swing_config.json                  (FTMO challenge rules)

Outputs:
  - Portfolio-level statistics (independent of sim, computed from ledger)
  - FTMO Step-1 pass rate at deployed sizing (0.5%) under both intra-trade models
  - Sizing sweep (0.25%, 0.5%, 0.75%, 1.0%) so we can see how the deployed
    sizing compares to alternatives
  - Per-strategy contribution breakdown
  - results.json with all metrics for downstream consumption
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "research" / "ftmo_sizing_sim"))
sys.path.insert(0, str(REPO / "src"))

from sim import FtmoConfig, SizingConfig, run_cohort, load_ftmo_config  # noqa: E402

LEDGER_PATH = REPO / "research" / "v2_deploy_backtest" / "deploy_ledger.csv"
FTMO_CONFIG = REPO / "src" / "bh_ftmo_swing_config.json"
RESULTS_PATH = REPO / "research" / "v2_deploy_backtest" / "results.json"

DEPLOYED_SIZING = 0.005  # what bh_ftmo_v2_paper.RISK_PER_TRADE_PCT uses
SIZING_SWEEP = [0.0025, 0.005, 0.0075, 0.01]
N_STARTS = 500


def wilson_ci(wins: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    p = wins / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * np.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return centre - half, centre + half


def ledger_stats(ledger: pd.DataFrame) -> dict:
    rs = ledger["r"].to_numpy()
    n = len(rs)
    wins = int((rs >= 1.0 - 1e-9).sum())
    losses = int((rs <= -1.0 + 1e-9).sum())
    timeouts = n - wins - losses

    cum_r = np.cumsum(rs)
    running_max = np.maximum.accumulate(cum_r)
    drawdowns = cum_r - running_max
    max_dd_r = float(drawdowns.min())

    span = (ledger["entry_ts"].max() - ledger["entry_ts"].min()).days
    trades_per_day = n / max(span, 1)

    wlo, whi = wilson_ci(wins, max(wins + losses, 1))

    by_strat = ledger.groupby("strategy")["r"].agg(["count", "mean", "sum"])
    by_dir = ledger.groupby("direction")["r"].agg(["count", "mean", "sum"])

    return {
        "n_trades": n,
        "wins": wins,
        "losses": losses,
        "timeouts": timeouts,
        "win_rate": wins / max(wins + losses, 1),
        "wr_ci_low": wlo,
        "wr_ci_high": whi,
        "mean_r": float(rs.mean()),
        "std_r": float(rs.std(ddof=1)),
        "cum_r": float(rs.sum()),
        "max_dd_r": max_dd_r,
        "span_days": span,
        "trades_per_day": trades_per_day,
        "by_strategy": {s: {"n": int(row["count"]), "mean_r": float(row["mean"]),
                            "cum_r": float(row["sum"])}
                        for s, row in by_strat.iterrows()},
        "by_direction": {d: {"n": int(row["count"]), "mean_r": float(row["mean"]),
                             "cum_r": float(row["sum"])}
                         for d, row in by_dir.iterrows()},
    }


def fmt_cohort(name: str, c: dict) -> str:
    if c.get("n_starts", 0) == 0:
        return f"  {name}: insufficient data ({c.get('error', 'unknown')})"
    fr = c.get("fail_reasons", {})
    fr_str = ", ".join(f"{k}={v}" for k, v in sorted(fr.items())) or "n/a"
    median = c.get("median_days_to_pass")
    median_str = f"{median:.0f}d" if median is not None else "n/a"
    return (f"  {name}: pass={c['pass_rate']*100:5.1f}%  "
            f"failed={c['failed']}/{c['n_starts']}  "
            f"in_progress={c['in_progress']}  "
            f"median_pass={median_str}  fail_reasons[{fr_str}]")


def run_sim(ledger: pd.DataFrame, ftmo: FtmoConfig, sizing_pct: float) -> dict:
    sizing = SizingConfig(mode="fixed", risk_per_trade_pct=sizing_pct)
    out = {}
    for model in ("realistic", "conservative"):
        c = run_cohort(ledger, ftmo, sizing, n_starts=N_STARTS,
                       intra_trade_model=model, seed=42)
        # Strip the per-result list to keep results.json small
        results = c.pop("results", [])
        # Aggregate days_to_resolution distribution
        if results:
            d = [r.days_to_resolution for r in results if r.status == "passed"]
            c["pass_days_p25"] = float(np.percentile(d, 25)) if d else None
            c["pass_days_p75"] = float(np.percentile(d, 75)) if d else None
            c["max_dd_pct_p50"] = float(np.median([r.max_dd_pct for r in results]))
            c["max_dd_pct_p95"] = float(np.percentile([r.max_dd_pct for r in results], 95))
        out[model] = c
    return out


def main() -> int:
    if not LEDGER_PATH.exists():
        print(f"ERROR: missing {LEDGER_PATH} — run build_deploy_ledger.py first")
        return 1

    print(f"Loading {LEDGER_PATH.name}...")
    ledger = pd.read_csv(LEDGER_PATH)
    ledger["entry_ts"] = pd.to_datetime(ledger["entry_ts"])
    ledger["exit_ts"] = pd.to_datetime(ledger["exit_ts"])
    print(f"  {len(ledger):,} trades, {ledger['entry_ts'].min().date()} → {ledger['entry_ts'].max().date()}\n")

    stats = ledger_stats(ledger)
    print("=== Portfolio statistics (pure-R, no sizing) ===")
    print(f"  trades:          {stats['n_trades']:,} ({stats['trades_per_day']:.2f}/day)")
    print(f"  W / L / timeout: {stats['wins']} / {stats['losses']} / {stats['timeouts']}")
    print(f"  win rate:        {stats['win_rate']*100:.1f}%  "
          f"(95% CI: {stats['wr_ci_low']*100:.1f}–{stats['wr_ci_high']*100:.1f}%)")
    print(f"  mean R / trade:  {stats['mean_r']:+.4f}  (std {stats['std_r']:.3f})")
    print(f"  cum R:           {stats['cum_r']:+.1f}")
    print(f"  max DD (R):      {stats['max_dd_r']:.1f}")
    print()
    print(f"  by direction:")
    for d, s in stats["by_direction"].items():
        print(f"    {d:5s}  n={s['n']:5d}  mean_R={s['mean_r']:+.3f}  cum_R={s['cum_r']:+.1f}")
    print()

    print(f"Loading FTMO config: {FTMO_CONFIG.name}...")
    ftmo = load_ftmo_config(str(FTMO_CONFIG), phase="step1")
    print(f"  Step 1: balance={ftmo.initial_balance}, target={ftmo.profit_target_pct*100:.0f}%, "
          f"daily DD={ftmo.daily_loss_pct*100:.0f}%, max DD={ftmo.max_loss_pct*100:.0f}%, "
          f"max_days={ftmo.max_trading_days or 'unlimited'}\n")

    print(f"=== FTMO Step 1 pass rate by sizing × intra-trade model "
          f"({N_STARTS} random starts each) ===")
    sweep_out: dict[str, dict] = {}
    for sizing in SIZING_SWEEP:
        flag = "  <-- DEPLOYED" if abs(sizing - DEPLOYED_SIZING) < 1e-9 else ""
        print(f"\nSizing {sizing*100:.2f}% per trade{flag}:")
        sim_out = run_sim(ledger, ftmo, sizing)
        sweep_out[f"{sizing:.4f}"] = sim_out
        print(fmt_cohort("realistic   ", sim_out["realistic"]))
        print(fmt_cohort("conservative", sim_out["conservative"]))
        # DD percentiles for the deployed sizing
        for model in ("realistic", "conservative"):
            c = sim_out[model]
            if "max_dd_pct_p50" in c:
                print(f"    {model:12s} max_DD% p50={c['max_dd_pct_p50']*100:.1f}%  "
                      f"p95={c['max_dd_pct_p95']*100:.1f}%")

    out = {
        "ledger_path": str(LEDGER_PATH),
        "ftmo_config": str(FTMO_CONFIG),
        "n_starts": N_STARTS,
        "deployed_sizing": DEPLOYED_SIZING,
        "ledger_stats": stats,
        "sweep": sweep_out,
    }
    RESULTS_PATH.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
