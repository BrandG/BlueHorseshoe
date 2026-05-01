"""Walk-forward 70/30 split for the BB confirmation-bar sweep.

Same parameter grid as sweep_bb_confirm.py (38,400 cells with confirm dimension).
Splits each cell's trades chronologically by entry_ts at the 70/30 boundary
and reports train/test stats. Identifies survivors (positive both halves with
test CI > 50%).
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
CONFIRMS = [
    ("none", None),
    ("bare", None),
    ("rise", 0.000),
    ("rise", 0.001),
    ("rise", 0.0025),
    ("rise", 0.005),
]
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


def maybe_enter_long(close, lower, i, confirm):
    if confirm[0] == "none":
        return i
    if i + 1 >= len(close):
        return None
    if confirm[0] == "bare":
        return i + 1 if close[i + 1] > lower[i + 1] else None
    return i + 1 if close[i + 1] >= close[i] * (1 + confirm[1]) else None


def maybe_enter_short(close, upper, i, confirm):
    if confirm[0] == "none":
        return i
    if i + 1 >= len(close):
        return None
    if confirm[0] == "bare":
        return i + 1 if close[i + 1] < upper[i + 1] else None
    return i + 1 if close[i + 1] <= close[i] * (1 - confirm[1]) else None


def wilson_ci(wins: int, decisive: int) -> tuple[float, float, float]:
    if decisive == 0:
        return float("nan"), float("nan"), float("nan")
    p = wins / decisive
    se = np.sqrt(p * (1 - p) / decisive)
    return p, max(0.0, p - 1.96 * se), min(1.0, p + 1.96 * se)


def confirm_label(c) -> str:
    if c[0] == "none":
        return "none"
    if c[0] == "bare":
        return "bare"
    return f"rise_{c[1]*100:.2f}%"


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
                for depth in DEPTHS:
                    if direction == "long":
                        triggers = find_fresh_long(m_close, lower, bw, depth)
                    else:
                        triggers = find_fresh_short(m_close, upper, bw, depth)

                    for confirm in CONFIRMS:
                        outcomes = []
                        for i in triggers:
                            if direction == "long":
                                entry_idx = maybe_enter_long(m_close, lower, int(i), confirm)
                            else:
                                entry_idx = maybe_enter_short(m_close, upper, int(i), confirm)
                            if entry_idx is None:
                                continue
                            if direction == "long":
                                r = sim_long(m_close, m_high, m_low, entry_idx, MAX_HOLD)
                            else:
                                r = sim_short(m_close, m_high, m_low, entry_idx, MAX_HOLD)
                            if r is None:
                                continue
                            outcomes.append((pd.Timestamp(ts[entry_idx]), r))

                        s = split_stats(outcomes)
                        s.update({
                            "pair": pair, "tf": GRANULARITY, "period": period, "std": std,
                            "depth": depth, "direction": direction,
                            "confirm": confirm_label(confirm),
                            "total_n": len(outcomes),
                        })
                        rows.append(s)
    return rows


def main():
    out_path = "/tmp/walkforward_bb_confirm.csv"
    n_cells = (len(PAIRS_FULL) * len(BB_PERIODS) * len(BB_STDS)
               * len(DEPTHS) * len(DIRECTIONS) * len(CONFIRMS))
    print(f"Walk-forward: {n_cells} cells, 70/30 split per cell\n")

    all_rows = []
    t0 = time.time()
    for p_idx, pair in enumerate(PAIRS_FULL, 1):
        rows = sweep_pair(pair)
        all_rows.extend(rows)
        elapsed = time.time() - t0
        eta = elapsed / p_idx * (len(PAIRS_FULL) - p_idx)
        print(f"  [{p_idx}/{len(PAIRS_FULL)}] {pair}  total {elapsed:.0f}s  ETA {eta:.0f}s")

    df = pd.DataFrame(all_rows)
    df.to_csv(out_path, index=False)
    print(f"\nWrote {len(df)} cells to {out_path}\n")

    if df.empty:
        return

    # Strict survivors: train_wr > 50% AND test_ci_low > 50% AND test_n >= 30
    surv = df[(df["tr_wr"] > 0.50) & (df["te_ci_low"] > 0.50) & (df["te_n"] >= 30)].copy()
    print(f"Strict survivors (train WR>50%, test CI lower>50%, test n>=30): {len(surv)}/{len(df)}")

    # Robust survivors: stricter — train AND test both have CI lower > 50%
    robust = df[(df["tr_ci_low"] > 0.50) & (df["te_ci_low"] > 0.50)
                & (df["tr_n"] >= 50) & (df["te_n"] >= 30)].copy()
    print(f"Robust survivors (BOTH halves CI lower>50%, tr_n>=50, te_n>=30): {len(robust)}/{len(df)}")

    if not robust.empty:
        print("\n=== Robust survivors sorted by test WR ===")
        for _, r in robust.sort_values("te_wr", ascending=False).iterrows():
            print(f"  {r['pair']:<10} p={int(r['period'])} s={r['std']} d={r['depth']:.2f} "
                  f"{r['direction']:<5} confirm={r['confirm']:<11}  "
                  f"tr: n={int(r['tr_n'])} WR={r['tr_wr']*100:.1f}% CI=[{r['tr_ci_low']*100:.1f},{r['tr_ci_high']*100:.1f}]  "
                  f"te: n={int(r['te_n'])} WR={r['te_wr']*100:.1f}% CI=[{r['te_ci_low']*100:.1f},{r['te_ci_high']*100:.1f}]")

    # Robust pairs: which instruments appear at all?
    if not robust.empty:
        print("\n=== Robust pairs (count of robust cells per pair) ===")
        print(robust["pair"].value_counts().to_string())
        print("\n=== Robust by confirm variant ===")
        print(robust["confirm"].value_counts().to_string())

    # Verification of original 6 + new USD_JPY + NZD_CHF cells
    targets = [
        ("CHF_JPY", 50, 1.5, 0.25, "long", "none"),
        ("CHF_JPY", 50, 2.0, 0.10, "long", "none"),
        ("CHF_JPY", 50, 2.0, 0.00, "long", "none"),
        ("GBP_NZD", 50, 1.5, 0.25, "long", "none"),
        ("AUD_CAD", 50, 1.5, 0.25, "short", "none"),
        ("CAD_CHF", 20, 1.5, 0.00, "short", "none"),
        ("USD_JPY", 50, 2.0, 0.00, "long", "rise_0.00%"),
        ("USD_JPY", 50, 1.5, 0.10, "long", "rise_0.00%"),
        ("CAD_CHF", 30, 1.5, 0.00, "short", "bare"),
        ("NZD_CHF", 10, 2.0, 0.00, "short", "bare"),
    ]
    print("\n=== Verification of 10 high-confidence cells from full-history sweep ===")
    for pair, period, std, depth, direction, confirm in targets:
        cell = df[(df["pair"] == pair) & (df["period"] == period) & (df["std"] == std)
                  & (df["depth"] == depth) & (df["direction"] == direction)
                  & (df["confirm"] == confirm)]
        if cell.empty:
            print(f"  {pair} p={period} s={std} d={depth} {direction} confirm={confirm}: NOT FOUND")
            continue
        r = cell.iloc[0]
        is_robust = (r["tr_ci_low"] > 0.50) and (r["te_ci_low"] > 0.50) and r["tr_n"] >= 50 and r["te_n"] >= 30
        is_strict = (r["tr_wr"] > 0.50) and (r["te_ci_low"] > 0.50)
        flag = "★★ ROBUST" if is_robust else ("★ STRICT" if is_strict else (
            "≈ lenient" if r["tr_wr"] > 0.50 and r["te_wr"] > 0.50 else "✗ FAIL"))
        print(f"  {pair:<10} p={period} s={std} d={depth} {direction:<5} confirm={confirm:<11}  "
              f"tr: n={int(r['tr_n'])} WR={r['tr_wr']*100:.1f}%  "
              f"te: n={int(r['te_n'])} WR={r['te_wr']*100:.1f}% CI=[{r['te_ci_low']*100:.1f},{r['te_ci_high']*100:.1f}]  {flag}")


if __name__ == "__main__":
    main()
