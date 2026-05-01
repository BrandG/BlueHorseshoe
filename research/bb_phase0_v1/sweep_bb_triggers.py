"""BB trigger parameter sweep — Phase 0 coin-flip test.

Mid prices, fixed 1%/1% RR, full universe, both directions.

Parameter grid (default = full sweep):
  - timeframe:  H4, D1
  - bb_period:  10, 20, 30, 50
  - bb_std:     1.5, 2.0, 2.5, 3.0
  - depth:      0, 0.1, 0.25, 0.5, 0.75 bandwidths past the band
  - direction:  long, short
  - pair:       40 OANDA majors/exotics

Trigger:
  - long  when fresh: close_mid < lower - depth * bw
  - short when fresh: close_mid > upper + depth * bw

Sim:
  - entry at next bar's close_mid
  - TP at entry * (1 ± 0.01), checked against high_mid / low_mid
  - stop at entry * (1 ∓ 0.01), checked stop-first ordering
  - timeout exit at close_mid at i + max_hold

Output: CSV with one row per cell + Wilson 95% CI on WR_decisive.

CLI:
  --smoke         Run a 24-cell smoke test (1 pair, 2 TF, 2 periods, 2 stds, 3 depths, 2 dirs)
  --out PATH      Output CSV path (default: /tmp/sweep_bb_triggers.csv)
  --pairs LIST    Comma-separated subset of pairs (overrides full universe)
"""
from __future__ import annotations

import argparse
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

TIMEFRAMES = {"H4": 14 * 6}  # max_hold in bars (2 weeks)
BB_PERIODS = [10, 20, 30, 50]
BB_STDS = [1.5, 2.0, 2.5, 3.0]
DEPTHS = [0.0, 0.1, 0.25, 0.5, 0.75]
DIRECTIONS = ["long", "short"]

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
               periods: list[int], stds: list[float], depths: list[float],
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
        for std in stds:
            bb = bollinger_bands(mid, period=period, n_std=std)
            lower = bb["lower"].to_numpy(dtype=float)
            upper = bb["upper"].to_numpy(dtype=float)
            bw = upper - lower

            for direction in directions:
                if direction == "long":
                    sim = sim_long
                    find = find_fresh_long
                    band = lower
                else:
                    sim = sim_short
                    find = find_fresh_short
                    band = upper

                for depth in depths:
                    triggers = find(m_close, band, bw, depth)
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
                        "pair": pair, "tf": timeframe, "period": period, "std": std,
                        "depth": depth, "direction": direction,
                        "n": n, "w": w, "l": l, "t": t,
                        "wr_decisive": wr, "ci_low": ci_low, "ci_high": ci_high,
                    })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="Run reduced 24-cell smoke test")
    ap.add_argument("--out", default="/tmp/sweep_bb_triggers.csv")
    ap.add_argument("--pairs", default=None, help="Comma-separated subset (overrides full universe)")
    args = ap.parse_args()

    if args.smoke:
        pairs = ["EUR_USD"]
        timeframes = {"H4": 14 * 6}
        periods = [20, 50]
        stds = [2.0, 2.5]
        depths = [0.0, 0.25, 0.5]
        directions = ["long", "short"]
    else:
        pairs = args.pairs.split(",") if args.pairs else PAIRS_FULL
        timeframes = TIMEFRAMES
        periods = BB_PERIODS
        stds = BB_STDS
        depths = DEPTHS
        directions = DIRECTIONS

    n_cells = (len(pairs) * len(timeframes) * len(periods) * len(stds)
               * len(depths) * len(directions))
    print(f"Sweep: {len(pairs)} pairs × {len(timeframes)} TF × {len(periods)} periods "
          f"× {len(stds)} stds × {len(depths)} depths × {len(directions)} dirs = {n_cells} cells")
    print(f"Output: {args.out}")
    print()

    all_rows = []
    t0 = time.time()
    for p_idx, pair in enumerate(pairs, 1):
        pair_t0 = time.time()
        for tf, max_hold in timeframes.items():
            rows = sweep_pair(pair, tf, max_hold, periods, stds, depths, directions)
            all_rows.extend(rows)
        elapsed = time.time() - pair_t0
        total_elapsed = time.time() - t0
        eta = total_elapsed / p_idx * (len(pairs) - p_idx)
        print(f"  [{p_idx}/{len(pairs)}] {pair} ({elapsed:.1f}s)  total {total_elapsed:.0f}s  ETA {eta:.0f}s")

    df = pd.DataFrame(all_rows)
    df.to_csv(args.out, index=False)
    print(f"\nWrote {len(df)} cells to {args.out}")

    # Quick summary: count of cells where CI lower bound > 0.50
    if not df.empty:
        clears = df[(df["ci_low"] > 0.50) & (df["n"] >= 50)]
        print(f"Cells with n≥50 AND CI lower bound > 50%: {len(clears)}/{len(df)}")
        if not clears.empty:
            print("\nTop 20 cells by WR (with n≥50 and CI lower bound > 50%):")
            top = clears.sort_values("wr_decisive", ascending=False).head(20)
            for _, r in top.iterrows():
                print(f"  {r['pair']:<10} {r['tf']:<3} period={int(r['period'])} std={r['std']} "
                      f"depth={r['depth']:.2f} {r['direction']:<5}  "
                      f"n={int(r['n'])} W/L/T={int(r['w'])}/{int(r['l'])}/{int(r['t'])}  "
                      f"WR={r['wr_decisive']*100:.1f}%  CI=[{r['ci_low']*100:.1f}, {r['ci_high']*100:.1f}]")


if __name__ == "__main__":
    main()
