"""MACD standalone trigger v1 under v2 methodology.

Trigger families (mirror Phase 0):
  signal_cross — long: macd[i] > signal[i] AND macd[i-1] <= signal[i-1]
                 short: mirror.
  zero_cross   — long: macd[i] > 0 AND macd[i-1] <= 0
                 short: mirror.

This is a TREND-FOLLOWING / momentum signal — same shape family as Donchian
and SuperTrend, both of which were NULL under v2 across mid/limit/stop entry
modes. MACD's prior Phase 0 trigger sweep produced a wash result (mean WR
50.18% across 2,400 cells), establishing its role as a filter rather than a
standalone strategy. This v2 re-test puts MACD on the same methodology footing
as the other indicators (per-trade R, expectancy CI gate, fixed 1%/1% RR,
walk-forward 70/30, spread test, optional limit/stop entry).

Param grid:
  (fast, slow): (6,13), (8,17), (12,26), (18,39), (24,52)
  signal:       5, 9, 13
  trigger:      signal_cross, zero_cross
  direction:    long, short
  pair:         40-pair OANDA universe (PAIRS_FULL)

Per pair: 5 × 3 × 2 × 2 = 60 cells. × 40 pairs = 2,400 cells per --entry mode.
"""
from __future__ import annotations

import argparse
import sys
import time
import os

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/research/_v2_rerun")
sys.path.insert(0, "/root/BlueHorseshoe/src")

from _lib import (
    PAIRS_FULL, GRANULARITY, MAX_HOLD, TRAIN_FRAC, LIMIT_FILL_WINDOW,
    sim_long_mid, sim_short_mid, sim_long_spread, sim_short_spread,
    sim_long_limit, sim_short_limit, sim_long_limit_spread, sim_short_limit_spread,
    sim_long_stop, sim_short_stop, sim_long_stop_spread, sim_short_stop_spread,
    expectancy_split, survivor_gate_walkforward, select_production_cells,
    portfolio_stats,
)
from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import macd, ohlc_mid


FAST_SLOW = [(6, 13), (8, 17), (12, 26), (18, 39), (24, 52)]
SIGNAL_PERIODS = [5, 9, 13]
TRIGGERS = ["signal_cross", "zero_cross"]
DIRECTIONS = ["long", "short"]


def find_signal_cross_long(macd_arr, signal_arr):
    n = len(macd_arr)
    if n < 2:
        return np.array([], dtype=int)
    above = macd_arr > signal_arr
    fresh = above & ~np.roll(above, 1)
    fresh[0] = False
    fresh[np.isnan(macd_arr) | np.isnan(signal_arr)] = False
    return np.where(fresh)[0]


def find_signal_cross_short(macd_arr, signal_arr):
    n = len(macd_arr)
    if n < 2:
        return np.array([], dtype=int)
    below = macd_arr < signal_arr
    fresh = below & ~np.roll(below, 1)
    fresh[0] = False
    fresh[np.isnan(macd_arr) | np.isnan(signal_arr)] = False
    return np.where(fresh)[0]


def find_zero_cross_long(macd_arr):
    n = len(macd_arr)
    if n < 2:
        return np.array([], dtype=int)
    above = macd_arr > 0
    fresh = above & ~np.roll(above, 1)
    fresh[0] = False
    fresh[np.isnan(macd_arr)] = False
    return np.where(fresh)[0]


def find_zero_cross_short(macd_arr):
    n = len(macd_arr)
    if n < 2:
        return np.array([], dtype=int)
    below = macd_arr < 0
    fresh = below & ~np.roll(below, 1)
    fresh[0] = False
    fresh[np.isnan(macd_arr)] = False
    return np.where(fresh)[0]


