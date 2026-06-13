"""ATR-conditional bullish/bearish momentum v1 under v2 methodology.

Two trigger families (both volatility-scaled momentum signals):

  close_breakout:
    long:  close[i] > close[i-1] + k * ATR[i-1] (fresh)
    short: close[i] < close[i-1] - k * ATR[i-1] (fresh)
    "Today's close moved more than k volatility units beyond yesterday's."

  range_expansion:
    long:  range[i] > k * mean(range, 14)[i-1] AND close[i] > open[i] (fresh, bullish bar)
    short: range[i] > k * mean(range, 14)[i-1] AND close[i] < open[i] (fresh, bearish bar)
    "Today's range is k× recent average AND we closed in the trigger direction."

Both shapes are MOMENTUM/BREAKOUT — same family that produced NULL for Donchian
and SuperTrend. The interesting question is whether ATR scaling (volatility-
adaptive thresholds) rescues the shape vs the static-channel breakouts.

Param grid:
  atr_period: 14, 20
  k:          0.5, 1.0, 1.5
  trigger:    close_breakout, range_expansion
  direction:  long, short
  pair:       40 OANDA pairs

Per pair: 2 × 3 × 2 × 2 = 24 cells. × 40 = 960 cells per --entry mode.
"""
from __future__ import annotations

import argparse
import sys
import time
import os
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from _lib import (
    PAIRS_FULL, GRANULARITY, MAX_HOLD, TRAIN_FRAC, LIMIT_FILL_WINDOW,
    sim_long_mid, sim_short_mid, sim_long_spread, sim_short_spread,
    sim_long_limit, sim_short_limit, sim_long_limit_spread, sim_short_limit_spread,
    sim_long_stop, sim_short_stop, sim_long_stop_spread, sim_short_stop_spread,
    expectancy_split, survivor_gate_walkforward, select_production_cells,
    portfolio_stats,
)
from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import ohlc_mid, atr


ATR_PERIODS = [14, 20]
K_VALUES = [0.5, 1.0, 1.5]
TRIGGERS = ["close_breakout", "range_expansion"]
DIRECTIONS = ["long", "short"]
RANGE_LOOKBACK = 14


def find_close_breakout_long(close, atr_arr, k):
    n = len(close)
    if n < 2:
        return np.array([], dtype=int)
    prev_close = np.full(n, np.nan)
    prev_close[1:] = close[:-1]
    prev_atr = np.full(n, np.nan)
    prev_atr[1:] = atr_arr[:-1]
    cond = close > (prev_close + k * prev_atr)
    cond = np.where(np.isnan(prev_close) | np.isnan(prev_atr), False, cond)
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def find_close_breakout_short(close, atr_arr, k):
    n = len(close)
    if n < 2:
        return np.array([], dtype=int)
    prev_close = np.full(n, np.nan)
    prev_close[1:] = close[:-1]
    prev_atr = np.full(n, np.nan)
    prev_atr[1:] = atr_arr[:-1]
    cond = close < (prev_close - k * prev_atr)
    cond = np.where(np.isnan(prev_close) | np.isnan(prev_atr), False, cond)
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def _mean_range(high, low, lookback):
    rng = high - low
    return pd.Series(rng).rolling(lookback, min_periods=lookback).mean().to_numpy()


def find_range_expansion_long(open_arr, high, low, close, k, lookback):
    rng = high - low
    mean_rng = _mean_range(high, low, lookback)
    prev_mean = np.full(len(close), np.nan)
    prev_mean[1:] = mean_rng[:-1]
    is_bull = close > open_arr
    cond = (rng > k * prev_mean) & is_bull
    cond = np.where(np.isnan(prev_mean), False, cond)
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def find_range_expansion_short(open_arr, high, low, close, k, lookback):
    rng = high - low
    mean_rng = _mean_range(high, low, lookback)
    prev_mean = np.full(len(close), np.nan)
    prev_mean[1:] = mean_rng[:-1]
    is_bear = close < open_arr
    cond = (rng > k * prev_mean) & is_bear
    cond = np.where(np.isnan(prev_mean), False, cond)
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def get_triggers(open_arr, high, low, close, atr_arr, k, trigger, direction):
    if trigger == "close_breakout":
        return (find_close_breakout_long(close, atr_arr, k) if direction == "long"
                else find_close_breakout_short(close, atr_arr, k))
    return (find_range_expansion_long(open_arr, high, low, close, k, RANGE_LOOKBACK) if direction == "long"
            else find_range_expansion_short(open_arr, high, low, close, k, RANGE_LOOKBACK))


def walkforward_pair(pair, entry_mode="mid"):
    store = FxStore(read_only=True)
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return []
    mid = ohlc_mid(raw)
    m_open = mid["open"].to_numpy(dtype=float)
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
    for atr_period in ATR_PERIODS:
        atr_arr = atr(mid, period=atr_period).to_numpy(dtype=float)
        for k in K_VALUES:
            for trigger in TRIGGERS:
                for direction in DIRECTIONS:
                    sim = long_sim if direction == "long" else short_sim
                    triggers = get_triggers(m_open, m_high, m_low, m_close,
                                            atr_arr, k, trigger, direction)
                    rs = []
                    for i in triggers:
                        r, _ = sim(m_close, m_high, m_low, int(i), MAX_HOLD)
                        if r is None:
                            continue
                        rs.append((pd.Timestamp(ts[i]), r))
                    s = expectancy_split(rs)
                    s.update({
                        "pair": pair, "atr_period": atr_period, "k": k,
                        "trigger": trigger, "direction": direction,
                        "total_n": len(rs),
                    })
                    rows.append(s)
    return rows


