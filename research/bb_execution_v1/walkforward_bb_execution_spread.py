"""Spread-aware walk-forward for BB execution variants A and C.

Variants B and D are skipped — they produced 0 walk-forward survivors at mid,
so spread test would only confirm. A and C use fixed 1%/1% RR with different
entries (market vs stop-at-band).

Reads walkforward.csv to identify which cells to test (only those that passed
mid walk-forward gate). Re-simulates each survivor with bid/ask fills.
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


PAIRS_FULL = [
    "EUR_USD", "GBP_USD", "AUD_USD", "USD_CAD", "USD_CHF", "NZD_USD", "USD_SEK",
    "AUD_CHF", "AUD_NZD", "AUD_CAD", "EUR_AUD", "EUR_CAD", "EUR_CHF", "EUR_NZD",
    "EUR_CZK", "CAD_JPY", "CAD_CHF", "USD_JPY", "EUR_GBP", "EUR_JPY", "GBP_JPY",
    "GBP_AUD", "GBP_CAD", "GBP_CHF", "GBP_NZD", "CHF_JPY", "NZD_JPY", "AUD_JPY",
    "USD_SGD", "USD_PLN", "USD_CZK", "USD_HUF", "EUR_HUF", "EUR_PLN", "EUR_SEK",
    "NZD_CAD", "NZD_CHF", "EUR_NOK", "USD_ZAR", "USD_NOK",
]

GRANULARITY = "H4"
MAX_HOLD = 14 * 6
WAIT_BARS = 1
TP_PCT = 0.01
STOP_PCT = 0.01
TRAIN_FRAC = 0.7

WALKFORWARD_CSV = "/root/BlueHorseshoe/research/bb_execution_v1/walkforward.csv"


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


def sim_long_spread_fixed(close_ask, high_bid, low_bid, close_bid,
                           entry_idx, entry_price, max_hold):
    n = len(close_ask)
    if entry_idx + max_hold >= n:
        return None
    tp = entry_price * (1 + TP_PCT)
    stop = entry_price * (1 - STOP_PCT)
    risk = entry_price - stop
    for j in range(1, max_hold + 1):
        k = entry_idx + j
        if low_bid[k] <= stop:
            return -1.0
        if high_bid[k] >= tp:
            return (tp - entry_price) / risk
    exit_price = close_bid[entry_idx + max_hold]
    return (exit_price - entry_price) / risk


def sim_short_spread_fixed(close_bid, high_ask, low_ask, close_ask,
                            entry_idx, entry_price, max_hold):
    n = len(close_bid)
    if entry_idx + max_hold >= n:
        return None
    tp = entry_price * (1 - TP_PCT)
    stop = entry_price * (1 + STOP_PCT)
    risk = stop - entry_price
    for j in range(1, max_hold + 1):
        k = entry_idx + j
        if high_ask[k] >= stop:
            return -1.0
        if low_ask[k] <= tp:
            return (entry_price - tp) / risk
    exit_price = close_ask[entry_idx + max_hold]
    return (entry_price - exit_price) / risk


def stop_entry_fill_long_spread(high_ask, i, level, wait_bars):
    """Long stop-buy fills when ask rises to level."""
    n = len(high_ask)
    for w in range(1, wait_bars + 1):
        k = i + w
        if k >= n:
            return None
        if high_ask[k] >= level:
            return k
    return None


def stop_entry_fill_short_spread(low_bid, i, level, wait_bars):
    """Short stop-sell fills when bid drops to level."""
    n = len(low_bid)
    for w in range(1, wait_bars + 1):
        k = i + w
        if k >= n:
            return None
        if low_bid[k] <= level:
            return k
    return None


def expectancy_split(rs_with_ts):
    if not rs_with_ts:
        return {f"{half}_{k}": float("nan") for half in ["tr", "te"]
                for k in ["n", "mean_r", "se_r", "ci_low_r", "ci_high_r"]}
    sorted_data = sorted(rs_with_ts, key=lambda x: x[0])
    cut = int(len(sorted_data) * TRAIN_FRAC)
    halves = {"tr": sorted_data[:cut], "te": sorted_data[cut:]}
    out = {}
    for label, half in halves.items():
        rs = np.asarray([r for _, r in half], dtype=float)
        n = len(rs)
        if n == 0:
            mean_r = se = ci_low = ci_high = float("nan")
        elif n == 1:
            mean_r = float(rs[0])
            se = ci_low = ci_high = float("nan")
        else:
            mean_r = float(rs.mean())
            se = float(rs.std(ddof=1) / np.sqrt(n))
            ci_low = mean_r - 1.96 * se
            ci_high = mean_r + 1.96 * se
        out[f"{label}_n"] = n
        out[f"{label}_mean_r"] = mean_r
        out[f"{label}_se_r"] = se
        out[f"{label}_ci_low_r"] = ci_low
        out[f"{label}_ci_high_r"] = ci_high
    return out


def evaluate_cell(pair, period, std, depth, direction, variant):
    store = FxStore()
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return None

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

    rs_with_ts = []
    for i in triggers:
        i = int(i)
        if direction == "long":
            if variant == "A":
                entry = ca[i]
                r = sim_long_spread_fixed(ca, hb, lb, cb, i, entry, MAX_HOLD)
                idx = i
            else:  # C
                fill = stop_entry_fill_long_spread(ha, i, lower[i], WAIT_BARS)
                if fill is None:
                    continue
                entry = lower[i]
                r = sim_long_spread_fixed(ca, hb, lb, cb, fill, entry, MAX_HOLD)
                idx = fill
        else:  # short
            if variant == "A":
                entry = cb[i]
                r = sim_short_spread_fixed(cb, ha, la, ca, i, entry, MAX_HOLD)
                idx = i
            else:  # C
                fill = stop_entry_fill_short_spread(lb, i, upper[i], WAIT_BARS)
                if fill is None:
                    continue
                entry = upper[i]
                r = sim_short_spread_fixed(cb, ha, la, ca, fill, entry, MAX_HOLD)
                idx = fill
        if r is None:
            continue
        rs_with_ts.append((pd.Timestamp(ts[idx]), r))

    s = expectancy_split(rs_with_ts)
    s.update({
        "pair": pair, "period": period, "std": std, "depth": depth,
        "direction": direction, "variant": variant,
        "total_n": len(rs_with_ts),
    })
    return s


def main():
    out_path = "/root/BlueHorseshoe/research/bb_execution_v1/walkforward_spread.csv"
    print("Loading mid walk-forward survivors...")
    wf = pd.read_csv(WALKFORWARD_CSV)
    survivors = wf[(wf["tr_ci_low_r"] > 0.0) & (wf["te_ci_low_r"] > 0.0)
                   & (wf["tr_n"] >= 50) & (wf["te_n"] >= 30)
                   & (wf["variant"].isin(["A", "C"]))].copy()
    print(f"Found {len(survivors)} mid survivors to spread-test "
          f"(A: {(survivors['variant']=='A').sum()}, C: {(survivors['variant']=='C').sum()})\n")

    rows = []
    t0 = time.time()
    for idx, (_, r) in enumerate(survivors.iterrows(), 1):
        out = evaluate_cell(r["pair"], int(r["period"]), float(r["std"]),
                            float(r["depth"]), r["direction"], r["variant"])
        if out is not None:
            rows.append(out)
        if idx % 5 == 0 or idx == len(survivors):
            print(f"  [{idx}/{len(survivors)}] {time.time()-t0:.1f}s")

    df = pd.DataFrame(rows)
    df.to_csv(out_path, index=False)
    print(f"\nWrote {len(df)} cells to {out_path}\n")

    if df.empty:
        return

    print("=== Spread-robust survivors per variant (both halves CI_low_r > 0, tr n>=50, te n>=30) ===\n")
    for v in ["A", "C"]:
        sub = df[df["variant"] == v]
        robust = sub[(sub["tr_ci_low_r"] > 0.0) & (sub["te_ci_low_r"] > 0.0)
                     & (sub["tr_n"] >= 50) & (sub["te_n"] >= 30)]
        print(f"  Variant {v}: {len(robust)}/{len(sub)} cells")
        if not robust.empty:
            print(f"    Per-pair survivors:")
            piv = robust.groupby(["pair", "direction"]).size().unstack(fill_value=0)
            piv["total"] = piv.sum(axis=1)
            print(piv.sort_values("total", ascending=False).to_string())
            print(f"    Top 5 by te mean_R:")
            for _, r in robust.sort_values("te_mean_r", ascending=False).head(5).iterrows():
                print(f"      {r['pair']:<10} p={int(r['period'])} std={r['std']:.1f} "
                      f"depth={r['depth']:.2f} {r['direction']:<5}  "
                      f"tr: n={int(r['tr_n'])} R={r['tr_mean_r']:+.3f}  "
                      f"te: n={int(r['te_n'])} R={r['te_mean_r']:+.3f} "
                      f"CI=[{r['te_ci_low_r']:+.3f},{r['te_ci_high_r']:+.3f}]")
        print()


if __name__ == "__main__":
    main()
