"""MACD trigger parameter sweep — Phase 0, first pass.

Mid prices, fixed 1%/1% RR, full 40-pair universe, both directions.
NO spread, NO walk-forward, NO CI gates, NO pair clustering at output.

This is the "does MACD predict anything in this data?" question, presented
without filters so we can see the raw shape of the result.

Trigger families:
  signal_cross — MACD line crosses signal line (long: above, short: below).
  zero_cross   — MACD line crosses zero (long: above, short: below).

Parameter grid:
  - timeframe:  H4  (max_hold 84 bars)
  - (fast, slow): (6,13), (8,17), (12,26), (18,39), (24,52)   — 5 combos
  - signal:     5, 9, 13                                       — 3 values
  - trigger:    signal_cross, zero_cross
  - direction:  long, short
  - pair:       40 OANDA majors/exotics
  Total: 5 × 3 × 2 × 2 × 40 = 2,400 cells

Sim (identical to BB / stoch Phase 0):
  - entry at trigger bar's close_mid
  - TP at entry × (1 ± 0.01) checked against high_mid / low_mid
  - stop at entry × (1 ∓ 0.01) checked stop-first per bar
  - timeout exit at close_mid at i + max_hold

Output: CSV with one row per cell; raw WR, no Wilson CI, no filtering.
Console summary shows the unfiltered distribution.

CLI:
  --smoke         Reduced grid (1 pair, 1 fast/slow combo, 1 signal, 2 triggers, 2 dirs)
  --out PATH      Output CSV (default /tmp/sweep_macd_triggers.csv)
  --pairs LIST    Comma-separated pair subset
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/src")

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import macd, ohlc_mid


PAIRS_FULL = [
    "EUR_USD", "GBP_USD", "AUD_USD", "USD_CAD", "USD_CHF", "NZD_USD", "USD_SEK",
    "AUD_CHF", "AUD_NZD", "AUD_CAD", "EUR_AUD", "EUR_CAD", "EUR_CHF", "EUR_NZD",
    "EUR_CZK", "CAD_JPY", "CAD_CHF", "USD_JPY", "EUR_GBP", "EUR_JPY", "GBP_JPY",
    "GBP_AUD", "GBP_CAD", "GBP_CHF", "GBP_NZD", "CHF_JPY", "NZD_JPY", "AUD_JPY",
    "USD_SGD", "USD_PLN", "USD_CZK", "USD_HUF", "EUR_HUF", "EUR_PLN", "EUR_SEK",
    "NZD_CAD", "NZD_CHF", "EUR_NOK", "USD_ZAR", "USD_NOK",
]

TIMEFRAMES = {"H4": 14 * 6}
FAST_SLOW = [(6, 13), (8, 17), (12, 26), (18, 39), (24, 52)]
SIGNAL_PERIODS = [5, 9, 13]
TRIGGERS = ["signal_cross", "zero_cross"]
DIRECTIONS = ["long", "short"]

TP_PCT = 0.01
STOP_PCT = 0.01


def find_signal_cross_long(macd_arr: np.ndarray, signal_arr: np.ndarray) -> np.ndarray:
    """MACD crosses up through signal: macd[i] > signal[i] AND macd[i-1] <= signal[i-1]."""
    n = len(macd_arr)
    if n < 2:
        return np.array([], dtype=int)
    above = macd_arr > signal_arr
    fresh = above & ~np.roll(above, 1)
    fresh[0] = False
    fresh[np.isnan(macd_arr) | np.isnan(signal_arr)] = False
    return np.where(fresh)[0]


def find_signal_cross_short(macd_arr: np.ndarray, signal_arr: np.ndarray) -> np.ndarray:
    n = len(macd_arr)
    if n < 2:
        return np.array([], dtype=int)
    below = macd_arr < signal_arr
    fresh = below & ~np.roll(below, 1)
    fresh[0] = False
    fresh[np.isnan(macd_arr) | np.isnan(signal_arr)] = False
    return np.where(fresh)[0]


def find_zero_cross_long(macd_arr: np.ndarray) -> np.ndarray:
    n = len(macd_arr)
    if n < 2:
        return np.array([], dtype=int)
    above = macd_arr > 0
    fresh = above & ~np.roll(above, 1)
    fresh[0] = False
    fresh[np.isnan(macd_arr)] = False
    return np.where(fresh)[0]


def find_zero_cross_short(macd_arr: np.ndarray) -> np.ndarray:
    n = len(macd_arr)
    if n < 2:
        return np.array([], dtype=int)
    below = macd_arr < 0
    fresh = below & ~np.roll(below, 1)
    fresh[0] = False
    fresh[np.isnan(macd_arr)] = False
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


def sweep_pair(pair: str, timeframe: str, max_hold: int,
               fast_slow: list[tuple[int, int]],
               signals: list[int],
               triggers: list[str],
               directions: list[str]) -> list[dict]:
    store = FxStore()
    raw = store.load(pair, granularity=timeframe, include_incomplete=False)
    if raw is None or raw.empty:
        return []

    mid = ohlc_mid(raw)
    m_close = mid["close"].to_numpy(dtype=float)
    m_high = mid["high"].to_numpy(dtype=float)
    m_low = mid["low"].to_numpy(dtype=float)

    rows = []
    for fast, slow in fast_slow:
        for signal in signals:
            df_macd = macd(mid, fast=fast, slow=slow, signal=signal)
            macd_arr = df_macd["macd"].to_numpy(dtype=float)
            signal_arr = df_macd["signal"].to_numpy(dtype=float)

            for trigger in triggers:
                for direction in directions:
                    if trigger == "signal_cross":
                        find = (find_signal_cross_long if direction == "long"
                                else find_signal_cross_short)
                        triggers_idx = find(macd_arr, signal_arr)
                    else:  # zero_cross
                        find = (find_zero_cross_long if direction == "long"
                                else find_zero_cross_short)
                        triggers_idx = find(macd_arr)

                    sim = sim_long if direction == "long" else sim_short
                    n = w = l = t = 0
                    for i in triggers_idx:
                        r = sim(m_close, m_high, m_low, int(i), max_hold)
                        if r is None:
                            continue
                        n += 1
                        if r == +1:
                            w += 1
                        elif r == -1:
                            l += 1
                        else:
                            t += 1
                    decisive = w + l
                    wr = (w / decisive) if decisive > 0 else float("nan")
                    rows.append({
                        "pair": pair, "tf": timeframe,
                        "fast": fast, "slow": slow, "signal": signal,
                        "trigger": trigger, "direction": direction,
                        "n": n, "w": w, "l": l, "t": t,
                        "wr_decisive": wr,
                    })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--out", default="/tmp/sweep_macd_triggers.csv")
    ap.add_argument("--pairs", default=None)
    args = ap.parse_args()

    if args.smoke:
        pairs = ["EUR_USD"]
        timeframes = {"H4": 14 * 6}
        fast_slow = [(12, 26)]
        signals = [9]
        triggers = ["signal_cross", "zero_cross"]
        directions = ["long", "short"]
    else:
        pairs = args.pairs.split(",") if args.pairs else PAIRS_FULL
        timeframes = TIMEFRAMES
        fast_slow = FAST_SLOW
        signals = SIGNAL_PERIODS
        triggers = TRIGGERS
        directions = DIRECTIONS

    n_cells = (len(pairs) * len(timeframes) * len(fast_slow) * len(signals)
               * len(triggers) * len(directions))
    print(f"Sweep: {len(pairs)} pairs × {len(timeframes)} TF × {len(fast_slow)} fast/slow × "
          f"{len(signals)} signal × {len(triggers)} triggers × {len(directions)} dirs "
          f"= {n_cells} cells")
    print(f"Output: {args.out}")
    print()

    all_rows = []
    t0 = time.time()
    for p_idx, pair in enumerate(pairs, 1):
        pair_t0 = time.time()
        for tf, max_hold in timeframes.items():
            rows = sweep_pair(pair, tf, max_hold, fast_slow, signals, triggers, directions)
            all_rows.extend(rows)
        elapsed = time.time() - pair_t0
        total_elapsed = time.time() - t0
        eta = total_elapsed / p_idx * (len(pairs) - p_idx)
        print(f"  [{p_idx}/{len(pairs)}] {pair} ({elapsed:.1f}s)  total {total_elapsed:.0f}s  ETA {eta:.0f}s")

    df = pd.DataFrame(all_rows)
    df.to_csv(args.out, index=False)
    print(f"\nWrote {len(df)} cells to {args.out}\n")

    if df.empty:
        return

    # Raw shape — no filters, no clusters, no gates.
    valid = df[df["n"] > 0].copy()
    print(f"=== Raw distribution across all {len(valid)} cells with at least 1 trade ===")
    print(f"  WR_decisive mean:   {valid['wr_decisive'].mean()*100:.2f}%")
    print(f"  WR_decisive median: {valid['wr_decisive'].median()*100:.2f}%")
    print(f"  WR_decisive stdev:  {valid['wr_decisive'].std()*100:.2f}pp")
    print(f"  Total trades:       {valid['n'].sum():,}")
    print(f"  Median trades/cell: {valid['n'].median():.0f}")

    # Histogram-style WR breakdown
    bins = [0, 0.40, 0.45, 0.475, 0.50, 0.525, 0.55, 0.60, 1.0]
    labels = ["<40%", "40-45%", "45-47.5%", "47.5-50%", "50-52.5%", "52.5-55%", "55-60%", ">=60%"]
    valid["bucket"] = pd.cut(valid["wr_decisive"], bins=bins, labels=labels, include_lowest=True)
    print("\n  WR bucket distribution:")
    print(valid["bucket"].value_counts().reindex(labels).to_string())

    # By trigger × direction (to see if the average tilts at the family level)
    print("\n=== Mean WR by trigger × direction (no filtering) ===")
    grp = valid.groupby(["trigger", "direction"]).agg(
        n_cells=("wr_decisive", "size"),
        mean_wr=("wr_decisive", "mean"),
        median_wr=("wr_decisive", "median"),
        total_trades=("n", "sum"),
    )
    grp["mean_wr"] = (grp["mean_wr"] * 100).round(2)
    grp["median_wr"] = (grp["median_wr"] * 100).round(2)
    print(grp.to_string())

    # By (fast, slow, signal) — to see if any param family stands out
    print("\n=== Mean WR by (fast, slow, signal) parameter family ===")
    grp2 = valid.groupby(["fast", "slow", "signal"]).agg(
        n_cells=("wr_decisive", "size"),
        mean_wr=("wr_decisive", "mean"),
        median_wr=("wr_decisive", "median"),
        total_trades=("n", "sum"),
    )
    grp2["mean_wr"] = (grp2["mean_wr"] * 100).round(2)
    grp2["median_wr"] = (grp2["median_wr"] * 100).round(2)
    print(grp2.to_string())

    # Top 30 cells by WR (n >= 100 to filter out tiny samples that aren't meaningful;
    # this is sample-size sanity, NOT a statistical gate)
    print("\n=== Top 30 cells by WR (n >= 100, just to skip noise from tiny samples) ===")
    top = valid[valid["n"] >= 100].sort_values("wr_decisive", ascending=False).head(30)
    for _, r in top.iterrows():
        print(f"  {r['pair']:<10} {r['tf']:<3} f={int(r['fast']):<2} s={int(r['slow']):<2} "
              f"sig={int(r['signal']):<2} {r['trigger']:<13} {r['direction']:<5}  "
              f"n={int(r['n']):>5} W/L/T={int(r['w'])}/{int(r['l'])}/{int(r['t'])}  "
              f"WR={r['wr_decisive']*100:.1f}%")

    # Bottom 10 — to see whether the negative tail is symmetric (sanity check)
    print("\n=== Bottom 10 cells by WR (n >= 100) ===")
    bot = valid[valid["n"] >= 100].sort_values("wr_decisive", ascending=True).head(10)
    for _, r in bot.iterrows():
        print(f"  {r['pair']:<10} {r['tf']:<3} f={int(r['fast']):<2} s={int(r['slow']):<2} "
              f"sig={int(r['signal']):<2} {r['trigger']:<13} {r['direction']:<5}  "
              f"n={int(r['n']):>5} W/L/T={int(r['w'])}/{int(r['l'])}/{int(r['t'])}  "
              f"WR={r['wr_decisive']*100:.1f}%")


if __name__ == "__main__":
    main()
