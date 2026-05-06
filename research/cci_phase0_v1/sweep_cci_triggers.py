"""CCI trigger parameter sweep — Phase 0 coin-flip test.

Mirror of research/rsi_phase0_v1/sweep_rsi_triggers.py — same trigger family
shape (fresh recovery from oversold/overbought) on a different oscillator.

CCI is unbounded (typically ±200, sometimes ±400 in extremes). Thresholds are
absolute values: long uses negative threshold, short uses positive.

Trigger family:
  long  — CCI rose for `recovery_bars` consecutive bars AND CCI at the start
          of that run was below `-threshold` (oversold). Fires fresh.
  short — CCI fell `recovery_bars` consecutive bars AND CCI at the start was
          above `+threshold` (overbought). Fires fresh.

Parameter grid:
  - timeframe:     H4  (max_hold 84 bars = 2 weeks)
  - period:        14, 20, 30, 40
  - threshold:     100, 150, 200, 250  (long uses -threshold, short uses +threshold)
  - recovery_bars: 1, 2, 3, 4
  - direction:     long, short
  - pair:          40 OANDA majors/exotics

  Total: 40 × 4 × 4 × 4 × 2 = 5,120 cells

Sim (identical to RSI / Stoch / SMA Phase 0): mid prices, 1%/1% RR,
stop-first ordering, timeout exit at close after max_hold.
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/src")

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import cci, ohlc_mid


PAIRS_FULL = [
    "EUR_USD", "GBP_USD", "AUD_USD", "USD_CAD", "USD_CHF", "NZD_USD", "USD_SEK",
    "AUD_CHF", "AUD_NZD", "AUD_CAD", "EUR_AUD", "EUR_CAD", "EUR_CHF", "EUR_NZD",
    "EUR_CZK", "CAD_JPY", "CAD_CHF", "USD_JPY", "EUR_GBP", "EUR_JPY", "GBP_JPY",
    "GBP_AUD", "GBP_CAD", "GBP_CHF", "GBP_NZD", "CHF_JPY", "NZD_JPY", "AUD_JPY",
    "USD_SGD", "USD_PLN", "USD_CZK", "USD_HUF", "EUR_HUF", "EUR_PLN", "EUR_SEK",
    "NZD_CAD", "NZD_CHF", "EUR_NOK", "USD_ZAR", "USD_NOK",
]

TIMEFRAMES = {"H4": 14 * 6}
PERIODS = [14, 20, 30, 40]
THRESHOLDS = [100, 150, 200, 250]
RECOVERY_BARS = [1, 2, 3, 4]
DIRECTIONS = ["long", "short"]

TP_PCT = 0.01
STOP_PCT = 0.01


def find_fresh_long(cci_arr, threshold, recovery):
    """Long: CCI rose `recovery` bars from below `-threshold`."""
    n = len(cci_arr)
    if n < recovery + 1:
        return np.array([], dtype=int)
    diffs_pos = np.zeros(n, dtype=bool)
    diffs_pos[1:] = cci_arr[1:] > cci_arr[:-1]
    rising = np.zeros(n, dtype=bool)
    for i in range(recovery, n):
        rising[i] = bool(np.all(diffs_pos[i - recovery + 1: i + 1]))
    base = np.full(n, np.nan)
    base[recovery:] = cci_arr[: n - recovery]
    valid = ~np.isnan(base) & ~np.isnan(cci_arr)
    cond = valid & rising & (base < -threshold)
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def find_fresh_short(cci_arr, threshold, recovery):
    """Short: CCI fell `recovery` bars from above `+threshold`."""
    n = len(cci_arr)
    if n < recovery + 1:
        return np.array([], dtype=int)
    diffs_neg = np.zeros(n, dtype=bool)
    diffs_neg[1:] = cci_arr[1:] < cci_arr[:-1]
    falling = np.zeros(n, dtype=bool)
    for i in range(recovery, n):
        falling[i] = bool(np.all(diffs_neg[i - recovery + 1: i + 1]))
    base = np.full(n, np.nan)
    base[recovery:] = cci_arr[: n - recovery]
    valid = ~np.isnan(base) & ~np.isnan(cci_arr)
    cond = valid & falling & (base > threshold)
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


def wilson_ci(wins, decisive):
    if decisive == 0:
        return float("nan"), float("nan"), float("nan")
    p = wins / decisive
    se = np.sqrt(p * (1 - p) / decisive)
    return p, max(0.0, p - 1.96 * se), min(1.0, p + 1.96 * se)


def sweep_pair(pair, timeframe, max_hold, periods, thresholds, recoveries, directions):
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
        cci_arr = cci(mid, period=period).to_numpy(dtype=float)
        for direction in directions:
            find = find_fresh_long if direction == "long" else find_fresh_short
            sim = sim_long if direction == "long" else sim_short
            for threshold in thresholds:
                for recovery in recoveries:
                    triggers = find(cci_arr, float(threshold), int(recovery))
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
                        "period": period, "threshold": threshold, "recovery": recovery,
                        "direction": direction,
                        "n": n, "w": w, "l": l, "t": t,
                        "wr_decisive": wr, "ci_low": ci_low, "ci_high": ci_high,
                    })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--out", default="/tmp/sweep_cci_triggers.csv")
    ap.add_argument("--pairs", default=None)
    args = ap.parse_args()

    if args.smoke:
        pairs = ["EUR_USD"]
        timeframes = {"H4": 14 * 6}
        periods = [14, 20]
        thresholds = [100, 200]
        recoveries = [1, 3]
        directions = ["long", "short"]
    else:
        pairs = args.pairs.split(",") if args.pairs else PAIRS_FULL
        timeframes = TIMEFRAMES
        periods = PERIODS
        thresholds = THRESHOLDS
        recoveries = RECOVERY_BARS
        directions = DIRECTIONS

    n_cells = (len(pairs) * len(timeframes) * len(periods) * len(thresholds)
               * len(recoveries) * len(directions))
    print(f"Sweep: {n_cells} cells, output: {args.out}\n")

    all_rows = []
    t0 = time.time()
    for p_idx, pair in enumerate(pairs, 1):
        pair_t0 = time.time()
        for tf, max_hold in timeframes.items():
            rows = sweep_pair(pair, tf, max_hold, periods, thresholds, recoveries, directions)
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
            print("\nTop 25 cells by WR (with n>=50 and CI lower bound > 50%):")
            top = clears.sort_values("wr_decisive", ascending=False).head(25)
            for _, r in top.iterrows():
                print(f"  {r['pair']:<10} p={int(r['period']):<2} thr={int(r['threshold']):>3} "
                      f"rec={int(r['recovery'])} {r['direction']:<5}  "
                      f"n={int(r['n'])} W/L/T={int(r['w'])}/{int(r['l'])}/{int(r['t'])}  "
                      f"WR={r['wr_decisive']*100:.1f}%  "
                      f"CI=[{r['ci_low']*100:.1f}, {r['ci_high']*100:.1f}]")


if __name__ == "__main__":
    main()
