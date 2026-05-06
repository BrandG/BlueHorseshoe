"""CCI portfolio walk-forward."""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/src")

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import cci, ohlc_mid


SURVIVING_PAIRS = ["EUR_GBP", "USD_JPY", "CHF_JPY", "USD_CAD", "EUR_USD"]
GRANULARITY = "H4"
MAX_HOLD = 14 * 6
TRAIN_FRAC = 0.7
TP_PCT = 0.01
STOP_PCT = 0.01

SPREAD_CSV = "/root/BlueHorseshoe/research/cci_phase0_v1/walkforward_cci_spread.csv"


def find_fresh_long(cci_arr, threshold, recovery):
    n = len(cci_arr)
    if n < recovery + 1:
        return np.array([], dtype=int)
    diffs_pos = np.zeros(n, dtype=bool)
    diffs_pos[1:] = cci_arr[1:] > cci_arr[:-1]
    rising = np.zeros(n, dtype=bool)
    for i in range(recovery, n):
        rising[i] = bool(np.all(diffs_pos[i - recovery + 1: i + 1]))
    base = np.full(n, np.nan)
    base[recovery:] = cci_arr[: n - recovery]
    valid = ~np.isnan(base) & ~np.isnan(cci_arr)
    cond = valid & rising & (base < -threshold)
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def find_fresh_short(cci_arr, threshold, recovery):
    n = len(cci_arr)
    if n < recovery + 1:
        return np.array([], dtype=int)
    diffs_neg = np.zeros(n, dtype=bool)
    diffs_neg[1:] = cci_arr[1:] < cci_arr[:-1]
    falling = np.zeros(n, dtype=bool)
    for i in range(recovery, n):
        falling[i] = bool(np.all(diffs_neg[i - recovery + 1: i + 1]))
    base = np.full(n, np.nan)
    base[recovery:] = cci_arr[: n - recovery]
    valid = ~np.isnan(base) & ~np.isnan(cci_arr)
    cond = valid & falling & (base > threshold)
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
        kk = i + j
        if low_bid[kk] <= stop:
            return -1, kk
        if high_bid[kk] >= tp:
            return +1, kk
    return 0, i + max_hold


def sim_short_spread(close_bid, high_ask, low_ask, close_ask, i, max_hold):
    if i + max_hold >= len(close_bid):
        return None, None
    entry = close_bid[i]
    tp = entry * (1 - TP_PCT)
    stop = entry * (1 + STOP_PCT)
    for j in range(1, max_hold + 1):
        kk = i + j
        if high_ask[kk] >= stop:
            return -1, kk
        if low_ask[kk] <= tp:
            return +1, kk
    return 0, i + max_hold


