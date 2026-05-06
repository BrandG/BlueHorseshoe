"""SMA two-MA crossover trigger sweep — Phase 0 coin-flip test.

Family C: fast SMA crosses through slow SMA (golden/death cross).

Trigger family:
  long  (golden) — fast[i-1] <= slow[i-1] AND fast[i] > slow[i]. Fresh.
  short (death)  — fast[i-1] >= slow[i-1] AND fast[i] < slow[i]. Fresh.

  - timeframe: H4  (max_hold 84 bars = 2 weeks)
  - fast/slow: pairs from {(10,50), (10,100), (10,200),
                            (20,50), (20,100), (20,200),
                            (50,100), (50,200), (100,200)}
  - direction: long, short
  - pair:      40 OANDA majors/exotics
  - entry/exit: mid prices, 1%/1% RR, stop-first, timeout at close

  Total: 40 × 9 × 2 = 720 cells

CLI:
  --smoke
  --out PATH    (default: /tmp/sweep_sma_cross.csv)
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
from bh_ftmo.indicators import ohlc_mid, sma


PAIRS_FULL = [
    "EUR_USD", "GBP_USD", "AUD_USD", "USD_CAD", "USD_CHF", "NZD_USD", "USD_SEK",
    "AUD_CHF", "AUD_NZD", "AUD_CAD", "EUR_AUD", "EUR_CAD", "EUR_CHF", "EUR_NZD",
    "EUR_CZK", "CAD_JPY", "CAD_CHF", "USD_JPY", "EUR_GBP", "EUR_JPY", "GBP_JPY",
    "GBP_AUD", "GBP_CAD", "GBP_CHF", "GBP_NZD", "CHF_JPY", "NZD_JPY", "AUD_JPY",
    "USD_SGD", "USD_PLN", "USD_CZK", "USD_HUF", "EUR_HUF", "EUR_PLN", "EUR_SEK",
    "NZD_CAD", "NZD_CHF", "EUR_NOK", "USD_ZAR", "USD_NOK",
]

TIMEFRAMES = {"H4": 14 * 6}
PAIR_GRID = [
    (10, 50), (10, 100), (10, 200),
    (20, 50), (20, 100), (20, 200),
    (50, 100), (50, 200),
    (100, 200),
]
DIRECTIONS = ["long", "short"]

TP_PCT = 0.01
STOP_PCT = 0.01


def find_fresh_golden(fast: np.ndarray, slow: np.ndarray) -> np.ndarray:
    """Long: fast crosses above slow. Fresh."""
    n = len(fast)
    valid = ~np.isnan(fast) & ~np.isnan(slow)
    cond = np.zeros(n, dtype=bool)
    cond[1:] = (
        valid[1:] & valid[:-1]
        & (fast[1:] > slow[1:])
        & (fast[:-1] <= slow[:-1])
    )
    return np.where(cond)[0]


def find_fresh_death(fast: np.ndarray, slow: np.ndarray) -> np.ndarray:
    """Short: fast crosses below slow. Fresh."""
    n = len(fast)
    valid = ~np.isnan(fast) & ~np.isnan(slow)
    cond = np.zeros(n, dtype=bool)
    cond[1:] = (
        valid[1:] & valid[:-1]
        & (fast[1:] < slow[1:])
        & (fast[:-1] >= slow[:-1])
    )
    return np.where(cond)[0]


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
               pair_grid: list[tuple[int, int]],
               directions: list[str]) -> list[dict]:
    store = FxStore()
    raw = store.load(pair, granularity=timeframe, include_incomplete=False)
    if raw is None or raw.empty:
        return []

    mid = ohlc_mid(raw)
    m_close = mid["close"].to_numpy(dtype=float)
    m_high = mid["high"].to_numpy(dtype=float)
    m_low = mid["low"].to_numpy(dtype=float)

    sma_cache = {}
    rows = []
    for fast_p, slow_p in pair_grid:
        if fast_p not in sma_cache:
            sma_cache[fast_p] = sma(mid, period=fast_p).to_numpy(dtype=float)
        if slow_p not in sma_cache:
            sma_cache[slow_p] = sma(mid, period=slow_p).to_numpy(dtype=float)
        fast = sma_cache[fast_p]
        slow = sma_cache[slow_p]

        for direction in directions:
            if direction == "long":
                triggers = find_fresh_golden(fast, slow)
                sim = sim_long
            else:
                triggers = find_fresh_death(fast, slow)
                sim = sim_short

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
                "fast": fast_p, "slow": slow_p,
                "direction": direction,
                "n": n, "w": w, "l": l, "t": t,
                "wr_decisive": wr, "ci_low": ci_low, "ci_high": ci_high,
            })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--out", default="/tmp/sweep_sma_cross.csv")
    ap.add_argument("--pairs", default=None)
    args = ap.parse_args()

    if args.smoke:
        pairs = ["EUR_USD"]
        timeframes = {"H4": 14 * 6}
        pair_grid = [(20, 50), (50, 200)]
        directions = ["long", "short"]
    else:
        pairs = args.pairs.split(",") if args.pairs else PAIRS_FULL
        timeframes = TIMEFRAMES
        pair_grid = PAIR_GRID
        directions = DIRECTIONS

    n_cells = len(pairs) * len(timeframes) * len(pair_grid) * len(directions)
    print(f"Sweep: {len(pairs)} pairs × {len(timeframes)} TF × {len(pair_grid)} (fast,slow) "
          f"× {len(directions)} dirs = {n_cells} cells")
    print(f"Output: {args.out}\n")

    all_rows = []
    t0 = time.time()
    for p_idx, pair in enumerate(pairs, 1):
        pair_t0 = time.time()
        for tf, max_hold in timeframes.items():
            rows = sweep_pair(pair, tf, max_hold, pair_grid, directions)
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
                print(f"  {r['pair']:<10} {r['tf']:<3} fast={int(r['fast']):<3} "
                      f"slow={int(r['slow']):<3} {r['direction']:<5}  "
                      f"n={int(r['n'])} W/L/T={int(r['w'])}/{int(r['l'])}/{int(r['t'])}  "
                      f"WR={r['wr_decisive']*100:.1f}%  "
                      f"CI=[{r['ci_low']*100:.1f}, {r['ci_high']*100:.1f}]")


if __name__ == "__main__":
    main()
