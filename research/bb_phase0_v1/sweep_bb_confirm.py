"""BB trigger sweep with confirmation-bar variants.

Same parameter grid as sweep_bb_triggers.py, plus a confirmation dimension.
For each (pair, period, std, depth, direction) combo, additionally varies
the confirmation rule applied at bar i+1 after the trigger fires at bar i.

Confirmation variants:
  - none:       enter at close of trigger bar (current baseline)
  - bare:       enter at close of bar i+1 only if it closes back inside the band
  - rise_0.0%:  enter at close of bar i+1 only if close[i+1] >= close[i] (longs);
                close[i+1] <= close[i] (shorts)
  - rise_0.1%:  same idea, requires 0.1% rise (longs) / fall (shorts)
  - rise_0.25%
  - rise_0.5%

Entry shifts from trigger bar i (no confirm) to bar i+1 (any confirm).
Cell count: 40 × 4 × 4 × 5 × 2 × 6 = 38,400.

Mid prices, fixed 1%/1% RR, max_hold = 84 H4 bars (2 weeks).
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
    """Decide entry index (or None to skip)."""
    if confirm[0] == "none":
        return i
    if i + 1 >= len(close):
        return None
    if confirm[0] == "bare":
        if close[i + 1] > lower[i + 1]:
            return i + 1
        return None
    # rise variant
    if close[i + 1] >= close[i] * (1 + confirm[1]):
        return i + 1
    return None


def maybe_enter_short(close, upper, i, confirm):
    if confirm[0] == "none":
        return i
    if i + 1 >= len(close):
        return None
    if confirm[0] == "bare":
        if close[i + 1] < upper[i + 1]:
            return i + 1
        return None
    if close[i + 1] <= close[i] * (1 - confirm[1]):
        return i + 1
    return None


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


def sweep_pair(pair: str) -> list[dict]:
    store = FxStore()
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return []

    mid = ohlc_mid(raw)
    m_close = mid["close"].to_numpy(dtype=float)
    m_high = mid["high"].to_numpy(dtype=float)
    m_low = mid["low"].to_numpy(dtype=float)

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
                        n = w = l = t = 0
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
                            n += 1
                            if r == +1: w += 1
                            elif r == -1: l += 1
                            else: t += 1
                        decisive = w + l
                        wr, ci_low, ci_high = wilson_ci(w, decisive)
                        rows.append({
                            "pair": pair, "tf": GRANULARITY, "period": period, "std": std,
                            "depth": depth, "direction": direction,
                            "confirm": confirm_label(confirm),
                            "n": n, "w": w, "l": l, "t": t,
                            "wr_decisive": wr, "ci_low": ci_low, "ci_high": ci_high,
                        })
    return rows


def main():
    out_path = "/tmp/sweep_bb_confirm.csv"
    n_cells = (len(PAIRS_FULL) * len(BB_PERIODS) * len(BB_STDS)
               * len(DEPTHS) * len(DIRECTIONS) * len(CONFIRMS))
    print(f"Sweep: {len(PAIRS_FULL)} pairs × {len(BB_PERIODS)} periods × {len(BB_STDS)} stds "
          f"× {len(DEPTHS)} depths × {len(DIRECTIONS)} dirs × {len(CONFIRMS)} confirm = {n_cells} cells")
    print(f"Output: {out_path}")
    print()

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
    print(f"\nWrote {len(df)} cells to {out_path}")

    if df.empty:
        return

    # High-confidence subset (n>=150 AND CI lower > 55%)
    strong = df[(df["n"] >= 150) & (df["ci_low"] > 0.55)].copy()
    print(f"\nHigh-confidence cells (n>=150, CI lower > 55%): {len(strong)}")
    if not strong.empty:
        print("\nTop 30 by WR:")
        for _, r in strong.sort_values("wr_decisive", ascending=False).head(30).iterrows():
            print(f"  {r['pair']:<10} period={int(r['period'])} std={r['std']} "
                  f"depth={r['depth']:.2f} {r['direction']:<5} confirm={r['confirm']:<11}  "
                  f"n={int(r['n'])} W/L/T={int(r['w'])}/{int(r['l'])}/{int(r['t'])}  "
                  f"WR={r['wr_decisive']*100:.1f}% CI=[{r['ci_low']*100:.1f}, {r['ci_high']*100:.1f}]")

    # Summary by confirm variant: how many high-confidence cells does each generate?
    print("\nHigh-confidence cell count by confirm variant:")
    print(strong["confirm"].value_counts().to_string() if not strong.empty else "(none)")
    print("\nMedian WR by confirm variant (n>=150 cells only):")
    big = df[df["n"] >= 150]
    print(big.groupby("confirm")["wr_decisive"].agg(["count", "median", "mean"]).to_string())


if __name__ == "__main__":
    main()
