"""SMA distance-band trigger sweep — Phase 0 coin-flip test.

Family D: price penetrates SMA ± k*ATR band. Mean-reversion-shaped, but
distinct from Bollinger (BB uses k*stdev, this uses k*ATR which is
volatility-of-range rather than volatility-of-close).

Trigger family:
  long  — close[i] < SMA[i] - k*ATR[i]. Fresh.
  short — close[i] > SMA[i] + k*ATR[i]. Fresh.

  - timeframe:  H4  (max_hold 84 bars = 2 weeks)
  - period:     20, 50, 100, 200
  - k (atr):    1.0, 1.5, 2.0, 2.5
  - atr_period: 14 (fixed)
  - direction:  long, short
  - pair:       40 OANDA majors/exotics
  - entry/exit: mid prices, 1%/1% RR, stop-first, timeout at close

  Total: 40 × 4 × 4 × 2 = 1,280 cells

CLI:
  --smoke
  --out PATH    (default: /tmp/sweep_sma_band.csv)
  --pairs LIST
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/src")

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import atr, ohlc_mid, sma


PAIRS_FULL = [
    "EUR_USD", "GBP_USD", "AUD_USD", "USD_CAD", "USD_CHF", "NZD_USD", "USD_SEK",
    "AUD_CHF", "AUD_NZD", "AUD_CAD", "EUR_AUD", "EUR_CAD", "EUR_CHF", "EUR_NZD",
    "EUR_CZK", "CAD_JPY", "CAD_CHF", "USD_JPY", "EUR_GBP", "EUR_JPY", "GBP_JPY",
    "GBP_AUD", "GBP_CAD", "GBP_CHF", "GBP_NZD", "CHF_JPY", "NZD_JPY", "AUD_JPY",
    "USD_SGD", "USD_PLN", "USD_CZK", "USD_HUF", "EUR_HUF", "EUR_PLN", "EUR_SEK",
    "NZD_CAD", "NZD_CHF", "EUR_NOK", "USD_ZAR", "USD_NOK",
]

TIMEFRAMES = {"H4": 14 * 6}
PERIODS = [20, 50, 100, 200]
K_VALUES = [1.0, 1.5, 2.0, 2.5]
ATR_PERIOD = 14
DIRECTIONS = ["long", "short"]

TP_PCT = 0.01
STOP_PCT = 0.01


def find_fresh_long(close: np.ndarray, sma_arr: np.ndarray, atr_arr: np.ndarray,
                     k: float) -> np.ndarray:
    """Long: close penetrates below SMA - k*ATR. Fresh (becomes true after not being)."""
    n = len(close)
    valid = ~np.isnan(close) & ~np.isnan(sma_arr) & ~np.isnan(atr_arr)
    lower = sma_arr - k * atr_arr
    cond = valid & (close < lower)
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def find_fresh_short(close: np.ndarray, sma_arr: np.ndarray, atr_arr: np.ndarray,
                      k: float) -> np.ndarray:
    """Short: close penetrates above SMA + k*ATR. Fresh."""
    n = len(close)
    valid = ~np.isnan(close) & ~np.isnan(sma_arr) & ~np.isnan(atr_arr)
    upper = sma_arr + k * atr_arr
    cond = valid & (close > upper)
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


def sweep_pair(pair: str, timeframe: str, max_hold: int,
               periods: list[int], k_values: list[float],
               directions: list[str]) -> list[dict]:
    store = FxStore()
    raw = store.load(pair, granularity=timeframe, include_incomplete=False)
    if raw is None or raw.empty:
        return []

    mid = ohlc_mid(raw)
    m_close = mid["close"].to_numpy(dtype=float)
    m_high = mid["high"].to_numpy(dtype=float)
    m_low = mid["low"].to_numpy(dtype=float)
    atr_arr = atr(mid, period=ATR_PERIOD).to_numpy(dtype=float)

    rows = []
    for period in periods:
        sma_arr = sma(mid, period=period).to_numpy(dtype=float)

        for direction in directions:
            find = find_fresh_long if direction == "long" else find_fresh_short
            sim = sim_long if direction == "long" else sim_short

            for k in k_values:
                triggers = find(m_close, sma_arr, atr_arr, float(k))
                n = w = l = t = 0
                for i in triggers:
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
                wr, ci_low, ci_high = wilson_ci(w, decisive)
                rows.append({
                    "pair": pair, "tf": timeframe,
                    "period": period, "k": k, "atr_period": ATR_PERIOD,
                    "direction": direction,
                    "n": n, "w": w, "l": l, "t": t,
                    "wr_decisive": wr, "ci_low": ci_low, "ci_high": ci_high,
                })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--out", default="/tmp/sweep_sma_band.csv")
    ap.add_argument("--pairs", default=None)
    args = ap.parse_args()

    if args.smoke:
        pairs = ["EUR_USD"]
        timeframes = {"H4": 14 * 6}
        periods = [20, 50]
        k_values = [1.0, 2.0]
        directions = ["long", "short"]
    else:
        pairs = args.pairs.split(",") if args.pairs else PAIRS_FULL
        timeframes = TIMEFRAMES
        periods = PERIODS
        k_values = K_VALUES
        directions = DIRECTIONS

    n_cells = len(pairs) * len(timeframes) * len(periods) * len(k_values) * len(directions)
    print(f"Sweep: {len(pairs)} pairs × {len(timeframes)} TF × {len(periods)} periods × "
          f"{len(k_values)} k × {len(directions)} dirs = {n_cells} cells")
    print(f"Output: {args.out}\n")

    all_rows = []
    t0 = time.time()
    for p_idx, pair in enumerate(pairs, 1):
        pair_t0 = time.time()
        for tf, max_hold in timeframes.items():
            rows = sweep_pair(pair, tf, max_hold, periods, k_values, directions)
            all_rows.extend(rows)
        elapsed = time.time() - pair_t0
        total_elapsed = time.time() - t0
        eta = total_elapsed / p_idx * (len(pairs) - p_idx)
        print(f"  [{p_idx}/{len(pairs)}] {pair} ({elapsed:.1f}s)  total {total_elapsed:.0f}s  ETA {eta:.0f}s")

    df = pd.DataFrame(all_rows)
    df.to_csv(args.out, index=False)
    print(f"\nWrote {len(df)} cells to {args.out}")

    if not df.empty:
        clears = df[(df["ci_low"] > 0.50) & (df["n"] >= 50)]
        print(f"Cells with n>=50 AND CI lower bound > 50%: {len(clears)}/{len(df)}")
        if not clears.empty:
            print("\nTop 20 cells by WR (with n>=50 and CI lower bound > 50%):")
            top = clears.sort_values("wr_decisive", ascending=False).head(20)
            for _, r in top.iterrows():
                print(f"  {r['pair']:<10} {r['tf']:<3} p={int(r['period']):<3} "
                      f"k={r['k']:.1f} {r['direction']:<5}  "
                      f"n={int(r['n'])} W/L/T={int(r['w'])}/{int(r['l'])}/{int(r['t'])}  "
                      f"WR={r['wr_decisive']*100:.1f}%  "
                      f"CI=[{r['ci_low']*100:.1f}, {r['ci_high']*100:.1f}]")


if __name__ == "__main__":
    main()
