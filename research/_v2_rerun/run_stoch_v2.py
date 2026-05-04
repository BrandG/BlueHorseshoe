"""Stoch v1 rerun under v2 methodology — expectancy gate, mean R tracking,
full 40-pair universe walk-forward + spread + portfolio.
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/research/_v2_rerun")
sys.path.insert(0, "/root/BlueHorseshoe/src")

from _lib import (
    PAIRS_FULL, GRANULARITY, MAX_HOLD, TP_PCT, STOP_PCT, TRAIN_FRAC, LIMIT_FILL_WINDOW,
    sim_long_mid, sim_short_mid, sim_long_spread, sim_short_spread,
    sim_long_limit, sim_short_limit, sim_long_limit_spread, sim_short_limit_spread,
    expectancy_split, survivor_gate_walkforward, select_production_cells,
    portfolio_stats,
)
from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import ohlc_mid, stochastic


K_PERIODS = [5, 9, 14, 21]
D_PERIODS = [3]
THRESHOLDS = [15, 20, 25, 30]
RECOVERY_BARS = [1, 2, 3, 4]
DIRECTIONS = ["long", "short"]


def find_fresh_long(k_arr, threshold, recovery):
    n = len(k_arr)
    if n < recovery + 1:
        return np.array([], dtype=int)
    diffs_pos = np.zeros(n, dtype=bool)
    diffs_pos[1:] = k_arr[1:] > k_arr[:-1]
    rising = np.zeros(n, dtype=bool)
    for i in range(recovery, n):
        rising[i] = bool(np.all(diffs_pos[i - recovery + 1: i + 1]))
    base = np.full(n, np.nan)
    base[recovery:] = k_arr[: n - recovery]
    valid = ~np.isnan(base) & ~np.isnan(k_arr)
    cond = valid & rising & (base < threshold)
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def find_fresh_short(k_arr, threshold, recovery):
    n = len(k_arr)
    if n < recovery + 1:
        return np.array([], dtype=int)
    diffs_neg = np.zeros(n, dtype=bool)
    diffs_neg[1:] = k_arr[1:] < k_arr[:-1]
    falling = np.zeros(n, dtype=bool)
    for i in range(recovery, n):
        falling[i] = bool(np.all(diffs_neg[i - recovery + 1: i + 1]))
    base = np.full(n, np.nan)
    base[recovery:] = k_arr[: n - recovery]
    valid = ~np.isnan(base) & ~np.isnan(k_arr)
    upper = 100.0 - threshold
    cond = valid & falling & (base > upper)
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def walkforward_pair(pair, entry_mode="mid"):
    store = FxStore()
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return []
    mid = ohlc_mid(raw)
    m_close = mid["close"].to_numpy(dtype=float)
    m_high = mid["high"].to_numpy(dtype=float)
    m_low = mid["low"].to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()

    if entry_mode == "limit":
        long_sim, short_sim = sim_long_limit, sim_short_limit
    else:
        long_sim, short_sim = sim_long_mid, sim_short_mid

    rows = []
    for k_period in K_PERIODS:
        for d_period in D_PERIODS:
            stoch = stochastic(mid, k_period=k_period, d_period=d_period)
            k_arr = stoch["k"].to_numpy(dtype=float)
            for direction in DIRECTIONS:
                find = find_fresh_long if direction == "long" else find_fresh_short
                sim = long_sim if direction == "long" else short_sim
                for thr in THRESHOLDS:
                    for rec in RECOVERY_BARS:
                        triggers = find(k_arr, float(thr), int(rec))
                        rs = []
                        for i in triggers:
                            r, _ = sim(m_close, m_high, m_low, int(i), MAX_HOLD)
                            if r is None:
                                continue
                            rs.append((pd.Timestamp(ts[i]), r))
                        s = expectancy_split(rs)
                        s.update({
                            "pair": pair, "k_period": k_period, "d_period": d_period,
                            "threshold": thr, "recovery": rec, "direction": direction,
                            "total_n": len(rs),
                        })
                        rows.append(s)
    return rows


def spread_test_pair(pair, period, d_period, threshold, recovery, direction, entry_mode="mid"):
    store = FxStore()
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return None
    mid = ohlc_mid(raw)
    stoch = stochastic(mid, k_period=period, d_period=d_period)
    k_arr = stoch["k"].to_numpy(dtype=float)
    m_close = mid["close"].to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()
    ca = raw["close_ask"].to_numpy(dtype=float)
    ha = raw["high_ask"].to_numpy(dtype=float)
    la = raw["low_ask"].to_numpy(dtype=float)
    cb = raw["close_bid"].to_numpy(dtype=float)
    hb = raw["high_bid"].to_numpy(dtype=float)
    lb = raw["low_bid"].to_numpy(dtype=float)

    if direction == "long":
        triggers = find_fresh_long(k_arr, float(threshold), int(recovery))
    else:
        triggers = find_fresh_short(k_arr, float(threshold), int(recovery))
    rs = []
    for i in triggers:
        if entry_mode == "limit":
            if direction == "long":
                r, _ = sim_long_limit_spread(ca, hb, lb, cb, lb, int(i), MAX_HOLD)
            else:
                r, _ = sim_short_limit_spread(cb, ha, la, ca, ha, int(i), MAX_HOLD)
        else:
            if direction == "long":
                r, _ = sim_long_spread(ca, hb, lb, cb, int(i), MAX_HOLD)
            else:
                r, _ = sim_short_spread(cb, ha, la, ca, int(i), MAX_HOLD)
        if r is None:
            continue
        rs.append((pd.Timestamp(ts[i]), r))
    s = expectancy_split(rs)
    s.update({
        "pair": pair, "k_period": period, "d_period": d_period,
        "threshold": threshold, "recovery": recovery, "direction": direction,
        "total_n": len(rs),
    })
    return s


def collect_trades(pair, period, d_period, threshold, recovery, direction, entry_mode="mid"):
    store = FxStore()
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return []
    mid = ohlc_mid(raw)
    stoch = stochastic(mid, k_period=period, d_period=d_period)
    k_arr = stoch["k"].to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()
    ca = raw["close_ask"].to_numpy(dtype=float)
    ha = raw["high_ask"].to_numpy(dtype=float)
    la = raw["low_ask"].to_numpy(dtype=float)
    cb = raw["close_bid"].to_numpy(dtype=float)
    hb = raw["high_bid"].to_numpy(dtype=float)
    lb = raw["low_bid"].to_numpy(dtype=float)

    if direction == "long":
        triggers = find_fresh_long(k_arr, float(threshold), int(recovery))
    else:
        triggers = find_fresh_short(k_arr, float(threshold), int(recovery))
    trades = []
    for i in triggers:
        i = int(i)
        if entry_mode == "limit":
            if direction == "long":
                r, exit_idx = sim_long_limit_spread(ca, hb, lb, cb, lb, i, MAX_HOLD)
            else:
                r, exit_idx = sim_short_limit_spread(cb, ha, la, ca, ha, i, MAX_HOLD)
            entry_idx = i + LIMIT_FILL_WINDOW
        else:
            if direction == "long":
                r, exit_idx = sim_long_spread(ca, hb, lb, cb, i, MAX_HOLD)
            else:
                r, exit_idx = sim_short_spread(cb, ha, la, ca, i, MAX_HOLD)
            entry_idx = i
        if r is None:
            continue
        trades.append({
            "pair": pair,
            "entry_ts": pd.Timestamp(ts[entry_idx]),
            "exit_ts": pd.Timestamp(ts[exit_idx]),
            "r": r,
        })
    return trades


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry", choices=["mid", "limit"], default="mid",
                        help="Entry mechanic: mid=market at signal close, "
                             "limit=limit at signal-bar low/high, fill window 1 bar")
    args = parser.parse_args()
    entry_mode = args.entry
    suffix = "_limit" if entry_mode == "limit" else ""

    out_dir = "/root/BlueHorseshoe/research/_v2_rerun/stoch"
    import os
    os.makedirs(out_dir, exist_ok=True)

    print(f"=== STOCH v2 walk-forward (entry={entry_mode}) ===\n", flush=True)
    all_rows = []
    t0 = time.time()
    for p_idx, pair in enumerate(PAIRS_FULL, 1):
        rows = walkforward_pair(pair, entry_mode=entry_mode)
        all_rows.extend(rows)
        print(f"  [{p_idx}/{len(PAIRS_FULL)}] {pair}  ({time.time()-t0:.1f}s)", flush=True)
    wf_df = pd.DataFrame(all_rows)
    wf_df.to_csv(f"{out_dir}/walkforward{suffix}.csv", index=False)
    print(f"  Wrote {len(wf_df)} cells to walkforward{suffix}.csv\n", flush=True)

    survivors = survivor_gate_walkforward(wf_df)
    print(f"Mid walk-forward survivors: {len(survivors)}/{len(wf_df)}\n", flush=True)

    print(f"=== STOCH v2 spread test on survivors (entry={entry_mode}) ===\n", flush=True)
    spread_rows = []
    for idx, (_, r) in enumerate(survivors.iterrows(), 1):
        out = spread_test_pair(r["pair"], int(r["k_period"]), int(r["d_period"]),
                                int(r["threshold"]), int(r["recovery"]), r["direction"],
                                entry_mode=entry_mode)
        if out is not None:
            spread_rows.append(out)
        if idx % 20 == 0 or idx == len(survivors):
            print(f"  [{idx}/{len(survivors)}]", flush=True)
    spread_df = pd.DataFrame(spread_rows)
    spread_df.to_csv(f"{out_dir}/walkforward_spread{suffix}.csv", index=False)

    robust = survivor_gate_walkforward(spread_df)
    print(f"\nSpread-robust cells: {len(robust)}/{len(spread_df)}", flush=True)

    if robust.empty:
        return

    print("\n=== Production cell selection ===\n", flush=True)
    selected = select_production_cells(robust,
        ["pair", "k_period", "d_period", "threshold", "recovery", "direction"])
    for s in selected:
        print(f"  {s['pair']:<10} kP={int(s['k_period'])} thr={int(s['threshold'])} "
              f"rec={int(s['recovery'])} {s['direction']:<5}  "
              f"te n={int(s['te_n'])} mean_R={s['te_mean_r']:+.3f}", flush=True)

    print("\n=== Building portfolio ===", flush=True)
    all_trades = []
    for s in selected:
        trades = collect_trades(s["pair"], int(s["k_period"]), int(s["d_period"]),
                                int(s["threshold"]), int(s["recovery"]), s["direction"],
                                entry_mode=entry_mode)
        all_trades.extend(trades)
    df_t = pd.DataFrame(all_trades).sort_values("entry_ts").reset_index(drop=True)
    print(f"Total trades: {len(df_t)}", flush=True)
    cut = int(len(df_t) * TRAIN_FRAC)
    df_tr = df_t.iloc[:cut].copy()
    df_te = df_t.iloc[cut:].copy()
    print(f"Train/test boundary: {df_te['entry_ts'].iloc[0].date()}\n", flush=True)
    print("=== Portfolio stats ===", flush=True)
    portfolio_stats(df_tr, "TRAIN")
    portfolio_stats(df_te, "TEST")
    portfolio_stats(df_t, "FULL")

    print("\n=== Per-pair (test) ===", flush=True)
    for pair in sorted(df_te["pair"].unique()):
        sub = df_te[df_te["pair"] == pair]
        rs = sub["r"].to_numpy()
        wins = int((rs >= 1.0 - 1e-9).sum())
        losses = int((rs <= -1.0 + 1e-9).sum())
        wr = wins / max(wins + losses, 1)
        print(f"  {pair:<10} n={len(sub)} WR={wr*100:.1f}% "
              f"mean_R={rs.mean():+.3f} cum_R={rs.sum():+.1f}", flush=True)

    df_t.to_csv(f"{out_dir}/portfolio_trades{suffix}.csv", index=False)


if __name__ == "__main__":
    main()
