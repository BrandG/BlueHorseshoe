"""How often are concurrent slots actually filled?

For each TP in {0.5, 0.7, 1.0}R, replay the historical fires under the
max-10-positions cap, then sample the open-position count every H4 bar.
Report:

  - distribution of open slots (histogram)
  - mean / median / p25 / p75 / p95 occupancy
  - % of time at 0 slots ("system idle")
  - % of time at >=8 slots ("cap binding")
  - fires-rejected ratio (how often did a fire arrive when 10 were already open?)

Separately reports full sample and last 18 months.
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

IN_CSV = Path("/root/BlueHorseshoe/research/mfe_tp_sweep/per_trade.csv")
MAX_POSITIONS = 10
TP_GRID = [0.5, 0.7, 1.0]


def replay_with_cap(trades: pd.DataFrame, tp_R: float):
    bars_col = f"bars_tp{tp_R}"
    trades = trades.sort_values("entry_ts").reset_index(drop=True).copy()
    trades["exit_ts"] = trades["entry_ts"] + pd.to_timedelta(trades[bars_col] * 4, unit="h")

    open_until: list[pd.Timestamp] = []
    kept_idx = []
    rejected = 0
    for i, row in trades.iterrows():
        open_until = [t for t in open_until if t > row["entry_ts"]]
        if len(open_until) >= MAX_POSITIONS:
            rejected += 1
            continue
        open_until.append(row["exit_ts"])
        kept_idx.append(i)

    kept = trades.loc[kept_idx, ["entry_ts", "exit_ts"]].copy()
    return kept, rejected, len(trades)


def occupancy_over_time(kept: pd.DataFrame, freq: str = "4h") -> pd.Series:
    """Count open positions on a regular grid."""
    if kept.empty:
        return pd.Series(dtype=int)
    start = kept["entry_ts"].min().floor(freq)
    end = kept["exit_ts"].max().ceil(freq)
    grid = pd.date_range(start, end, freq=freq)
    # For each grid timestamp, count rows where entry_ts <= t < exit_ts.
    # Vectorize via stick events.
    open_events = kept["entry_ts"].sort_values().to_numpy()
    close_events = kept["exit_ts"].sort_values().to_numpy()
    grid_np = grid.to_numpy()
    n_open = np.searchsorted(open_events, grid_np, side="right")
    n_closed = np.searchsorted(close_events, grid_np, side="right")
    return pd.Series(n_open - n_closed, index=grid)


def report(slice_df: pd.DataFrame, label: str):
    print(f"\n{'='*70}\n{label}  ({len(slice_df):,} raw fires)\n{'='*70}")
    print(f"{'TP':>4} {'kept':>5} {'rej':>5} {'rej%':>5}  "
          f"{'idle%':>6} {'mean':>5} {'p50':>4} {'p75':>4} {'p90':>4} "
          f"{'p95':>4} {'max':>4} {'>=8%':>6}")
    for tp in TP_GRID:
        kept, rejected, total = replay_with_cap(slice_df, tp)
        occ = occupancy_over_time(kept)
        if occ.empty:
            print(f"{tp:>4.1f}  (no data)")
            continue
        rej_pct = rejected / total if total else 0
        idle_pct = (occ == 0).mean()
        cap_pct = (occ >= 8).mean()
        print(f"{tp:>4.1f} {len(kept):>5} {rejected:>5} {rej_pct:>5.1%}  "
              f"{idle_pct:>6.1%} {occ.mean():>5.2f} {int(occ.median()):>4} "
              f"{int(np.percentile(occ,75)):>4} {int(np.percentile(occ,90)):>4} "
              f"{int(np.percentile(occ,95)):>4} {int(occ.max()):>4} "
              f"{cap_pct:>6.1%}")
    print("\n  idle%  = % of H4 bars with 0 open positions")
    print("  mean   = average concurrent open positions")
    print("  >=8%   = % of bars where 8+ slots filled (cap nearly binding)")
    print("  rej%   = % of fires rejected because cap was full")


def histogram(slice_df: pd.DataFrame, label: str, tp: float = 0.7):
    kept, rejected, total = replay_with_cap(slice_df, tp)
    occ = occupancy_over_time(kept)
    print(f"\n--- Occupancy distribution at TP={tp}R, {label} ---")
    for k in range(MAX_POSITIONS + 1):
        pct = (occ == k).mean()
        bar = "#" * int(pct * 100)
        print(f"  {k} slots: {pct:>6.1%}  {bar}")


def main():
    df = pd.read_csv(IN_CSV, parse_dates=["entry_ts"])
    full = df
    cutoff = df["entry_ts"].max() - pd.Timedelta(days=540)
    recent = df[df["entry_ts"] >= cutoff].copy()

    report(full, "FULL SAMPLE 2016-2026")
    report(recent, "LAST 18 MONTHS")

    histogram(full, "FULL SAMPLE", tp=0.7)
    histogram(recent, "LAST 18 MONTHS", tp=0.7)


if __name__ == "__main__":
    main()
