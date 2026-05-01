"""Walk-forward BB sweep with shape (period-state) filter dimension.

Adds a shape filter applied at the trigger bar. Seven shape variants:

  - any:            no shape filter (baseline)
  - bw_contracting: bandwidth shrinking (bw[i] / bw[i-10] < 0.9)
  - bw_flat:        bandwidth stable (0.9 <= ratio <= 1.1)
  - bw_expanding:   bandwidth widening (ratio > 1.1)
  - mid_down:       middle band sloping down (mid[i] vs mid[i-10] change < -0.5%)
  - mid_flat:       middle band roughly flat (|change| <= 0.5%)
  - mid_up:         middle band sloping up (change > 0.5%)

Lookback for shape evaluation: 10 H4 bars (~40 hours).

Cell count: 40 pairs × 4 periods × 4 stds × 5 depths × 2 dirs × 6 confirm × 7 shape
            = 268,800 cells. Memory-light (counters only, no trade lists).

Walk-forward 70/30 split per cell. Robust survivor = both halves CI lower > 50%
with tr_n>=50 AND te_n>=30. Bonferroni at this scale: alpha = 0.05 / 268,800 ≈ 1.9e-7.
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
    ("none", None), ("bare", None), ("rise", 0.000),
    ("rise", 0.001), ("rise", 0.0025), ("rise", 0.005),
]
SHAPES = ["any", "bw_contracting", "bw_flat", "bw_expanding",
          "mid_down", "mid_flat", "mid_up"]
SHAPE_LOOKBACK = 10
BW_LO_THRESH = 0.9
BW_HI_THRESH = 1.1
MID_THRESH = 0.005
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


def shape_at_bar(i, bw_ratio, mid_change, shape):
    """Return True if the trigger at bar i passes the shape filter."""
    if shape == "any":
        return True
    if i < SHAPE_LOOKBACK:
        return False  # not enough history
    if shape == "bw_contracting":
        return bw_ratio[i] < BW_LO_THRESH
    if shape == "bw_flat":
        return BW_LO_THRESH <= bw_ratio[i] <= BW_HI_THRESH
    if shape == "bw_expanding":
        return bw_ratio[i] > BW_HI_THRESH
    if shape == "mid_down":
        return mid_change[i] < -MID_THRESH
    if shape == "mid_flat":
        return abs(mid_change[i]) <= MID_THRESH
    if shape == "mid_up":
        return mid_change[i] > MID_THRESH
    return True


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


def split_stats(outcomes):
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
            middle = bb["middle"].to_numpy(dtype=float)
            bw = upper - lower

            # Shape state arrays
            bw_lag = np.roll(bw, SHAPE_LOOKBACK)
            with np.errstate(divide="ignore", invalid="ignore"):
                bw_ratio = np.where(bw_lag > 0, bw / bw_lag, np.nan)
            mid_lag = np.roll(middle, SHAPE_LOOKBACK)
            with np.errstate(divide="ignore", invalid="ignore"):
                mid_change = np.where(mid_lag > 0, (middle - mid_lag) / mid_lag, np.nan)

            for direction in DIRECTIONS:
                for depth in DEPTHS:
                    if direction == "long":
                        triggers = find_fresh_long(m_close, lower, bw, depth)
                    else:
                        triggers = find_fresh_short(m_close, upper, bw, depth)

                    for confirm in CONFIRMS:
                        # Per-(confirm) cache: pre-resolve entry indices and outcomes for each trigger
                        entries = []
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
                            entries.append((int(i), entry_idx, r))

                        for shape in SHAPES:
                            outcomes = []
                            for (trigger_i, entry_idx, r) in entries:
                                if not shape_at_bar(trigger_i, bw_ratio, mid_change, shape):
                                    continue
                                outcomes.append((pd.Timestamp(ts[entry_idx]), r))

                            s = split_stats(outcomes)
                            s.update({
                                "pair": pair, "tf": GRANULARITY, "period": period, "std": std,
                                "depth": depth, "direction": direction,
                                "confirm": confirm_label(confirm), "shape": shape,
                                "total_n": len(outcomes),
                            })
                            rows.append(s)
    return rows


def main():
    out_path = "/tmp/walkforward_bb_shape.csv"
    n_cells = (len(PAIRS_FULL) * len(BB_PERIODS) * len(BB_STDS)
               * len(DEPTHS) * len(DIRECTIONS) * len(CONFIRMS) * len(SHAPES))
    print(f"Walk-forward shape sweep: {n_cells} cells, 70/30 split per cell\n")

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

    # Robust survivors
    robust = df[(df["tr_ci_low"] > 0.50) & (df["te_ci_low"] > 0.50)
                & (df["tr_n"] >= 50) & (df["te_n"] >= 30)].copy()
    print(f"Robust survivors (BOTH halves CI low > 50%, tr_n>=50, te_n>=30): {len(robust)}/{len(df)}")

    # By shape variant
    print("\nRobust cells by shape variant:")
    print(robust["shape"].value_counts().to_string() if not robust.empty else "(none)")

    # Compare: shape!=any robust cells vs shape==any
    any_robust = robust[robust["shape"] == "any"]
    nonany_robust = robust[robust["shape"] != "any"]
    print(f"\nShape=any robust: {len(any_robust)}")
    print(f"Shape!=any robust: {len(nonany_robust)}")

    # Top robust by test WR (filtered to te_n >= 50 for credibility)
    print("\n=== Top 30 robust cells (te_n >= 50) sorted by test WR ===")
    big = robust[robust["te_n"] >= 50].sort_values("te_wr", ascending=False).head(30)
    for _, r in big.iterrows():
        print(f"  {r['pair']:<10} p={int(r['period'])} s={r['std']} d={r['depth']:.2f} {r['direction']:<5} "
              f"confirm={r['confirm']:<11} shape={r['shape']:<15}  "
              f"tr: n={int(r['tr_n'])} WR={r['tr_wr']*100:.1f}%  "
              f"te: n={int(r['te_n'])} WR={r['te_wr']*100:.1f}% CI=[{r['te_ci_low']*100:.1f},{r['te_ci_high']*100:.1f}]")

    # For each of the previously robust cells (without shape), find best shape variant
    print("\n=== Did shape filter improve any of the 10 known cells? ===")
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
    for pair, period, std, depth, direction, confirm in targets:
        cells = df[(df["pair"] == pair) & (df["period"] == period) & (df["std"] == std)
                   & (df["depth"] == depth) & (df["direction"] == direction)
                   & (df["confirm"] == confirm)]
        if cells.empty:
            continue
        baseline = cells[cells["shape"] == "any"]
        if baseline.empty:
            continue
        b = baseline.iloc[0]
        baseline_te_wr = b["te_wr"]
        baseline_te_n = int(b["te_n"])
        # Best shape (max te_wr with te_n >= 30)
        candidates = cells[(cells["shape"] != "any") & (cells["te_n"] >= 30)]
        if candidates.empty:
            best = None
        else:
            best = candidates.sort_values("te_wr", ascending=False).iloc[0]
        print(f"\n  {pair} p={period} s={std} d={depth} {direction} confirm={confirm}:")
        print(f"    baseline (any):        te n={baseline_te_n} WR={baseline_te_wr*100:.1f}%")
        if best is not None:
            print(f"    best shape ({best['shape']:<15}): te n={int(best['te_n'])} WR={best['te_wr']*100:.1f}% "
                  f"CI=[{best['te_ci_low']*100:.1f},{best['te_ci_high']*100:.1f}]  "
                  f"delta={(best['te_wr']-baseline_te_wr)*100:+.1f}pp")


if __name__ == "__main__":
    main()