def get_triggers(macd_arr, signal_arr, trigger, direction):
    if trigger == "signal_cross":
        return (find_signal_cross_long(macd_arr, signal_arr) if direction == "long"
                else find_signal_cross_short(macd_arr, signal_arr))
    return (find_zero_cross_long(macd_arr) if direction == "long"
            else find_zero_cross_short(macd_arr))


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
    elif entry_mode == "stop":
        long_sim, short_sim = sim_long_stop, sim_short_stop
    else:
        long_sim, short_sim = sim_long_mid, sim_short_mid

    rows = []
    for fast, slow in FAST_SLOW:
        for sig in SIGNAL_PERIODS:
            df = macd(mid, fast=fast, slow=slow, signal=sig)
            macd_arr = df["macd"].to_numpy(dtype=float)
            signal_arr = df["signal"].to_numpy(dtype=float)
            for trigger in TRIGGERS:
                for direction in DIRECTIONS:
                    triggers = get_triggers(macd_arr, signal_arr, trigger, direction)
                    sim = long_sim if direction == "long" else short_sim
                    rs = []
                    for i in triggers:
                        r, _ = sim(m_close, m_high, m_low, int(i), MAX_HOLD)
                        if r is None:
                            continue
                        rs.append((pd.Timestamp(ts[i]), r))
                    s = expectancy_split(rs)
                    s.update({
                        "pair": pair, "fast": fast, "slow": slow, "signal": sig,
                        "trigger": trigger, "direction": direction, "total_n": len(rs),
                    })
                    rows.append(s)
    return rows


def spread_test_pair(pair, fast, slow, sig, trigger, direction, entry_mode="mid"):
    store = FxStore()
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return None
    mid = ohlc_mid(raw)
    df = macd(mid, fast=int(fast), slow=int(slow), signal=int(sig))
    macd_arr = df["macd"].to_numpy(dtype=float)
    signal_arr = df["signal"].to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()
    ca = raw["close_ask"].to_numpy(dtype=float)
    ha = raw["high_ask"].to_numpy(dtype=float)
    la = raw["low_ask"].to_numpy(dtype=float)
    cb = raw["close_bid"].to_numpy(dtype=float)
    hb = raw["high_bid"].to_numpy(dtype=float)
    lb = raw["low_bid"].to_numpy(dtype=float)

    triggers = get_triggers(macd_arr, signal_arr, trigger, direction)
    rs = []
    for i in triggers:
        if entry_mode == "limit":
            if direction == "long":
                r, _ = sim_long_limit_spread(ca, hb, lb, cb, lb, int(i), MAX_HOLD)
            else:
                r, _ = sim_short_limit_spread(cb, ha, la, ca, ha, int(i), MAX_HOLD)
        elif entry_mode == "stop":
            if direction == "long":
                r, _ = sim_long_stop_spread(ca, hb, lb, cb, ha, ha, int(i), MAX_HOLD)
            else:
                r, _ = sim_short_stop_spread(cb, ha, la, ca, lb, lb, int(i), MAX_HOLD)
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
        "pair": pair, "fast": fast, "slow": slow, "signal": sig,
        "trigger": trigger, "direction": direction, "total_n": len(rs),
    })
    return s


