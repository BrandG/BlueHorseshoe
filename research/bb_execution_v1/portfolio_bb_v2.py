"""BB v1 portfolio assembly under the new methodology.

Uses spread-robust variant-A cells from walkforward_spread.csv. Per pair, picks
cell with largest test n (ties broken by te_mean_r). Builds full portfolio
ledger and reports stats with R tracking.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/src")

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import bollinger_bands, ohlc_mid


GRANULARITY = "H4"
MAX_HOLD = 14 * 6
TP_PCT = 0.01
STOP_PCT = 0.01
TRAIN_FRAC = 0.7

SPREAD_CSV = "/root/BlueHorseshoe/research/bb_execution_v1/walkforward_spread.csv"


def find_fresh_long(close, lower, bw, depth):
    threshold = lower - depth * bw
    cond = close < threshold
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def find_fresh_short(close, upper, bw, depth):
    threshold = upper + depth * bw
    cond = close > threshold
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def sim_long_spread(close_ask, high_bid, low_bid, close_bid, i, max_hold):
    if i + max_hold >= len(close_ask):
        return None, None
    entry = close_ask[i]
    tp = entry * (1 + TP_PCT)
    stop = entry * (1 - STOP_PCT)
    risk = entry - stop
    for j in range(1, max_hold + 1):
        k = i + j
        if low_bid[k] <= stop:
            return -1.0, k
        if high_bid[k] >= tp:
            return (tp - entry) / risk, k
    exit_price = close_bid[i + max_hold]
    return (exit_price - entry) / risk, i + max_hold


def sim_short_spread(close_bid, high_ask, low_ask, close_ask, i, max_hold):
    if i + max_hold >= len(close_bid):
        return None, None
    entry = close_bid[i]
    tp = entry * (1 - TP_PCT)
    stop = entry * (1 + STOP_PCT)
    risk = stop - entry
    for j in range(1, max_hold + 1):
        k = i + j
        if high_ask[k] >= stop:
            return -1.0, k
        if low_ask[k] <= tp:
            return (entry - tp) / risk, k
    exit_price = close_ask[i + max_hold]
    return (entry - exit_price) / risk, i + max_hold


def collect_trades(pair, period, std, depth, direction):
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
            r, exit_idx = sim_long_spread(ca, hb, lb, cb, i, MAX_HOLD)
        else:
            r, exit_idx = sim_short_spread(cb, ha, la, ca, i, MAX_HOLD)
        if r is None:
            continue
        trades.append({
            "pair": pair,
            "entry_ts": pd.Timestamp(ts[i]),
            "exit_ts": pd.Timestamp(ts[exit_idx]),
            "r": r,
        })
    return trades


def main():
    df = pd.read_csv(SPREAD_CSV)
    robust = df[(df["variant"] == "A")
                & (df["tr_ci_low_r"] > 0.0) & (df["te_ci_low_r"] > 0.0)
                & (df["tr_n"] >= 50) & (df["te_n"] >= 30)].copy()

    print(f"Robust spread-aware variant-A cells: {len(robust)}\n")

    # Per pair, pick largest te_n
    print("=== Per-pair production cell selection ===\n")
    selected = []
    for pair in sorted(robust["pair"].unique()):
        pair_cells = robust[robust["pair"] == pair].sort_values(
            ["te_n", "te_mean_r"], ascending=[False, False])
        chosen = pair_cells.iloc[0]
        selected.append(chosen)
        print(f"  {pair}: p={int(chosen['period'])} std={chosen['std']:.1f} "
              f"depth={chosen['depth']:.2f} {chosen['direction']:<5}  "
              f"te n={int(chosen['te_n'])} mean_R={chosen['te_mean_r']:+.3f}")
    print()

    # Build portfolio
    all_trades = []
    for s in selected:
        trades = collect_trades(s["pair"], int(s["period"]), float(s["std"]),
                                float(s["depth"]), s["direction"])
        all_trades.extend(trades)
        print(f"  {s['pair']:<10} {s['direction']:<5} → {len(trades)} trades")

    df_t = pd.DataFrame(all_trades).sort_values("entry_ts").reset_index(drop=True)
    print(f"\nTotal portfolio trades: {len(df_t)}")
    print(f"Date range: {df_t['entry_ts'].min().date()} → {df_t['entry_ts'].max().date()}")

    cut = int(len(df_t) * TRAIN_FRAC)
    df_tr = df_t.iloc[:cut].copy()
    df_te = df_t.iloc[cut:].copy()
    print(f"Train/test split: {df_te['entry_ts'].iloc[0].date()}  "
          f"(train n={len(df_tr)}, test n={len(df_te)})\n")

    def stats(df_split, label):
        n = len(df_split)
        if n == 0:
            return
        rs = df_split["r"].to_numpy()
        wins = int((rs >= 1.0).sum())  # full TP wins
        losses = int((rs <= -1.0).sum())  # full stop losses
        timeouts = n - wins - losses
        wr = wins / max(wins + losses, 1)
        mean_r = rs.mean()
        cum_r = rs.sum()
        running_max = np.maximum.accumulate(np.cumsum(rs))
        max_dd = float((np.cumsum(rs) - running_max).min())
        signs = np.sign(rs)
        max_consec = curr = 0
        for s_ in signs:
            if s_ < 0:
                curr += 1
                max_consec = max(max_consec, curr)
            else:
                curr = 0
        events = []
        for _, t in df_split.iterrows():
            events.append((t["entry_ts"], +1))
            events.append((t["exit_ts"], -1))
        events.sort()
        max_concurrent = curr_open = 0
        for _, delta in events:
            curr_open += delta
            max_concurrent = max(max_concurrent, curr_open)
        print(f"  {label}: n={n} W/L/T={wins}/{losses}/{timeouts}  "
              f"WR={wr*100:.1f}%  mean_R={mean_r:+.3f}  cum_R={cum_r:+.1f}  "
              f"max_DD={max_dd:.1f}R  max_consec_loss={max_consec}  max_simul={max_concurrent}")

    print("=== Portfolio walk-forward stats ===")
    stats(df_tr, "TRAIN")
    stats(df_te, "TEST")
    stats(df_t, "FULL")

    print("\n=== Per-pair contribution (test half) ===")
    for pair in sorted(df_te["pair"].unique()):
        sub = df_te[df_te["pair"] == pair]
        rs = sub["r"].to_numpy()
        wins = int((rs >= 1.0).sum())
        losses = int((rs <= -1.0).sum())
        wr = wins / max(wins + losses, 1)
        print(f"  {pair:<10} n={len(sub)} W/L/T={wins}/{losses}/{len(sub)-wins-losses}  "
              f"WR={wr*100:.1f}% mean_R={rs.mean():+.3f} cum_R={rs.sum():+.1f}")

    print("\n=== Cross-pair monthly R correlation (test half) ===")
    df_te_copy = df_te.copy()
    df_te_copy["month"] = df_te_copy["entry_ts"].dt.to_period("M")
    monthly = df_te_copy.pivot_table(index="month", columns="pair", values="r",
                                      aggfunc="sum", fill_value=0)
    print(monthly.corr().to_string())

    print("\n=== Production cell spec ===")
    for s in selected:
        print(f"  {s['pair']}: period={int(s['period'])}, std={s['std']:.1f}, "
              f"depth={s['depth']:.2f}, direction={s['direction']}, "
              f"test_n={int(s['te_n'])}, test_mean_r={s['te_mean_r']:+.3f}")


if __name__ == "__main__":
    main()
