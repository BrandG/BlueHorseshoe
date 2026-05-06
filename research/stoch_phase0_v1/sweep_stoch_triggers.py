"""Stochastic trigger parameter sweep — Phase 0 coin-flip test.

Mirror of research/bb_phase0_v1/sweep_bb_triggers.py for the stochastic %K
oscillator. Mid prices, fixed 1%/1% RR, full universe, both directions.

Trigger family:
  long  — K rose for `recovery_bars` consecutive bars AND K at the start of
          that run was below `threshold`. Fires only on the bar where the
          condition first becomes true (fresh).
  short — mirror: K fell for `recovery_bars` consecutive bars AND K at the
          start of that run was above `100 - threshold`.

  recovery_bars=3, threshold=20 reproduces the deployed `rising_3bar_from_
  oversold` configuration. recovery_bars=1 is "single up-bar from oversold",
  closer to a classic stoch_oversold_cross.

Parameter grid (default = full sweep):
  - timeframe:     H4  (max_hold 84 bars = 2 weeks, matches BB Phase 0)
  - k_period:      5, 9, 14, 21
  - d_period:      3  (fixed; %D not used by the trigger here, exposed for symmetry)
  - threshold:     15, 20, 25, 30  (long; short uses 100 - threshold)
  - recovery_bars: 1, 2, 3, 4
  - direction:     long, short
  - pair:          40 OANDA majors/exotics

  Total: 1 × 4 × 1 × 4 × 4 × 2 × 40 = 5,120 cells

Sim (identical to BB Phase 0):
  - entry at the trigger bar's close_mid
  - TP at entry * (1 ± 0.01), checked against high_mid / low_mid
  - stop at entry * (1 ∓ 0.01), checked stop-first ordering
  - timeout exit at close_mid at i + max_hold

Output: CSV with one row per cell + Wilson 95% CI on WR_decisive.

CLI:
  --smoke         Run a small smoke test (1 pair, 2 k_periods, 2 thresholds, 2 rec, 2 dirs)
  --out PATH      Output CSV path (default: /tmp/sweep_stoch_triggers.csv)
  --pairs LIST    Comma-separated subset of pairs (overrides full universe)
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/src")

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import ohlc_mid, stochastic


PAIRS_FULL = [
    "EUR_USD", "GBP_USD", "AUD_USD", "USD_CAD", "USD_CHF", "NZD_USD", "USD_SEK",
    "AUD_CHF", "AUD_NZD", "AUD_CAD", "EUR_AUD", "EUR_CAD", "EUR_CHF", "EUR_NZD",
    "EUR_CZK", "CAD_JPY", "CAD_CHF", "USD_JPY", "EUR_GBP", "EUR_JPY", "GBP_JPY",
    "GBP_AUD", "GBP_CAD", "GBP_CHF", "GBP_NZD", "CHF_JPY", "NZD_JPY", "AUD_JPY",
    "USD_SGD", "USD_PLN", "USD_CZK", "USD_HUF", "EUR_HUF", "EUR_PLN", "EUR_SEK",
    "NZD_CAD", "NZD_CHF", "EUR_NOK", "USD_ZAR", "USD_NOK",
]

TIMEFRAMES = {"H4": 14 * 6}  # max_hold in bars (2 weeks), same as BB
K_PERIODS = [5, 9, 14, 21]
D_PERIODS = [3]  # exposed for symmetry; %D not used by current trigger family
THRESHOLDS = [15, 20, 25, 30]
RECOVERY_BARS = [1, 2, 3, 4]
DIRECTIONS = ["long", "short"]

TP_PCT = 0.01
STOP_PCT = 0.01


def find_fresh_long(k: np.ndarray, threshold: float, recovery: int) -> np.ndarray:
    """Long trigger: K rose `recovery` consecutive bars from below `threshold`.

    Condition at bar i:
      K[i-recovery] < threshold
      AND K[i-r+1] > K[i-r] for r in 1..recovery   (strictly rising)

    `fresh` = condition true at i but not at i-1.
    """
    n = len(k)
    if n < recovery + 1:
        return np.array([], dtype=int)
    diffs_pos = np.zeros(n, dtype=bool)
    diffs_pos[1:] = k[1:] > k[:-1]
    rising = np.zeros(n, dtype=bool)
    for i in range(recovery, n):
        rising[i] = bool(np.all(diffs_pos[i - recovery + 1: i + 1]))
    # K at the start of the rise (bar i-recovery) was below threshold
    base = np.full(n, np.nan)
    base[recovery:] = k[: n - recovery]
    valid = ~np.isnan(base) & ~np.isnan(k)
    cond = valid & rising & (base < threshold)
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def find_fresh_short(k: np.ndarray, threshold: float, recovery: int) -> np.ndarray:
    """Short trigger: K fell `recovery` consecutive bars from above `100 - threshold`."""
    n = len(k)
    if n < recovery + 1:
        return np.array([], dtype=int)
    diffs_neg = np.zeros(n, dtype=bool)
    diffs_neg[1:] = k[1:] < k[:-1]
    falling = np.zeros(n, dtype=bool)
    for i in range(recovery, n):
        falling[i] = bool(np.all(diffs_neg[i - recovery + 1: i + 1]))
    base = np.full(n, np.nan)
    base[recovery:] = k[: n - recovery]
    valid = ~np.isnan(base) & ~np.isnan(k)
    upper = 100.0 - threshold
    cond = valid & falling & (base > upper)
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
    return 0  # timeout


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
    return 0  # timeout


def wilson_ci(wins: int, decisive: int) -> tuple[float, float, float]:
    if decisive == 0:
        return float("nan"), float("nan"), float("nan")
    p = wins / decisive
    se = np.sqrt(p * (1 - p) / decisive)
    return p, max(0.0, p - 1.96 * se), min(1.0, p + 1.96 * se)


def sweep_pair(pair: str, timeframe: str, max_hold: int,
               k_periods: list[int], d_periods: list[int],
               thresholds: list[int], recoveries: list[int],
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
    for k_period in k_periods:
        for d_period in d_periods:
            stoch = stochastic(mid, k_period=k_period, d_period=d_period)
            k_arr = stoch["k"].to_numpy(dtype=float)

            for direction in directions:
                find = find_fresh_long if direction == "long" else find_fresh_short
                sim = sim_long if direction == "long" else sim_short

                for threshold in thresholds:
                    for recovery in recoveries:
                        triggers = find(k_arr, float(threshold), int(recovery))
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
                            "k_period": k_period, "d_period": d_period,
                            "threshold": threshold, "recovery": recovery,
                            "direction": direction,
                            "n": n, "w": w, "l": l, "t": t,
                            "wr_decisive": wr, "ci_low": ci_low, "ci_high": ci_high,
                        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="Run reduced smoke test")
    ap.add_argument("--out", default="/tmp/sweep_stoch_triggers.csv")
    ap.add_argument("--pairs", default=None, help="Comma-separated subset of pairs")
    args = ap.parse_args()

    if args.smoke:
        pairs = ["EUR_USD"]
        timeframes = {"H4": 14 * 6}
        k_periods = [9, 14]
        d_periods = [3]
        thresholds = [20, 25]
        recoveries = [1, 3]
        directions = ["long", "short"]
    else:
        pairs = args.pairs.split(",") if args.pairs else PAIRS_FULL
        timeframes = TIMEFRAMES
        k_periods = K_PERIODS
        d_periods = D_PERIODS
        thresholds = THRESHOLDS
        recoveries = RECOVERY_BARS
        directions = DIRECTIONS

    n_cells = (len(pairs) * len(timeframes) * len(k_periods) * len(d_periods)
               * len(thresholds) * len(recoveries) * len(directions))
    print(f"Sweep: {len(pairs)} pairs × {len(timeframes)} TF × {len(k_periods)} k_periods × "
          f"{len(d_periods)} d_periods × {len(thresholds)} thresholds × "
          f"{len(recoveries)} recoveries × {len(directions)} dirs = {n_cells} cells")
    print(f"Output: {args.out}")
    print()

    all_rows = []
    t0 = time.time()
    for p_idx, pair in enumerate(pairs, 1):
        pair_t0 = time.time()
        for tf, max_hold in timeframes.items():
            rows = sweep_pair(pair, tf, max_hold, k_periods, d_periods,
                              thresholds, recoveries, directions)
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
                print(f"  {r['pair']:<10} {r['tf']:<3} kP={int(r['k_period']):<2} "
                      f"thr={int(r['threshold'])} rec={int(r['recovery'])} "
                      f"{r['direction']:<5}  "
                      f"n={int(r['n'])} W/L/T={int(r['w'])}/{int(r['l'])}/{int(r['t'])}  "
                      f"WR={r['wr_decisive']*100:.1f}%  "
                      f"CI=[{r['ci_low']*100:.1f}, {r['ci_high']*100:.1f}]")


if __name__ == "__main__":
    main()