def collect_trades(pair, period, threshold, recovery, direction):
    store = FxStore()
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return []

    mid = ohlc_mid(raw)
    cci_arr = cci(mid, period=period).to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()
    ca = raw["close_ask"].to_numpy(dtype=float)
    ha = raw["high_ask"].to_numpy(dtype=float)
    la = raw["low_ask"].to_numpy(dtype=float)
    cb = raw["close_bid"].to_numpy(dtype=float)
    hb = raw["high_bid"].to_numpy(dtype=float)
    lb = raw["low_bid"].to_numpy(dtype=float)

    if direction == "long":
        triggers = find_fresh_long(cci_arr, float(threshold), int(recovery))
    else:
        triggers = find_fresh_short(cci_arr, float(threshold), int(recovery))

    trades = []
    for i in triggers:
        if direction == "long":
            r, exit_idx = sim_long_spread(ca, hb, lb, cb, int(i), MAX_HOLD)
        else:
            r, exit_idx = sim_short_spread(cb, ha, la, ca, int(i), MAX_HOLD)
        if r is None:
            continue
        trades.append({
            "pair": pair,
            "entry_ts": pd.Timestamp(ts[i]),
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
    df = pd.read_csv(SPREAD_CSV)
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
            print(f"    p={int(r['period']):<2} thr={int(r['threshold'])} "
                  f"rec={int(r['recovery'])} {r['direction']:<5}  "
                  f"tr n={int(r['tr_n'])} WR={r['tr_wr']*100:.1f}%  "
                  f"te n={int(r['te_n'])} WR={r['te_wr']*100:.1f}% "
                  f"CI=[{r['te_ci_low']*100:.1f},{r['te_ci_high']*100:.1f}]")
        chosen = pair_cells.iloc[0]
        print(f"    PICK: p={int(chosen['period'])} thr={int(chosen['threshold'])} "
              f"rec={int(chosen['recovery'])} {chosen['direction']}\n")
        selected.append(chosen)

    if not selected:
        print("No selected cells — abort.")
        return

    print("=== Collecting trades ===\n")
    all_trades = []
    for s in selected:
        trades = collect_trades(s["pair"], int(s["period"]), int(s["threshold"]),
                                int(s["recovery"]), s["direction"])
        all_trades.extend(trades)
        print(f"  {s['pair']:<10} {s['direction']:<5} p={int(s['period'])} "
              f"thr={int(s['threshold'])} rec={int(s['recovery'])} → {len(trades)} trades")

    df_t = pd.DataFrame(all_trades).sort_values("entry_ts").reset_index(drop=True)
    print(f"\nTotal portfolio trades: {len(df_t)}")
    print(f"Date range: {df_t['entry_ts'].min().date()} → {df_t['entry_ts'].max().date()}")

    cut = int(len(df_t) * TRAIN_FRAC)
    df_tr = df_t.iloc[:cut].copy()
    df_te = df_t.iloc[cut:].copy()
    boundary = df_te["entry_ts"].iloc[0]
    print(f"Train/test split: {boundary.date()}  (train n={len(df_tr)}, test n={len(df_te)})\n")

    def portfolio_stats(df_split, label):
        n = len(df_split)
        if n == 0:
            print(f"  {label}: empty")
            return
        wins = int((df_split["r"] >= 1).sum())
        losses = int((df_split["r"] <= -1).sum())
        timeouts = n - wins - losses
        decisive = wins + losses
        wr, ci_low, ci_high = wilson_ci(wins, decisive)
        rs = df_split["r"].to_numpy()
        cum = np.cumsum(rs)
        running_max = np.maximum.accumulate(cum)
        drawdown = cum - running_max
        max_dd = float(drawdown.min())
        signs = np.sign(rs)
        max_consec_loss = current = 0
        for s in signs:
            if s < 0:
                current += 1
                max_consec_loss = max(max_consec_loss, current)
            else:
                current = 0
        events = []
        for _, t in df_split.iterrows():
            events.append((t["entry_ts"], +1))
            events.append((t["exit_ts"], -1))
        events.sort()
        max_concurrent = current_open = 0
        for _, delta in events:
            current_open += delta
            max_concurrent = max(max_concurrent, current_open)
        print(f"  {label}: n={n}  W={wins} L={losses} T={timeouts}")
        print(f"    decisive WR = {wr*100:.1f}%  CI [{ci_low*100:.1f}, {ci_high*100:.1f}]")
        print(f"    avg R per trade = {rs.mean():+.4f}")
        print(f"    cumulative R = {cum[-1]:+.1f}")
        print(f"    max drawdown = {max_dd:.1f} R")
        print(f"    max consecutive losses = {max_consec_loss}")
        print(f"    max simultaneous open positions = {max_concurrent}")

    print("=== Portfolio walk-forward stats ===\n")
    portfolio_stats(df_tr, "TRAIN")
    print()
    portfolio_stats(df_te, "TEST")
    print()
    portfolio_stats(df_t, "FULL HISTORY")

    print("\n=== Per-pair contribution (test half) ===")
    for pair in df_te["pair"].unique():
        sub = df_te[df_te["pair"] == pair]
        wins = int((sub["r"] >= 1).sum())
        losses = int((sub["r"] <= -1).sum())
        wr, ci_low, ci_high = wilson_ci(wins, wins + losses)
        cum_r = sub["r"].sum()
        print(f"  {pair:<10} n={len(sub)} W/L/T={wins}/{losses}/{len(sub)-wins-losses}  "
              f"WR={wr*100:.1f}% CI=[{ci_low*100:.1f},{ci_high*100:.1f}]  cum_R={cum_r:+.1f}")

    print("\n=== Cross-pair monthly R correlation (test half) ===")
    df_te_copy = df_te.copy()
    df_te_copy["month"] = df_te_copy["entry_ts"].dt.to_period("M")
    monthly = df_te_copy.pivot_table(index="month", columns="pair", values="r",
                                      aggfunc="sum", fill_value=0)
    corr = monthly.corr()
    print(corr.to_string())

    print("\n=== Production cell spec ===")
    spec = {s["pair"]: {
        "period": int(s["period"]),
        "threshold": int(s["threshold"]),
        "recovery": int(s["recovery"]),
        "direction": s["direction"],
        "test_wr": float(s["te_wr"]),
        "test_n": int(s["te_n"]),
        "test_ci_low": float(s["te_ci_low"]),
    } for s in selected}
    for pair, cfg in spec.items():
        print(f"  {pair}: {cfg}")


if __name__ == "__main__":
    main()
