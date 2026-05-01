"""Walk-forward 70/30 split for the BB trigger sweep.

Re-runs the same parameter grid as sweep_bb_triggers.py, but for each cell
splits trades chronologically by entry_ts at the 70/30 boundary and reports
train/test stats. Survivor = positive WR (>50%) on BOTH halves with CI low > 50%
on test (lenient survivor) or CI low > 50% on both (strict survivor).
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
BB_PERIODS = [10, 20, 30, 50]
BB_STDS = [1.5, 2.0, 2.5, 3.0]
DEPTHS = [0.0, 0.1, 0.25, 0.5, 0.75]
DIRECTIONS = ["long", "short"]
TRAIN_FRAC = 0.7

TP_PCT = 0.01
STOP_PCT = 0.01


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


def sim_long(close, high, low, i, max_hold):
    if i + max_hold >= len(close):
        return None
    entry = close[i]
    tp = entry * (1 + TP_PCT)
    stop = entry * (1 - STOP_PCT)
    for j in range(1, max_hold + 1):
        k = i + j
        if low[k] <= stop:
            return -1
        if high[k] >= tp:
            return +1
    return 0


def sim_short(close, high, low, i, max_hold):
    if i + max_hold >= len(close):
        return None
    entry = close[i]
    tp = entry * (1 - TP_PCT)
    stop = entry * (1 + STOP_PCT)
    for j in range(1, max_hold + 1):
        k = i + j
        if high[k] >= stop:
            return -1
        if low[k] <= tp:
            return +1
    return 0


def wilson_ci(wins: int, decisive: int) -> tuple[float, float, float]:
    if decisive == 0:
        return float("nan"), float("nan"), float("nan")
    p = wins / decisive
    se = np.sqrt(p * (1 - p) / decisive)
    return p, max(0.0, p - 1.96 * se), min(1.0, p + 1.96 * se)


def split_stats(outcomes: list[tuple[pd.Timestamp, int]]) -> dict:
    if not outcomes:
        return {f"{half}_{k}": float("nan") for half in ["tr", "te"]
                for k in ["n", "w", "l", "t", "wr", "ci_low", "ci_high"]}

    outcomes_sorted = sorted(outcomes, key=lambda x: x[0])
    cut = int(len(outcomes_sorted) * TRAIN_FRAC)
    halves = {"tr": outcomes_sorted[:cut], "te": outcomes_sorted[cut:]}

    out = {}
    for label, half in halves.items():
        rs = [r for _, r in half]
        n = len(rs)
        w = sum(1 for r in rs if r == +1)
        l = sum(1 for r in rs if r == -1)
        t = sum(1 for r in rs if r == 0)
        wr, ci_low, ci_high = wilson_ci(w, w + l)
        out[f"{label}_n"] = n
        out[f"{label}_w"] = w
        out[f"{label}_l"] = l
        out[f"{label}_t"] = t
        out[f"{label}_wr"] = wr
        out[f"{label}_ci_low"] = ci_low
        out[f"{label}_ci_high"] = ci_high
    return out


def sweep_pair(pair: str) -> list[dict]:
    store = FxStore()
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return []

    mid = ohlc_mid(raw)
    m_close = mid["close"].to_numpy(dtype=float)
    m_high = mid["high"].to_numpy(dtype=float)
    m_low = mid["low"].to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()

    rows = []
    for period in BB_PERIODS:
        for std in BB_STDS:
            bb = bollinger_bands(mid, period=period, n_std=std)
            lower = bb["lower"].to_numpy(dtype=float)
            upper = bb["upper"].to_numpy(dtype=float)
            bw = upper - lower

            for direction in DIRECTIONS:
                if direction == "long":
                    sim = sim_long
                    find = find_fresh_long
                    band = lower
                else:
                    sim = sim_short
                    find = find_fresh_short
                    band = upper

                for depth in DEPTHS:
                    triggers = find(m_close, band, bw, depth)
                    outcomes = []
                    for i in triggers:
                        r = sim(m_close, m_high, m_low, int(i), MAX_HOLD)
                        if r is None:
                            continue
                        outcomes.append((pd.Timestamp(ts[i]), r))

                    s = split_stats(outcomes)
                    s.update({
                        "pair": pair, "tf": GRANULARITY, "period": period, "std": std,
                        "depth": depth, "direction": direction,
                        "total_n": len(outcomes),
                    })
                    rows.append(s)
    return rows


def main():
    out_path = "/tmp/walkforward_bb_triggers.csv"
    print(f"Walk-forward sweep: 40 pairs × 4 periods × 4 stds × 5 depths × 2 dirs = 6400 cells")
    print(f"Split: {int(TRAIN_FRAC*100)}/{int((1-TRAIN_FRAC)*100)} per cell, by entry_ts")
    print()

    all_rows = []
    t0 = time.time()
    for p_idx, pair in enumerate(PAIRS_FULL, 1):
        rows = sweep_pair(pair)
        all_rows.extend(rows)
        print(f"  [{p_idx}/{len(PAIRS_FULL)}] {pair}  ({time.time()-t0:.1f}s)")

    df = pd.DataFrame(all_rows)
    df.to_csv(out_path, index=False)
    print(f"\nWrote {len(df)} cells to {out_path}")

    # Filter: cells that passed the original gate (looking only at the train half here
    # would be circular since cells were selected on full data — but since the original
    # gate uses full-history, what we want is "cells whose test half independently shows edge")
    if df.empty:
        return

    # Survivor 1 (lenient): WR > 50% on both halves AND test n >= 30
    surv_lenient = df[(df["tr_wr"] > 0.50) & (df["te_wr"] > 0.50) & (df["te_n"] >= 30)]
    # Survivor 2 (strict): test CI lower bound > 50%
    surv_strict = df[(df["te_ci_low"] > 0.50) & (df["te_n"] >= 30)]

    print(f"\nLenient survivors (both halves WR>50%, test n>=30): {len(surv_lenient)}/{len(df)}")
    print(f"Strict survivors (test CI lower > 50%, test n>=30):  {len(surv_strict)}/{len(df)}")

    print("\n=== Top strict survivors by test WR (test n>=50) ===")
    strict_top = df[(df["te_ci_low"] > 0.50) & (df["te_n"] >= 50)].sort_values("te_wr", ascending=False).head(20)
    for _, r in strict_top.iterrows():
        print(f"  {r['pair']:<10} period={int(r['period'])} std={r['std']} depth={r['depth']:.2f} {r['direction']:<5}  "
              f"tr: n={int(r['tr_n'])} W/L={int(r['tr_w'])}/{int(r['tr_l'])} WR={r['tr_wr']*100:.1f}% CI=[{r['tr_ci_low']*100:.1f}, {r['tr_ci_high']*100:.1f}]  "
              f"te: n={int(r['te_n'])} W/L={int(r['te_w'])}/{int(r['te_l'])} WR={r['te_wr']*100:.1f}% CI=[{r['te_ci_low']*100:.1f}, {r['te_ci_high']*100:.1f}]")

    print("\n=== Verification of original 6 high-confidence cells (n>=150 in full sweep) ===")
    targets = [
        ("CHF_JPY", 50, 1.5, 0.25, "long"),
        ("CHF_JPY", 50, 2.0, 0.10, "long"),
        ("CHF_JPY", 50, 2.0, 0.00, "long"),
        ("GBP_NZD", 50, 1.5, 0.25, "long"),
        ("AUD_CAD", 50, 1.5, 0.25, "short"),
        ("CAD_CHF", 20, 1.5, 0.00, "short"),
    ]
    for pair, period, std, depth, direction in targets:
        cell = df[(df["pair"] == pair) & (df["period"] == period) & (df["std"] == std)
                  & (df["depth"] == depth) & (df["direction"] == direction)]
        if cell.empty:
            print(f"  {pair} p={period} s={std} d={depth} {direction}: NOT FOUND")
            continue
        r = cell.iloc[0]
        survivor_strict = r["te_ci_low"] > 0.50 and r["te_n"] >= 30
        flag = "★ SURVIVOR" if survivor_strict else ("≈ lenient" if r["te_wr"] > 0.50 and r["tr_wr"] > 0.50 else "✗ FAILED")
        print(f"  {pair:<10} p={period} s={std} d={depth} {direction:<5}  "
              f"tr: n={int(r['tr_n'])} WR={r['tr_wr']*100:.1f}%  "
              f"te: n={int(r['te_n'])} WR={r['te_wr']*100:.1f}% CI=[{r['te_ci_low']*100:.1f}, {r['te_ci_high']*100:.1f}]  {flag}")


if __name__ == "__main__":
    main()
