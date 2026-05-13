"""Probability of hitting the $11K goal under different daily targets and TPs.

Approach: replay the historical 22,139 fires in chronological order under a
realistic concurrency cap (max 10 simultaneous positions), at each TP
candidate. Then for every possible start date, ask:

  - days to +20R (= $1000 at 0.5% risk = $50/R)
  - probability of reaching +20R within H days for H ∈ {10, 20, 30, 60, 90}
  - probability of touching -20R (FTMO 10% max DD blow-up at 0.5% per R)
    or -10R (5% soft-DD threshold) before reaching +20R

This is what actually matters: not expectancy, not even throughput, but
P(hit goal before blow-up) and median time-to-goal.
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from pathlib import Path

IN_CSV = Path("/root/BlueHorseshoe/research/mfe_tp_sweep/per_trade.csv")
OUT_DIR = Path("/root/BlueHorseshoe/research/mfe_tp_sweep")

MAX_POSITIONS = 10
RISK_PCT = 0.005  # 0.5% of $10K = $50 per R
START_BAL = 10_000
GOAL_R = 20.0    # +$1000 = +20R at $50/R
SOFT_DD_R = -10.0  # -$500 / 5% soft warning
HARD_DD_R = -20.0  # -$1000 / 10% FTMO blow-up

TP_GRID = [0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.5]
HORIZONS_DAYS = [5, 10, 20, 30, 60, 90, 180]


def simulate_at_tp(trades: pd.DataFrame, tp_R: float) -> pd.DataFrame:
    """Replay fires in entry order, cap concurrency, return daily R series."""
    r_col = f"r_tp{tp_R}"
    bars_col = f"bars_tp{tp_R}"
    # bars_to_exit in H4 bars; entry_ts is signal close. Exit ts = entry + bars * 4h.
    trades = trades.sort_values("entry_ts").reset_index(drop=True).copy()
    trades["exit_ts"] = trades["entry_ts"] + pd.to_timedelta(trades[bars_col] * 4, unit="h")
    trades["r"] = trades[r_col]

    # Concurrency cap: skip a fire if we'd exceed MAX_POSITIONS at its entry_ts
    open_until: list[pd.Timestamp] = []
    kept_idx = []
    for i, row in trades.iterrows():
        # Drop expired
        open_until = [t for t in open_until if t > row["entry_ts"]]
        if len(open_until) >= MAX_POSITIONS:
            continue
        open_until.append(row["exit_ts"])
        kept_idx.append(i)

    kept = trades.loc[kept_idx, ["entry_ts", "exit_ts", "r"]].copy()

    # Daily realized R (use exit_ts so PnL hits when trade actually closes)
    kept["exit_day"] = kept["exit_ts"].dt.normalize()
    daily_r = kept.groupby("exit_day")["r"].sum().sort_index()

    # Build a continuous date index over the trading sample
    if daily_r.empty:
        return pd.DataFrame()
    idx = pd.date_range(daily_r.index.min(), daily_r.index.max(), freq="D")
    daily_r = daily_r.reindex(idx, fill_value=0.0)
    daily_r.index.name = "day"
    return daily_r.to_frame(name="r")


def path_stats(daily_r: pd.DataFrame, goal_R: float, horizons: list[int]) -> dict:
    """For each possible start day, compute path outcomes."""
    r = daily_r["r"].to_numpy()
    n = len(r)
    cum = np.cumsum(r)
    days_to_goal = []
    pct_reach = {h: 0 for h in horizons}
    blow_soft = 0
    blow_hard = 0
    blow_hard_before_goal = 0
    total_starts = 0

    for s in range(n - max(horizons)):
        rel = cum[s:] - cum[s] if s > 0 else cum.copy()
        # rel[0] is at end of day s (= 0 baseline). We want path from start.
        # Use rel[i] = cumulative R from day s+1 .. s+i+1
        rel_path = rel  # cumulative from start s
        total_starts += 1

        # First day reaching goal
        ge_goal = np.where(rel_path >= goal_R)[0]
        # First day breaching hard DD
        le_hard = np.where(rel_path <= HARD_DD_R)[0]
        le_soft = np.where(rel_path <= SOFT_DD_R)[0]

        first_goal = ge_goal[0] if len(ge_goal) else None
        first_hard = le_hard[0] if len(le_hard) else None
        first_soft = le_soft[0] if len(le_soft) else None

        if first_goal is not None:
            days_to_goal.append(first_goal + 1)  # +1 because day index 0 = 1 day in
            for h in horizons:
                if first_goal < h:
                    pct_reach[h] += 1
            if first_hard is not None and first_hard < first_goal:
                blow_hard_before_goal += 1
        if first_hard is not None:
            blow_hard += 1
        if first_soft is not None:
            blow_soft += 1

    return {
        "starts": total_starts,
        "median_days_to_goal": float(np.median(days_to_goal)) if days_to_goal else None,
        "p10_days_to_goal": float(np.percentile(days_to_goal, 10)) if days_to_goal else None,
        "p90_days_to_goal": float(np.percentile(days_to_goal, 90)) if days_to_goal else None,
        **{f"p_reach_{h}d": pct_reach[h] / total_starts for h in horizons},
        "p_hard_dd_anytime": blow_hard / total_starts,
        "p_hard_dd_before_goal": blow_hard_before_goal / total_starts,
    }


def main():
    df = pd.read_csv(IN_CSV, parse_dates=["entry_ts", "signal_ts"])

    # Slice by regime: full sample + last 18 months
    full = df
    cutoff = df["entry_ts"].max() - pd.Timedelta(days=540)
    recent = df[df["entry_ts"] >= cutoff].copy()

    print(f"Full sample: {len(full):,} trades over {full['entry_ts'].min().date()}"
          f" .. {full['entry_ts'].max().date()}")
    print(f"Recent: {len(recent):,} trades, last 18 months\n")

    for label, slice_df in [("FULL SAMPLE", full), ("LAST 18 MONTHS", recent)]:
        print(f"\n{'='*70}\n{label}\n{'='*70}")
        print(f"{'TP':>5} {'med_days':>9} {'p10':>5} {'p90':>5} "
              f"{'p10d':>5} {'p20d':>5} {'p30d':>5} {'p60d':>5} {'p90d':>5} "
              f"{'p_hard':>7} {'p_blow_first':>12}")
        for tp in TP_GRID:
            dr = simulate_at_tp(slice_df, tp)
            if dr.empty:
                continue
            s = path_stats(dr, GOAL_R, HORIZONS_DAYS)
            md = f"{s['median_days_to_goal']:>9.0f}" if s['median_days_to_goal'] else "      n/a"
            p10 = f"{s['p10_days_to_goal']:>5.0f}" if s['p10_days_to_goal'] else "  n/a"
            p90 = f"{s['p90_days_to_goal']:>5.0f}" if s['p90_days_to_goal'] else "  n/a"
            print(f"{tp:>5.2f} {md} {p10} {p90} "
                  f"{s['p_reach_10d']:>5.1%} {s['p_reach_20d']:>5.1%} "
                  f"{s['p_reach_30d']:>5.1%} {s['p_reach_60d']:>5.1%} "
                  f"{s['p_reach_90d']:>5.1%} "
                  f"{s['p_hard_dd_anytime']:>7.1%} {s['p_hard_dd_before_goal']:>12.1%}")
        print("\n  med_days     = median days from random start to reach +$1000 (+20R)")
        print("  p10/p90      = 10th/90th percentile days to goal")
        print("  pHd          = P(reaching +$1000 within H days)")
        print("  p_hard       = P(touching -$1000 hard DD at any point in next 180d)")
        print("  p_blow_first = P(hard DD before goal | random start)")


if __name__ == "__main__":
    main()
