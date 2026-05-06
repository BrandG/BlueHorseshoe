"""ADX>T filter applied to Donchian and SuperTrend triggers (v2 methodology).

Question: does an ADX>T gate rescue the static-channel trend-followers
(Donchian, SuperTrend) that went NULL standalone? The hypothesis is that
their failures came from firing in non-trending regimes; an ADX gate should
filter those out.

For each Donchian / SuperTrend trigger event from the prior v2 sweeps, check
ADX(period)[i] > T and keep the trigger only if true. Re-run the v2 walk-
forward + spread test with the filter applied.

Param grid (added by this filter test, on top of the host's grid):
  adx_period:    14
  adx_threshold: 20, 25, 30

Tested on: --entry={mid,limit,stop} for both hosts.

Output: research/_v2_rerun/adx_filter/{donchian,supertrend}_{entry}_T{T}_walkforward.csv
        and walkforward_spread.csv if any survivors.
"""
from __future__ import annotations

import argparse
import sys
import os
import time

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/research/_v2_rerun")
sys.path.insert(0, "/root/BlueHorseshoe/src")

from _lib import (
    PAIRS_FULL, GRANULARITY, MAX_HOLD, TRAIN_FRAC, LIMIT_FILL_WINDOW,
    sim_long_mid, sim_short_mid, sim_long_spread, sim_short_spread,
    sim_long_limit, sim_short_limit, sim_long_limit_spread, sim_short_limit_spread,
    sim_long_stop, sim_short_stop, sim_long_stop_spread, sim_short_stop_spread,
    expectancy_split, survivor_gate_walkforward,
)
from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import ohlc_mid, donchian, supertrend, adx

# Reuse Donchian + SuperTrend trigger functions
from run_donchian_v2 import (
    find_fresh_long as donchian_long,
    find_fresh_short as donchian_short,
    PERIODS as DONCHIAN_PERIODS,
    CONFIRMS as DONCHIAN_CONFIRMS,
)
from run_supertrend_v2 import (
    find_fresh_long as supertrend_flip_long,
    find_fresh_short as supertrend_flip_short,
    PERIODS as ST_PERIODS,
    MULTIPLIERS as ST_MULTIPLIERS,
)


ADX_PERIOD = 14
ADX_THRESHOLDS = [20, 25, 30]


def apply_adx_filter(triggers, adx_arr, threshold):
    """Keep only triggers where ADX[i] > threshold."""
    if len(triggers) == 0:
        return triggers
    keep = adx_arr[triggers] > threshold
    keep &= ~np.isnan(adx_arr[triggers])
    return triggers[keep]


def get_sims(entry_mode):
    if entry_mode == "limit":
        return sim_long_limit, sim_short_limit
    if entry_mode == "stop":
        return sim_long_stop, sim_short_stop
    return sim_long_mid, sim_short_mid


def get_spread_sims_long(entry_mode):
    if entry_mode == "limit":
        return lambda ca, hb, lb, cb, ha, i: sim_long_limit_spread(ca, hb, lb, cb, lb, i, MAX_HOLD)
    if entry_mode == "stop":
        return lambda ca, hb, lb, cb, ha, i: sim_long_stop_spread(ca, hb, lb, cb, ha, ha, i, MAX_HOLD)
    return lambda ca, hb, lb, cb, ha, i: sim_long_spread(ca, hb, lb, cb, i, MAX_HOLD)


def get_spread_sims_short(entry_mode):
    if entry_mode == "limit":
        return lambda cb, ha, la, ca, lb, i: sim_short_limit_spread(cb, ha, la, ca, ha, i, MAX_HOLD)
    if entry_mode == "stop":
        return lambda cb, ha, la, ca, lb, i: sim_short_stop_spread(cb, ha, la, ca, lb, lb, i, MAX_HOLD)
    return lambda cb, ha, la, ca, lb, i: sim_short_spread(cb, ha, la, ca, i, MAX_HOLD)


def walkforward_donchian(pair, threshold, entry_mode):
    store = FxStore()
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return []
    mid = ohlc_mid(raw)
    m_close = mid["close"].to_numpy(dtype=float)
    m_high = mid["high"].to_numpy(dtype=float)
    m_low = mid["low"].to_numpy(dtype=float)
    adx_arr = adx(mid, period=ADX_PERIOD)["adx"].to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()
    long_sim, short_sim = get_sims(entry_mode)

    rows = []
    for period in DONCHIAN_PERIODS:
        ch = donchian(mid, period=period)
        upper = ch["upper"].to_numpy(dtype=float)
        lower = ch["lower"].to_numpy(dtype=float)
        for confirm in DONCHIAN_CONFIRMS:
            for direction in ["long", "short"]:
                if direction == "long":
                    raw_triggers = donchian_long(m_close, upper, int(confirm))
                    sim = long_sim
                else:
                    raw_triggers = donchian_short(m_close, lower, int(confirm))
                    sim = short_sim
                triggers = apply_adx_filter(raw_triggers, adx_arr, threshold)
                rs = []
                for i in triggers:
                    r, _ = sim(m_close, m_high, m_low, int(i), MAX_HOLD)
                    if r is None:
                        continue
                    rs.append((pd.Timestamp(ts[i]), r))
                s = expectancy_split(rs)
                s.update({
                    "pair": pair, "period": period, "confirm": confirm,
                    "direction": direction, "total_n": len(rs),
                    "raw_n": len(raw_triggers),
                    "filtered_n": len(triggers),
                })
                rows.append(s)
    return rows


