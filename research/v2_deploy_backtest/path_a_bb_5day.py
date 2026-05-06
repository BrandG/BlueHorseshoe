"""Path A: BB strategy 5-day MAX_HOLD test.

Hypothesis: a shorter max-hold (5 days = 30 H4 bars vs current 14 days = 84 bars)
trades per-trade R for trade-count, and the higher turnover lets more trades
through the live gate overlay. Net portfolio outcome could be better.

This script:
  1. Re-runs bb v2 trade collection with MAX_HOLD = 30 (5 days)
  2. Compares to the original 84-bar ledger at research/bb_execution_v1/portfolio_trades.csv
  3. Reports per-trade R, count, cum R, WR, duration distribution

If 5-day shows meaningful signal (count up, R only modestly down), expand to
all 9 strategies in a follow-up.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "research" / "bb_execution_v1"))

# Reuse the trigger + spread-aware sim helpers from the existing bb v2 module.
from portfolio_bb_v2 import (  # noqa: E402
    find_fresh_long, find_fresh_short, sim_long_spread, sim_short_spread,
    SPREAD_CSV, GRANULARITY, TRAIN_FRAC,
)
from bh_ftmo.data.fx_store import FxStore  # noqa: E402
from bh_ftmo.indicators import bollinger_bands, ohlc_mid  # noqa: E402

ORIG_LEDGER = REPO / "research" / "bb_execution_v1" / "portfolio_trades.csv"
NEW_MAX_HOLD = 30   # 5 days × 6 H4 bars per day
OLD_MAX_HOLD = 14 * 6  # 14 days (the original)


def collect_trades_with_hold(pair, period, std, depth, direction, max_hold):
    store = FxStore()
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return []

    mid = ohlc_mid(raw)
    m_close = mid["close"].to_numpy(dtype=float)
    bb = bollinger_bands(mid, period=period, n_std=std)
    lower = bb["lower"].to_numpy(dtype=float)
    upper = bb["upper"].to_numpy(dtype=float)
    bw = upper - lower
    ts = raw["timestamp"].to_numpy()
    ca = raw["close_ask"].to_numpy(dtype=float)
    ha = raw["high_ask"].to_numpy(dtype=float)
    la = raw["low_ask"].to_numpy(dtype=float)
    cb = raw["close_bid"].to_numpy(dtype=float)
    hb = raw["high_bid"].to_numpy(dtype=float)
    lb = raw["low_bid"].to_numpy(dtype=float)

    if direction == "long":
        triggers = find_fresh_long(m_close, lower, bw, depth)
    else:
        triggers = find_fresh_short(m_close, upper, bw, depth)

    trades = []
    for i in triggers:
        i = int(i)
        if direction == "long":
            r, exit_idx = sim_long_spread(ca, hb, lb, cb, i, max_hold)
        else:
            r, exit_idx = sim_short_spread(cb, ha, la, ca, i, max_hold)
        if r is None:
            continue
        trades.append({
            "pair": pair,
            "entry_ts": pd.Timestamp(ts[i]),
            "exit_ts": pd.Timestamp(ts[exit_idx]),
            "r": r,
        })
    return trades


def select_cells():
    """Same selection as portfolio_bb_v2.py main() — variant A robust + per-pair argmax(te_n)."""
    df = pd.read_csv(SPREAD_CSV)
    robust = df[(df["variant"] == "A")
                & (df["tr_ci_low_r"] > 0.0) & (df["te_ci_low_r"] > 0.0)
                & (df["tr_n"] >= 50) & (df["te_n"] >= 30)].copy()
    selected = []
    for pair in sorted(robust["pair"].unique()):
        pair_cells = robust[robust["pair"] == pair].sort_values(
            ["te_n", "te_mean_r"], ascending=[False, False])
        selected.append(pair_cells.iloc[0])
    return selected


def stats_block(label: str, df: pd.DataFrame) -> str:
    rs = df["r"].to_numpy()
    n = len(rs)
    if n == 0:
        return f"{label}: empty"
    wins = int((rs >= 1.0 - 1e-9).sum())
    losses = int((rs <= -1.0 + 1e-9).sum())
    timeouts = n - wins - losses
    wr = wins / max(wins + losses, 1)
    dur = (pd.to_datetime(df["exit_ts"]) - pd.to_datetime(df["entry_ts"])).dt.total_seconds() / 86400
    return (f"{label:30s} n={n:>5d}  W/L/T={wins}/{losses}/{timeouts}  "
            f"WR={wr*100:5.1f}%  mean_R={rs.mean():+.4f}  "
            f"cum_R={rs.sum():+8.1f}  "
            f"dur p50/p75/max={np.percentile(dur,50):.1f}/{np.percentile(dur,75):.1f}/{dur.max():.1f}d")


def main() -> int:
    selected = select_cells()
    print(f"BB v2 cells: {len(selected)} pairs")
    print(f"Original MAX_HOLD = {OLD_MAX_HOLD} bars ({OLD_MAX_HOLD/6:.0f}d)  vs  new MAX_HOLD = {NEW_MAX_HOLD} bars ({NEW_MAX_HOLD/6:.1f}d)")
    print()

    # Generate the 5-day-capped ledger
    new_trades = []
    for s in selected:
        trades = collect_trades_with_hold(
            s["pair"], int(s["period"]), float(s["std"]),
            float(s["depth"]), s["direction"], NEW_MAX_HOLD,
        )
        new_trades.extend(trades)
    new_df = pd.DataFrame(new_trades).sort_values("entry_ts").reset_index(drop=True)

    # Load the original (14-day) ledger
    orig_df = pd.read_csv(ORIG_LEDGER)
    orig_df["entry_ts"] = pd.to_datetime(orig_df["entry_ts"])
    orig_df["exit_ts"] = pd.to_datetime(orig_df["exit_ts"])

    print("=== Portfolio-level comparison ===")
    print(stats_block("ORIGINAL (14d cap)", orig_df))
    print(stats_block("PATH A   (5d cap) ", new_df))
    print()

    print("=== Per-pair comparison ===")
    print(f"{'pair':9s}  {'orig n':>7s}  {'new n':>7s}  {'Δn':>6s}  "
          f"{'orig R':>8s}  {'new R':>8s}  {'ΔR':>8s}  "
          f"{'orig cum':>9s}  {'new cum':>9s}")
    for pair in sorted(set(orig_df["pair"]) | set(new_df["pair"])):
        o = orig_df[orig_df["pair"] == pair]
        n_ = new_df[new_df["pair"] == pair]
        d_count = len(n_) - len(o)
        d_r = (n_["r"].mean() - o["r"].mean()) if len(n_) and len(o) else 0
        print(f"{pair:9s}  {len(o):>7d}  {len(n_):>7d}  {d_count:>+6d}  "
              f"{o['r'].mean():>+8.3f}  {n_['r'].mean():>+8.3f}  {d_r:>+8.3f}  "
              f"{o['r'].sum():>+9.1f}  {n_['r'].sum():>+9.1f}")

    print()
    # Decision summary
    n_orig = len(orig_df); n_new = len(new_df)
    r_orig = orig_df["r"].mean(); r_new = new_df["r"].mean()
    cum_orig = orig_df["r"].sum(); cum_new = new_df["r"].sum()
    print(f"=== Verdict ===")
    print(f"  trade count:  {n_new/n_orig*100-100:+.0f}%   ({n_orig} -> {n_new})")
    print(f"  mean R/trade: {(r_new-r_orig)/abs(r_orig)*100:+.0f}%   ({r_orig:+.4f} -> {r_new:+.4f})")
    print(f"  cum R:        {(cum_new-cum_orig)/abs(cum_orig)*100:+.0f}%   ({cum_orig:+.1f} -> {cum_new:+.1f})")
    print()
    if cum_new > cum_orig and n_new > n_orig:
        print("  → 5-day cap WINS on cum R AND volume. Strong signal for Path B.")
    elif cum_new > cum_orig:
        print("  → 5-day cap improves cum R but trade count flat. Worth Path B.")
    elif n_new >= n_orig * 1.5 and r_new > r_orig * 0.7:
        print("  → 5-day cap drops R modestly but boosts volume substantially. Path B may net out positive after gate-overlay turnover effect.")
    else:
        print("  → 5-day cap doesn't pull its weight on this indicator. Re-evaluate before Path B.")

    out_path = REPO / "research" / "v2_deploy_backtest" / "path_a_bb_5day_trades.csv"
    new_df.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
