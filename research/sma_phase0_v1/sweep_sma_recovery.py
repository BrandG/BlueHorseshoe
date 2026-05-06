"""SMA recovery-from-cross trigger sweep — Phase 0 coin-flip test.

Family B (and folds in Family A): close was on the wrong side of SMA(period)
for `recovery` consecutive bars, then closes back through. Single-bar cross
is the recovery=1 case.

Trigger family:
  long  — close[i-recovery..i-1] all < SMA AND close[i] > SMA. Fresh.
  short — close[i-recovery..i-1] all > SMA AND close[i] < SMA. Fresh.

Mirrors research/stoch_phase0_v1/sweep_stoch_triggers.py shape:
  - timeframe:     H4  (max_hold 84 bars = 2 weeks)
  - period:        20, 50, 100, 200
  - recovery_bars: 1, 2, 3, 4
  - direction:     long, short
  - pair:          40 OANDA majors/exotics
  - entry/exit:    mid prices, 1%/1% RR, stop-first ordering, timeout at close

  Total: 40 × 4 × 4 × 2 = 1,280 cells

CLI:
  --smoke         Reduced grid for sanity check
  --out PATH      Output CSV path (default: /tmp/sweep_sma_recovery.csv)
  --pairs LIST    Comma-separated subset of pairs
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
PERIODS = [20, 50, 100, 200]
RECOVERY_BARS = [1, 2, 3, 4]
DIRECTIONS = ["long", "short"]

TP_PCT = 0.01
STOP_PCT = 0.01


def find_fresh_long(close: np.ndarray, sma_arr: np.ndarray, recovery: int) -> np.ndarray:
    """Long: close was below SMA for `recovery` bars, then closes above. Fresh."""
    n = len(close)
    if n < recovery + 1:
        return np.array([], dtype=int)
    below = close < sma_arr  # element-wise
    above = close > sma_arr
    valid = ~np.isnan(sma_arr) & ~np.isnan(close)
    cond = np.zeros(n, dtype=bool)
    for i in range(recovery, n):
        if not valid[i]:
            continue
        if not above[i]:
            continue
        # check the last `recovery` bars (i-recovery .. i-1) were all below
        window_ok = bool(np.all(below[i - recovery: i] & valid[i - recovery: i]))
        cond[i] = window_ok
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def find_fresh_short(close: np.ndarray, sma_arr: np.ndarray, recovery: int) -> np.ndarray:
    """Short: close was above SMA for `recovery` bars, then closes below. Fresh."""
    n = len(close)
    if n < recovery + 1:
        return np.array([], dtype=int)
    above = close > sma_arr
    below = close < sma_arr
    valid = ~np.isnan(sma_arr) & ~np.isnan(close)
    cond = np.zeros(n, dtype=bool)
    for i in range(recovery, n):
        if not valid[i]:
            continue
        if not below[i]:
            continue
        window_ok = bool(np.all(above[i - recovery: i] & valid[i - recovery: i]))
        cond[i] = window_ok
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
               periods: list[int], recoveries: list[int],
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
    for period in periods:
        sma_series = sma(mid, period=period)
        sma_arr = sma_series.to_numpy(dtype=float)

        for direction in directions:
            find = find_fresh_long if direction == "long" else find_fresh_short
            sim = sim_long if direction == "long" else sim_short

            for recovery in recoveries:
                triggers = find(m_close, sma_arr, int(recovery))
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
                    "period": period, "recovery": recovery,
                    "direction": direction,
                    "n": n, "w": w, "l": l, "t": t,
                    "wr_decisive": wr, "ci_low": ci_low, "ci_high": ci_high,
                })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--out", default="/tmp/sweep_sma_recovery.csv")
    ap.add_argument("--pairs", default=None)
    args = ap.parse_args()

    if args.smoke:
        pairs = ["EUR_USD"]
        timeframes = {"H4": 14 * 6}
        periods = [20, 50]
        recoveries = [1, 3]
        directions = ["long", "short"]
    else:
        pairs = args.pairs.split(",") if args.pairs else PAIRS_FULL
        timeframes = TIMEFRAMES
        periods = PERIODS
        recoveries = RECOVERY_BARS
        directions = DIRECTIONS

    n_cells = len(pairs) * len(timeframes) * len(periods) * len(recoveries) * len(directions)
    print(f"Sweep: {len(pairs)} pairs × {len(timeframes)} TF × {len(periods)} periods × "
          f"{len(recoveries)} recoveries × {len(directions)} dirs = {n_cells} cells")
    print(f"Output: {args.out}\n")

    all_rows = []
    t0 = time.time()
    for p_idx, pair in enumerate(pairs, 1):
        pair_t0 = time.time()
        for tf, max_hold in timeframes.items():
            rows = sweep_pair(pair, tf, max_hold, periods, recoveries, directions)
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
                      f"rec={int(r['recovery'])} {r['direction']:<5}  "
                      f"n={int(r['n'])} W/L/T={int(r['w'])}/{int(r['l'])}/{int(r['t'])}  "
                      f"WR={r['wr_decisive']*100:.1f}%  "
                      f"CI=[{r['ci_low']*100:.1f}, {r['ci_high']*100:.1f}]")


if __name__ == "__main__":
    main()