def collect_trades(pair, fast, slow, sig, trigger, direction, entry_mode="mid"):
    store = FxStore()
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return []
    mid = ohlc_mid(raw)
    df = macd(mid, fast=int(fast), slow=int(slow), signal=int(sig))
    macd_arr = df["macd"].to_numpy(dtype=float)
    signal_arr = df["signal"].to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()
    ca = raw["close_ask"].to_numpy(dtype=float)
    ha = raw["high_ask"].to_numpy(dtype=float)
    la = raw["low_ask"].to_numpy(dtype=float)
    cb = raw["close_bid"].to_numpy(dtype=float)
    hb = raw["high_bid"].to_numpy(dtype=float)
    lb = raw["low_bid"].to_numpy(dtype=float)

    triggers = get_triggers(macd_arr, signal_arr, trigger, direction)
    trades = []
    for i in triggers:
        i = int(i)
        if entry_mode == "limit":
            if direction == "long":
                r, exit_idx = sim_long_limit_spread(ca, hb, lb, cb, lb, i, MAX_HOLD)
            else:
                r, exit_idx = sim_short_limit_spread(cb, ha, la, ca, ha, i, MAX_HOLD)
            entry_idx = i + LIMIT_FILL_WINDOW
        elif entry_mode == "stop":
            if direction == "long":
                r, exit_idx = sim_long_stop_spread(ca, hb, lb, cb, ha, ha, i, MAX_HOLD)
            else:
                r, exit_idx = sim_short_stop_spread(cb, ha, la, ca, lb, lb, i, MAX_HOLD)
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
            "pair": pair, "entry_ts": pd.Timestamp(ts[entry_idx]),
            "exit_ts": pd.Timestamp(ts[exit_idx]), "r": r,
        })
    return trades


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry", choices=["mid", "limit", "stop"], default="mid",
                        help="Entry mechanic: mid=market at signal close, "
                             "limit=limit at signal-bar low/high (mean-reversion), "
                             "stop=stop-buy at signal-bar high/low (breakout continuation), "
                             "fill window 1 bar")
    args = parser.parse_args()
    entry_mode = args.entry
    suffix = "" if entry_mode == "mid" else f"_{entry_mode}"

    out_dir = "/root/BlueHorseshoe/research/_v2_rerun/macd"
    os.makedirs(out_dir, exist_ok=True)
    print(f"=== MACD v2 walk-forward (entry={entry_mode}) ===\n", flush=True)
    all_rows = []
    t0 = time.time()
    for p_idx, pair in enumerate(PAIRS_FULL, 1):
        rows = walkforward_pair(pair, entry_mode=entry_mode)
        all_rows.extend(rows)
        print(f"  [{p_idx}/{len(PAIRS_FULL)}] {pair} ({time.time()-t0:.1f}s)", flush=True)
    wf_df = pd.DataFrame(all_rows)
    wf_df.to_csv(f"{out_dir}/walkforward{suffix}.csv", index=False)
    survivors = survivor_gate_walkforward(wf_df)
    print(f"\nMid walk-forward survivors: {len(survivors)}/{len(wf_df)}", flush=True)

    print(f"\n=== MACD v2 spread test (entry={entry_mode}) ===", flush=True)
    spread_rows = []
    for idx, (_, r) in enumerate(survivors.iterrows(), 1):
        out = spread_test_pair(r["pair"], int(r["fast"]), int(r["slow"]),
                               int(r["signal"]), r["trigger"], r["direction"],
                               entry_mode=entry_mode)
        if out is not None:
            spread_rows.append(out)
    spread_df = pd.DataFrame(spread_rows)
    spread_df.to_csv(f"{out_dir}/walkforward_spread{suffix}.csv", index=False)
    robust = survivor_gate_walkforward(spread_df)
    print(f"\nSpread-robust: {len(robust)}/{len(spread_df)}", flush=True)
    if robust.empty:
        print("\n*** MACD NULL — zero production cells. ***", flush=True)
        return

    print("\n=== Production cell selection ===", flush=True)
    selected = select_production_cells(robust, ["pair", "fast", "slow", "signal", "trigger", "direction"])
    for s in selected:
        print(f"  {s['pair']:<10} ({int(s['fast'])},{int(s['slow'])},{int(s['signal'])}) "
              f"{s['trigger']:<13} {s['direction']:<5}  "
              f"te n={int(s['te_n'])} mean_R={s['te_mean_r']:+.3f}", flush=True)

    print("\n=== Building portfolio ===", flush=True)
    all_trades = []
    for s in selected:
        trades = collect_trades(s["pair"], int(s["fast"]), int(s["slow"]),
                                int(s["signal"]), s["trigger"], s["direction"],
                                entry_mode=entry_mode)
        all_trades.extend(trades)
    df_t = pd.DataFrame(all_trades).sort_values("entry_ts").reset_index(drop=True)
    print(f"Total trades: {len(df_t)}", flush=True)
    cut = int(len(df_t) * TRAIN_FRAC)
    print("\n=== Portfolio stats ===", flush=True)
    portfolio_stats(df_t.iloc[:cut], "TRAIN")
    portfolio_stats(df_t.iloc[cut:], "TEST")
    portfolio_stats(df_t, "FULL")

    df_te = df_t.iloc[cut:]
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