def walkforward_supertrend(pair, threshold, entry_mode):
    store = FxStore()
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return []
    mid = ohlc_mid(raw)
    m_close = mid["close"].to_numpy(dtype=float)
    m_high = mid["high"].to_numpy(dtype=float)
    m_low = mid["low"].to_numpy(dtype=float)
    adx_arr = adx(mid, period=ADX_PERIOD)["adx"].to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()
    long_sim, short_sim = get_sims(entry_mode)

    rows = []
    for period in ST_PERIODS:
        for mult in ST_MULTIPLIERS:
            st = supertrend(mid, period=period, multiplier=mult)
            dir_arr = st["direction"].to_numpy(dtype=np.int8)
            for direction in ["long", "short"]:
                if direction == "long":
                    raw_triggers = supertrend_flip_long(dir_arr)
                    sim = long_sim
                else:
                    raw_triggers = supertrend_flip_short(dir_arr)
                    sim = short_sim
                triggers = apply_adx_filter(raw_triggers, adx_arr, threshold)
                rs = []
                for i in triggers:
                    r, _ = sim(m_close, m_high, m_low, int(i), MAX_HOLD)
                    if r is None:
                        continue
                    rs.append((pd.Timestamp(ts[i]), r))
                s = expectancy_split(rs)
                s.update({
                    "pair": pair, "period": period, "multiplier": mult,
                    "direction": direction, "total_n": len(rs),
                    "raw_n": len(raw_triggers),
                    "filtered_n": len(triggers),
                })
                rows.append(s)
    return rows


def run_host(host, threshold, entry_mode, out_dir):
    suffix = "" if entry_mode == "mid" else f"_{entry_mode}"
    print(f"\n=== {host} v2 + ADX>{threshold} filter (entry={entry_mode}) ===", flush=True)
    all_rows = []
    t0 = time.time()
    for p_idx, pair in enumerate(PAIRS_FULL, 1):
        rows = (walkforward_donchian(pair, threshold, entry_mode) if host == "donchian"
                else walkforward_supertrend(pair, threshold, entry_mode))
        all_rows.extend(rows)
        if p_idx % 10 == 0 or p_idx == len(PAIRS_FULL):
            print(f"  [{p_idx}/{len(PAIRS_FULL)}] ({time.time()-t0:.1f}s)", flush=True)
    wf_df = pd.DataFrame(all_rows)
    out_path = f"{out_dir}/{host}_T{threshold}_walkforward{suffix}.csv"
    wf_df.to_csv(out_path, index=False)
    survivors = survivor_gate_walkforward(wf_df)
    avg_keep = (
        wf_df["filtered_n"].sum() / wf_df["raw_n"].sum() if wf_df["raw_n"].sum() else float("nan")
    )
    print(f"  walk-forward: {len(survivors)}/{len(wf_df)} survivors  "
          f"(filter kept {avg_keep*100:.1f}% of raw triggers on avg)", flush=True)
    return wf_df, survivors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry", choices=["mid", "limit", "stop"], default="mid")
    parser.add_argument("--threshold", type=int, default=None,
                        help="ADX threshold; default = sweep [20,25,30]")
    parser.add_argument("--host", choices=["donchian", "supertrend", "both"], default="both")
    args = parser.parse_args()
    entry_mode = args.entry
    thresholds = [args.threshold] if args.threshold else ADX_THRESHOLDS
    hosts = ["donchian", "supertrend"] if args.host == "both" else [args.host]

    out_dir = "/root/BlueHorseshoe/research/_v2_rerun/adx_filter"
    os.makedirs(out_dir, exist_ok=True)

    summary = []
    for host in hosts:
        for t in thresholds:
            wf_df, survivors = run_host(host, t, entry_mode, out_dir)
            summary.append({
                "host": host, "threshold": t, "entry": entry_mode,
                "n_cells": len(wf_df), "n_survivors": len(survivors),
            })

    print("\n=== SUMMARY ===", flush=True)
    for s in summary:
        print(f"  {s['host']:<10} ADX>{s['threshold']:<3} entry={s['entry']:<6} "
              f"survivors={s['n_survivors']}/{s['n_cells']}", flush=True)


if __name__ == "__main__":
    main()
