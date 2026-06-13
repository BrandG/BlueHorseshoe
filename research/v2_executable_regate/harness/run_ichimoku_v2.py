"""Ichimoku standalone trigger v1 under v2 methodology.

Three trigger families:

  tk_cross — Tenkan/Kijun crossover (the inflection-event analog).
    long:  tenkan[i] > kijun[i] AND tenkan[i-1] <= kijun[i-1]
    short: mirror.

  cloud_break — close crosses out of the cloud (the breakout analog).
    long:  close[i] > max(senkou_a[i], senkou_b[i]) AND
           close[i-1] <= max(senkou_a[i-1], senkou_b[i-1])
    short: mirror with min().

  tk_cross_above_cloud — TK cross with cloud-side confirmation (the classical
                         Ichimoku confluence rule).
    long:  TK cross long AND close[i] > max(senkou_a[i], senkou_b[i])
    short: TK cross short AND close[i] < min(senkou_a[i], senkou_b[i])

Two of these are TREND-shaped:
- cloud_break is structurally a static-channel breakout (similar shape to
  Donchian — strong NULL prior).
- tk_cross is an inflection event (similar shape to MACD signal_cross — has
  surfaced edge under limit entry).
- tk_cross_above_cloud combines the two with a cloud-side filter.

Param grid:
  params:   (9,26,52,26) standard, (7,22,44,22) fast, (12,30,60,30) slow
  trigger:  tk_cross, cloud_break, tk_cross_above_cloud
  direction: long, short
  pair:     40 OANDA pairs

Per pair: 3 × 3 × 2 = 18 cells. × 40 pairs = 720 cells per --entry mode.
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
from bh_ftmo.indicators import ohlc_mid, ichimoku


PARAM_SETS = [
    (9, 26, 52, 26),    # standard
    (7, 22, 44, 22),    # faster
    (12, 30, 60, 30),   # slower
]
TRIGGERS = ["tk_cross", "cloud_break", "tk_cross_above_cloud"]
DIRECTIONS = ["long", "short"]


def find_tk_cross_long(tenkan, kijun):
    n = len(tenkan)
    if n < 2:
        return np.array([], dtype=int)
    above = tenkan > kijun
    fresh = above & ~np.roll(above, 1)
    fresh[0] = False
    fresh &= ~np.isnan(tenkan) & ~np.isnan(kijun)
    return np.where(fresh)[0]


def find_tk_cross_short(tenkan, kijun):
    n = len(tenkan)
    if n < 2:
        return np.array([], dtype=int)
    below = tenkan < kijun
    fresh = below & ~np.roll(below, 1)
    fresh[0] = False
    fresh &= ~np.isnan(tenkan) & ~np.isnan(kijun)
    return np.where(fresh)[0]


def find_cloud_break_long(close, senkou_a, senkou_b):
    n = len(close)
    if n < 2:
        return np.array([], dtype=int)
    cloud_top = np.maximum(senkou_a, senkou_b)
    above = close > cloud_top
    fresh = above & ~np.roll(above, 1)
    fresh[0] = False
    fresh &= ~np.isnan(close) & ~np.isnan(cloud_top)
    return np.where(fresh)[0]


def find_cloud_break_short(close, senkou_a, senkou_b):
    n = len(close)
    if n < 2:
        return np.array([], dtype=int)
    cloud_bot = np.minimum(senkou_a, senkou_b)
    below = close < cloud_bot
    fresh = below & ~np.roll(below, 1)
    fresh[0] = False
    fresh &= ~np.isnan(close) & ~np.isnan(cloud_bot)
    return np.where(fresh)[0]


def find_tk_cross_above_cloud_long(tenkan, kijun, close, senkou_a, senkou_b):
    triggers = find_tk_cross_long(tenkan, kijun)
    cloud_top = np.maximum(senkou_a, senkou_b)
    if len(triggers) == 0:
        return triggers
    keep = (close[triggers] > cloud_top[triggers]) & ~np.isnan(cloud_top[triggers])
    return triggers[keep]


def find_tk_cross_below_cloud_short(tenkan, kijun, close, senkou_a, senkou_b):
    triggers = find_tk_cross_short(tenkan, kijun)
    cloud_bot = np.minimum(senkou_a, senkou_b)
    if len(triggers) == 0:
        return triggers
    keep = (close[triggers] < cloud_bot[triggers]) & ~np.isnan(cloud_bot[triggers])
    return triggers[keep]


def get_triggers(tenkan, kijun, close, senkou_a, senkou_b, trigger, direction):
    if trigger == "tk_cross":
        return (find_tk_cross_long(tenkan, kijun) if direction == "long"
                else find_tk_cross_short(tenkan, kijun))
    if trigger == "cloud_break":
        return (find_cloud_break_long(close, senkou_a, senkou_b) if direction == "long"
                else find_cloud_break_short(close, senkou_a, senkou_b))
    # tk_cross_above_cloud
    if direction == "long":
        return find_tk_cross_above_cloud_long(tenkan, kijun, close, senkou_a, senkou_b)
    return find_tk_cross_below_cloud_short(tenkan, kijun, close, senkou_a, senkou_b)


def walkforward_pair(pair, entry_mode="mid"):
    store = FxStore(read_only=True)
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
    for tenkan_p, kijun_p, senkou_b_p, displ in PARAM_SETS:
        ich = ichimoku(mid, tenkan_period=tenkan_p, kijun_period=kijun_p,
                       senkou_b_period=senkou_b_p, displacement=displ)
        tenkan = ich["tenkan"].to_numpy(dtype=float)
        kijun = ich["kijun"].to_numpy(dtype=float)
        senkou_a = ich["senkou_a"].to_numpy(dtype=float)
        senkou_b = ich["senkou_b"].to_numpy(dtype=float)
        for trigger in TRIGGERS:
            for direction in DIRECTIONS:
                sim = long_sim if direction == "long" else short_sim
                triggers = get_triggers(tenkan, kijun, m_close, senkou_a, senkou_b,
                                        trigger, direction)
                rs = []
                for i in triggers:
                    r, _ = sim(m_close, m_high, m_low, int(i), MAX_HOLD)
                    if r is None:
                        continue
                    rs.append((pd.Timestamp(ts[i]), r))
                s = expectancy_split(rs)
                s.update({
                    "pair": pair, "tenkan": tenkan_p, "kijun": kijun_p,
                    "senkou_b": senkou_b_p, "displacement": displ,
                    "trigger": trigger, "direction": direction,
                    "total_n": len(rs),
                })
                rows.append(s)
    return rows


def spread_test_pair(pair, tenkan_p, kijun_p, senkou_b_p, displ, trigger, direction, entry_mode="mid"):
    store = FxStore(read_only=True)
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return None
    mid = ohlc_mid(raw)
    ich = ichimoku(mid, tenkan_period=int(tenkan_p), kijun_period=int(kijun_p),
                   senkou_b_period=int(senkou_b_p), displacement=int(displ))
    tenkan = ich["tenkan"].to_numpy(dtype=float)
    kijun = ich["kijun"].to_numpy(dtype=float)
    senkou_a = ich["senkou_a"].to_numpy(dtype=float)
    senkou_b = ich["senkou_b"].to_numpy(dtype=float)
    m_close = mid["close"].to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()
    ca = raw["close_ask"].to_numpy(dtype=float)
    ha = raw["high_ask"].to_numpy(dtype=float)
    la = raw["low_ask"].to_numpy(dtype=float)
    cb = raw["close_bid"].to_numpy(dtype=float)
    hb = raw["high_bid"].to_numpy(dtype=float)
    lb = raw["low_bid"].to_numpy(dtype=float)

    triggers = get_triggers(tenkan, kijun, m_close, senkou_a, senkou_b, trigger, direction)
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
        "pair": pair, "tenkan": tenkan_p, "kijun": kijun_p,
        "senkou_b": senkou_b_p, "displacement": displ,
        "trigger": trigger, "direction": direction, "total_n": len(rs),
    })
    return s


def collect_trades(pair, tenkan_p, kijun_p, senkou_b_p, displ, trigger, direction, entry_mode="mid"):
    store = FxStore(read_only=True)
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return []
    mid = ohlc_mid(raw)
    ich = ichimoku(mid, tenkan_period=int(tenkan_p), kijun_period=int(kijun_p),
                   senkou_b_period=int(senkou_b_p), displacement=int(displ))
    tenkan = ich["tenkan"].to_numpy(dtype=float)
    kijun = ich["kijun"].to_numpy(dtype=float)
    senkou_a = ich["senkou_a"].to_numpy(dtype=float)
    senkou_b = ich["senkou_b"].to_numpy(dtype=float)
    m_close = mid["close"].to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()
    ca = raw["close_ask"].to_numpy(dtype=float)
    ha = raw["high_ask"].to_numpy(dtype=float)
    la = raw["low_ask"].to_numpy(dtype=float)
    cb = raw["close_bid"].to_numpy(dtype=float)
    hb = raw["high_bid"].to_numpy(dtype=float)
    lb = raw["low_bid"].to_numpy(dtype=float)

    triggers = get_triggers(tenkan, kijun, m_close, senkou_a, senkou_b, trigger, direction)
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

    out_dir = str(Path(__file__).resolve().parents[1] / "harness" / "ichimoku")
    os.makedirs(out_dir, exist_ok=True)
    print(f"=== Ichimoku v2 walk-forward (entry={entry_mode}) ===\n", flush=True)
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

    print(f"\n=== Ichimoku v2 spread test (entry={entry_mode}) ===", flush=True)
    spread_rows = []
    for idx, (_, r) in enumerate(survivors.iterrows(), 1):
        out = spread_test_pair(r["pair"], int(r["tenkan"]), int(r["kijun"]),
                               int(r["senkou_b"]), int(r["displacement"]),
                               r["trigger"], r["direction"], entry_mode=entry_mode)
        if out is not None:
            spread_rows.append(out)
    spread_df = pd.DataFrame(spread_rows)
    spread_df.to_csv(f"{out_dir}/walkforward_spread{suffix}.csv", index=False)
    robust = survivor_gate_walkforward(spread_df)
    print(f"\nSpread-robust: {len(robust)}/{len(spread_df)}", flush=True)
    if robust.empty:
        print("\n*** Ichimoku NULL — zero production cells. ***", flush=True)
        return

    print("\n=== Production cell selection ===", flush=True)
    selected = select_production_cells(robust, ["pair", "tenkan", "kijun", "senkou_b",
                                                 "displacement", "trigger", "direction"])
    for s in selected:
        print(f"  {s['pair']:<10} ({int(s['tenkan'])},{int(s['kijun'])},{int(s['senkou_b'])}) "
              f"{s['trigger']:<22} {s['direction']:<5}  "
              f"te n={int(s['te_n'])} mean_R={s['te_mean_r']:+.3f}", flush=True)

    print("\n=== Building portfolio ===", flush=True)
    all_trades = []
    for s in selected:
        trades = collect_trades(s["pair"], int(s["tenkan"]), int(s["kijun"]),
                                int(s["senkou_b"]), int(s["displacement"]),
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