def spread_test_pair(pair, atr_period, k, trigger, direction, entry_mode="mid"):
    store = FxStore(read_only=True)
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return None
    mid = ohlc_mid(raw)
    m_open = mid["open"].to_numpy(dtype=float)
    m_close = mid["close"].to_numpy(dtype=float)
    m_high = mid["high"].to_numpy(dtype=float)
    m_low = mid["low"].to_numpy(dtype=float)
    atr_arr = atr(mid, period=int(atr_period)).to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()
    ca = raw["close_ask"].to_numpy(dtype=float)
    ha = raw["high_ask"].to_numpy(dtype=float)
    la = raw["low_ask"].to_numpy(dtype=float)
    cb = raw["close_bid"].to_numpy(dtype=float)
    hb = raw["high_bid"].to_numpy(dtype=float)
    lb = raw["low_bid"].to_numpy(dtype=float)

    triggers = get_triggers(m_open, m_high, m_low, m_close,
                            atr_arr, float(k), trigger, direction)
    rs = []
    for i in triggers:
        if entry_mode == "limit":
            if direction == "long":
                r, _ = sim_long_limit_spread(ca, hb, lb, cb, lb, la, lb, int(i), MAX_HOLD)
            else:
                r, _ = sim_short_limit_spread(cb, ha, la, ca, ha, hb, ha, int(i), MAX_HOLD)
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
        "pair": pair, "atr_period": atr_period, "k": k,
        "trigger": trigger, "direction": direction, "total_n": len(rs),
    })
    return s


def collect_trades(pair, atr_period, k, trigger, direction, entry_mode="mid"):
    store = FxStore(read_only=True)
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return []
    mid = ohlc_mid(raw)
    m_open = mid["open"].to_numpy(dtype=float)
    m_close = mid["close"].to_numpy(dtype=float)
    m_high = mid["high"].to_numpy(dtype=float)
    m_low = mid["low"].to_numpy(dtype=float)
    atr_arr = atr(mid, period=int(atr_period)).to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()
    ca = raw["close_ask"].to_numpy(dtype=float)
    ha = raw["high_ask"].to_numpy(dtype=float)
    la = raw["low_ask"].to_numpy(dtype=float)
    cb = raw["close_bid"].to_numpy(dtype=float)
    hb = raw["high_bid"].to_numpy(dtype=float)
    lb = raw["low_bid"].to_numpy(dtype=float)

    triggers = get_triggers(m_open, m_high, m_low, m_close,
                            atr_arr, float(k), trigger, direction)
    trades = []
    for i in triggers:
        i = int(i)
        if entry_mode == "limit":
            if direction == "long":
                r, exit_idx = sim_long_limit_spread(ca, hb, lb, cb, lb, la, lb, i, MAX_HOLD)
            else:
                r, exit_idx = sim_short_limit_spread(cb, ha, la, ca, ha, hb, ha, i, MAX_HOLD)
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

    out_dir = str(Path(__file__).resolve().parents[1] / "harness" / "atr")
    os.makedirs(out_dir, exist_ok=True)
    print(f"=== ATR v2 walk-forward (entry={entry_mode}) ===\n", flush=True)
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

    print(f"\n=== ATR v2 spread test (entry={entry_mode}) ===", flush=True)
    spread_rows = []
    for idx, (_, r) in enumerate(survivors.iterrows(), 1):
        out = spread_test_pair(r["pair"], int(r["atr_period"]), float(r["k"]),
                               r["trigger"], r["direction"], entry_mode=entry_mode)
        if out is not None:
            spread_rows.append(out)
    spread_df = pd.DataFrame(spread_rows)
    spread_df.to_csv(f"{out_dir}/walkforward_spread{suffix}.csv", index=False)
    robust = survivor_gate_walkforward(spread_df)
    print(f"\nSpread-robust: {len(robust)}/{len(spread_df)}", flush=True)
    if robust.empty:
        print("\n*** ATR NULL — zero production cells. ***", flush=True)
        return

    print("\n=== Production cell selection ===", flush=True)
    selected = select_production_cells(robust, ["pair", "atr_period", "k", "trigger", "direction"])
    for s in selected:
        print(f"  {s['pair']:<10} ATR{int(s['atr_period'])} k={s['k']:.1f} "
              f"{s['trigger']:<16} {s['direction']:<5}  "
              f"te n={int(s['te_n'])} mean_R={s['te_mean_r']:+.3f}", flush=True)

    print("\n=== Building portfolio ===", flush=True)
    all_trades = []
    for s in selected:
        trades = collect_trades(s["pair"], int(s["atr_period"]), float(s["k"]),
                                s["trigger"], s["direction"], entry_mode=entry_mode)
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
