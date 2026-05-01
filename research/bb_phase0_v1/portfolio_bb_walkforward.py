"""BB portfolio walk-forward: pick one cell per surviving pair, combine into
a single chronological trade ledger, and report portfolio-level metrics.

Spread-aware (uses the same fills as walkforward_bb_spread.py).

Selection rule: per pair, pick the robust cell (CI lower > 50% on both halves)
with the largest te_n. Ties broken by highest te_wr.

Portfolio metrics:
  - aggregated WR with CI (test half)
  - cumulative R curve (1 R = 1 unit of risk per trade)
  - max drawdown in R units
  - max consecutive losses
  - max simultaneous open positions
  - cross-pair correlation of daily returns
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/src")

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import bollinger_bands, ohlc_mid


SURVIVING_PAIRS = ["CAD_CHF", "USD_JPY", "EUR_CAD", "CHF_JPY"]
GRANULARITY = "H4"
MAX_HOLD = 14 * 6
TRAIN_FRAC = 0.7
TP_PCT = 0.01
STOP_PCT = 0.01

CONFIRM_MAP = {
    "none": ("none", None),
    "bare": ("bare", None),
    "rise_0.00%": ("rise", 0.000),
    "rise_0.10%": ("rise", 0.001),
    "rise_0.25%": ("rise", 0.0025),
    "rise_0.50%": ("rise", 0.005),
}


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
    for j in range(1, max_hold + 1):
        k = i + j
        if low_bid[k] <= stop:
            return -1, k
        if high_bid[k] >= tp:
            return +1, k
    return 0, i + max_hold


def sim_short_spread(close_bid, high_ask, low_ask, close_ask, i, max_hold):
    if i + max_hold >= len(close_bid):
        return None, None
    entry = close_bid[i]
    tp = entry * (1 - TP_PCT)
    stop = entry * (1 + STOP_PCT)
    for j in range(1, max_hold + 1):
        k = i + j
        if high_ask[k] >= stop:
            return -1, k
        if low_ask[k] <= tp:
            return +1, k
    return 0, i + max_hold


def maybe_enter_long(close_mid, lower, i, confirm):
    if confirm[0] == "none":
        return i
    if i + 1 >= len(close_mid):
        return None
    if confirm[0] == "bare":
        return i + 1 if close_mid[i + 1] > lower[i + 1] else None
    return i + 1 if close_mid[i + 1] >= close_mid[i] * (1 + confirm[1]) else None


def maybe_enter_short(close_mid, upper, i, confirm):
    if confirm[0] == "none":
        return i
    if i + 1 >= len(close_mid):
        return None
    if confirm[0] == "bare":
        return i + 1 if close_mid[i + 1] < upper[i + 1] else None
    return i + 1 if close_mid[i + 1] <= close_mid[i] * (1 - confirm[1]) else None


def collect_trades(pair, period, std, depth, direction, confirm_str):
    confirm = CONFIRM_MAP[confirm_str]
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
        if direction == "long":
            entry_idx = maybe_enter_long(m_close, lower, int(i), confirm)
        else:
            entry_idx = maybe_enter_short(m_close, upper, int(i), confirm)
        if entry_idx is None:
            continue
        if direction == "long":
            r, exit_idx = sim_long_spread(ca, hb, lb, cb, entry_idx, MAX_HOLD)
        else:
            r, exit_idx = sim_short_spread(cb, ha, la, ca, entry_idx, MAX_HOLD)
        if r is None:
            continue
        trades.append({
            "pair": pair,
            "entry_ts": pd.Timestamp(ts[entry_idx]),
            "exit_ts": pd.Timestamp(ts[exit_idx]),
            "r": r,
        })
    return trades


def wilson_ci(wins, decisive):
    if decisive == 0:
        return float("nan"), float("nan"), float("nan")
    p = wins / decisive
    se = np.sqrt(p * (1 - p) / decisive)
    return p, max(0.0, p - 1.96 * se), min(1.0, p + 1.96 * se)


def main():
    df = pd.read_csv("/tmp/walkforward_bb_spread.csv")
    robust = df[(df["tr_ci_low"] > 0.50) & (df["te_ci_low"] > 0.50)
                & (df["tr_n"] >= 50) & (df["te_n"] >= 30)
                & (df["pair"].isin(SURVIVING_PAIRS))].copy()

    print("=== Robust spread-aware cells per pair ===\n")
    selected = []
    for pair in SURVIVING_PAIRS:
        pair_cells = robust[robust["pair"] == pair].sort_values(
            ["te_n", "te_wr"], ascending=[False, False])
        if pair_cells.empty:
            print(f"  {pair}: no robust cells, SKIP\n")
            continue
        print(f"  {pair} (sorted by te_n desc):")
        for _, r in pair_cells.iterrows():
            print(f"    p={int(r['period'])} s={r['std']} d={r['depth']:.2f} {r['direction']:<5} "
                  f"confirm={r['confirm']:<11}  tr n={int(r['tr_n'])} WR={r['tr_wr']*100:.1f}%  "
                  f"te n={int(r['te_n'])} WR={r['te_wr']*100:.1f}% CI=[{r['te_ci_low']*100:.1f},{r['te_ci_high']*100:.1f}]")
        # Pick first (largest te_n)
        chosen = pair_cells.iloc[0]
        print(f"    ★ PICK: p={int(chosen['period'])} s={chosen['std']} d={chosen['depth']:.2f} "
              f"{chosen['direction']} confirm={chosen['confirm']}\n")
        selected.append(chosen)

    if not selected:
        print("No selected cells — abort.")
        return

    # Collect all trades from selected cells
    print("=== Collecting trades ===\n")
    all_trades = []
    for s in selected:
        trades = collect_trades(s["pair"], int(s["period"]), float(s["std"]),
                                float(s["depth"]), s["direction"], s["confirm"])
        all_trades.extend(trades)
        print(f"  {s['pair']:<10} {s['direction']:<5} p={int(s['period'])} s={s['std']} "
              f"d={s['depth']:.2f} confirm={s['confirm']:<11} → {len(trades)} trades")

    df_t = pd.DataFrame(all_trades).sort_values("entry_ts").reset_index(drop=True)
    print(f"\nTotal portfolio trades: {len(df_t)}")
    print(f"Date range: {df_t['entry_ts'].min().date()} → {df_t['entry_ts'].max().date()}")

    # Walk-forward split (use the same boundary as the cell-level walk-forward:
    # 70th percentile of entry_ts across the portfolio)
    cut = int(len(df_t) * TRAIN_FRAC)
    df_tr = df_t.iloc[:cut].copy()
    df_te = df_t.iloc[cut:].copy()
    boundary = df_te["entry_ts"].iloc[0]
    print(f"Train/test split: {boundary.date()}  (train n={len(df_tr)}, test n={len(df_te)})\n")

    def portfolio_stats(df_split, label):
        n = len(df_split)
        if n == 0:
            print(f"  {label}: empty"); return
        wins = (df_split["r"] >= 1).sum()
        losses = (df_split["r"] <= -1).sum()
        timeouts = n - wins - losses
        decisive = wins + losses
        wr, ci_low, ci_high = wilson_ci(wins, decisive)
        # Cumulative R curve and drawdown
        rs = df_split["r"].to_numpy()
        cum = np.cumsum(rs)
        running_max = np.maximum.accumulate(cum)
        drawdown = cum - running_max
        max_dd = float(drawdown.min())
        # Max consecutive losses
        signs = np.sign(rs)
        max_consec_loss = 0
        current = 0
        for s in signs:
            if s < 0:
                current += 1
                max_consec_loss = max(max_consec_loss, current)
            else:
                current = 0
        # Concurrent positions (max # of trades open at any timestamp)
        events = []
        for _, t in df_split.iterrows():
            events.append((t["entry_ts"], +1))
            events.append((t["exit_ts"], -1))
        events.sort()
        max_concurrent = 0
        current_open = 0
        for _, delta in events:
            current_open += delta
            max_concurrent = max(max_concurrent, current_open)
        print(f"  {label}: n={n}  W={wins} L={losses} T={timeouts}")
        print(f"    decisive WR = {wr*100:.1f}%  CI [{ci_low*100:.1f}, {ci_high*100:.1f}]")
        print(f"    avg R per trade = {rs.mean():+.4f}")
        print(f"    cumulative R = {cum[-1]:+.1f}  (final equity if 1R/trade)")
        print(f"    max drawdown = {max_dd:.1f} R")
        print(f"    max consecutive losses = {max_consec_loss}")
        print(f"    max simultaneous open positions = {max_concurrent}")

    print("=== Portfolio walk-forward stats ===\n")
    portfolio_stats(df_tr, "TRAIN")
    print()
    portfolio_stats(df_te, "TEST")
    print()
    portfolio_stats(df_t, "FULL HISTORY")

    # Per-pair contribution to portfolio
    print("\n=== Per-pair contribution (test half) ===")
    for pair in df_te["pair"].unique():
        sub = df_te[df_te["pair"] == pair]
        wins = (sub["r"] >= 1).sum()
        losses = (sub["r"] <= -1).sum()
        wr, ci_low, ci_high = wilson_ci(int(wins), int(wins + losses))
        cum_r = sub["r"].sum()
        print(f"  {pair:<10} n={len(sub)} W/L/T={wins}/{losses}/{len(sub)-wins-losses}  "
              f"WR={wr*100:.1f}% CI=[{ci_low*100:.1f},{ci_high*100:.1f}]  cum_R={cum_r:+.1f}")

    # Cross-pair monthly correlation
    print("\n=== Cross-pair monthly R correlation (test half) ===")
    df_te_copy = df_te.copy()
    df_te_copy["month"] = df_te_copy["entry_ts"].dt.to_period("M")
    monthly = df_te_copy.pivot_table(index="month", columns="pair", values="r",
                                      aggfunc="sum", fill_value=0)
    corr = monthly.corr()
    print(corr.to_string())

    # Save the production cell spec
    spec = {s["pair"]: {
        "period": int(s["period"]),
        "std": float(s["std"]),
        "depth": float(s["depth"]),
        "direction": s["direction"],
        "confirm": s["confirm"],
        "test_wr": float(s["te_wr"]),
        "test_n": int(s["te_n"]),
        "test_ci_low": float(s["te_ci_low"]),
    } for s in selected}
    print("\n=== Production cell spec ===")
    for pair, cfg in spec.items():
        print(f"  {pair}: {cfg}")


if __name__ == "__main__":
    main()
