"""Candlestick reversal patterns v1 standalone trigger under v2 methodology.

Four single-event reversal patterns from `bh_ftmo.indicators.candlestick`:

  - Hammer            — bullish reversal (long signal): small body, long lower shadow
  - Shooting Star     — bearish reversal (short signal): small body, long upper shadow
  - Bullish Engulfing — bullish reversal (long signal): prior bearish bar engulfed
  - Bearish Engulfing — bearish reversal (short signal): prior bullish bar engulfed

Each pattern fires on every bar where its boolean detector returns True (no
"fresh" disambiguation needed — patterns are bar-discrete).

Per the BH FTMO finding so far ("smoothed mean-reversion works, level-touch
doesn't"), candlesticks are intermediate: pattern detection has no internal
smoothing but does have multi-component shape constraints (body fraction,
shadow ratios). Hammer/engulfing in particular were validated in BH Lite for
equities. Tested as v2 standalone under all three entry modes for completeness.

Param grid:
  pattern: hammer / shooting_star / bull_engulf / bear_engulf
  strict:  False (default thresholds) / True (tighter thresholds)
  pair:    40 OANDA pairs

Per pair: 4 × 2 = 8 cells. × 40 pairs = 320 cells per --entry mode.
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
from bh_ftmo.indicators import (
    ohlc_mid,
    is_hammer, is_shooting_star,
    is_bullish_engulfing, is_bearish_engulfing,
)


PATTERNS = [
    ("hammer", "long"),
    ("shooting_star", "short"),
    ("bull_engulf", "long"),
    ("bear_engulf", "short"),
]
STRICT_OPTIONS = [False, True]


def detect_pattern(mid, pattern, strict):
    """Return boolean Series for the pattern at the given strictness."""
    if pattern == "hammer":
        if strict:
            return is_hammer(mid, body_frac_max=0.25, lower_shadow_min=0.6, upper_shadow_max=0.10)
        return is_hammer(mid)
    if pattern == "shooting_star":
        if strict:
            return is_shooting_star(mid, body_frac_max=0.25, upper_shadow_min=0.6, lower_shadow_max=0.10)
        return is_shooting_star(mid)
    if pattern == "bull_engulf":
        if strict:
            return is_bullish_engulfing(mid, min_body_frac=0.5)
        return is_bullish_engulfing(mid)
    if pattern == "bear_engulf":
        if strict:
            return is_bearish_engulfing(mid, min_body_frac=0.5)
        return is_bearish_engulfing(mid)
    raise ValueError(f"unknown pattern: {pattern}")


def get_triggers(mid, pattern, strict):
    mask = detect_pattern(mid, pattern, strict).to_numpy(dtype=bool)
    return np.where(mask)[0]


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
    for pattern, direction in PATTERNS:
        sim = long_sim if direction == "long" else short_sim
        for strict in STRICT_OPTIONS:
            triggers = get_triggers(mid, pattern, strict)
            rs = []
            for i in triggers:
                r, _ = sim(m_close, m_high, m_low, int(i), MAX_HOLD)
                if r is None:
                    continue
                rs.append((pd.Timestamp(ts[i]), r))
            s = expectancy_split(rs)
            s.update({
                "pair": pair, "pattern": pattern, "strict": strict,
                "direction": direction, "total_n": len(rs),
            })
            rows.append(s)
    return rows


def spread_test_pair(pair, pattern, strict, direction, entry_mode="mid"):
    store = FxStore()
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return None
    mid = ohlc_mid(raw)
    ts = raw["timestamp"].to_numpy()
    ca = raw["close_ask"].to_numpy(dtype=float)
    ha = raw["high_ask"].to_numpy(dtype=float)
    la = raw["low_ask"].to_numpy(dtype=float)
    cb = raw["close_bid"].to_numpy(dtype=float)
    hb = raw["high_bid"].to_numpy(dtype=float)
    lb = raw["low_bid"].to_numpy(dtype=float)

    triggers = get_triggers(mid, pattern, bool(strict))
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
        "pair": pair, "pattern": pattern, "strict": bool(strict),
        "direction": direction, "total_n": len(rs),
    })
    return s


def collect_trades(pair, pattern, strict, direction, entry_mode="mid"):
    store = FxStore()
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return []
    mid = ohlc_mid(raw)
    ts = raw["timestamp"].to_numpy()
    ca = raw["close_ask"].to_numpy(dtype=float)
    ha = raw["high_ask"].to_numpy(dtype=float)
    la = raw["low_ask"].to_numpy(dtype=float)
    cb = raw["close_bid"].to_numpy(dtype=float)
    hb = raw["high_bid"].to_numpy(dtype=float)
    lb = raw["low_bid"].to_numpy(dtype=float)

    triggers = get_triggers(mid, pattern, bool(strict))
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

    out_dir = "/root/BlueHorseshoe/research/_v2_rerun/candlestick"
    os.makedirs(out_dir, exist_ok=True)
    print(f"=== Candlestick v2 walk-forward (entry={entry_mode}) ===\n", flush=True)
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

    print(f"\n=== Candlestick v2 spread test (entry={entry_mode}) ===", flush=True)
    spread_rows = []
    for idx, (_, r) in enumerate(survivors.iterrows(), 1):
        out = spread_test_pair(r["pair"], r["pattern"], bool(r["strict"]), r["direction"],
                               entry_mode=entry_mode)
        if out is not None:
            spread_rows.append(out)
    spread_df = pd.DataFrame(spread_rows)
    spread_df.to_csv(f"{out_dir}/walkforward_spread{suffix}.csv", index=False)
    robust = survivor_gate_walkforward(spread_df)
    print(f"\nSpread-robust: {len(robust)}/{len(spread_df)}", flush=True)
    if robust.empty:
        print("\n*** Candlestick NULL — zero production cells. ***", flush=True)
        return

    print("\n=== Production cell selection ===", flush=True)
    selected = select_production_cells(robust, ["pair", "pattern", "strict", "direction"])
    for s in selected:
        print(f"  {s['pair']:<10} {s['pattern']:<14} strict={str(s['strict']):<5} "
              f"{s['direction']:<5}  te n={int(s['te_n'])} mean_R={s['te_mean_r']:+.3f}", flush=True)

    print("\n=== Building portfolio ===", flush=True)
    all_trades = []
    for s in selected:
        trades = collect_trades(s["pair"], s["pattern"], bool(s["strict"]), s["direction"],
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
