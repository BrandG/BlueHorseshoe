"""Donchian channel breakout trigger sweep — Phase 0 coin-flip test.

Different shape from prior v1s: this is a BREAKOUT indicator, not mean-reversion.
Per `feedback_test_indicators_independently.md`, RR is swept as a parameter
rather than locked to prior v1s' 1%/1% (which is structurally wrong for breakouts).

Trigger family:
  long  — close[i] > upper[i-1] AND condition was false at i-1 (fresh).
          Optional confirm: close[i], close[i-1], ..., close[i-confirm+1] ALL
          > upper[i-confirm-1].
  short — close[i] < lower[i-1], mirror.

  Note: bh_ftmo donchian() returns upper/lower inclusive of bar i, so we use
  upper[i-1] / lower[i-1] for the trigger condition (otherwise the breakout is
  trivially impossible).

Parameter grid:
  - timeframe:  H4  (max_hold 84 bars = 2 weeks)
  - period:     10, 20, 55, 100
  - confirm:    1, 2, 3
  - RR:         (1.0%, 1.0%), (1.0%, 2.0%), (1.0%, 3.0%)  (stop_pct, tp_pct)
  - direction:  long, short
  - pair:       40 OANDA majors/exotics

  Total: 40 × 4 × 3 × 3 × 2 = 2,880 cells

Sim: mid prices, stop-first ordering, timeout exit at close after max_hold.
Note: at higher RR, "win" still = +1.0 in R units (not 2.0 or 3.0); we want
to see WR survive at higher RR, which mathematically requires a lower WR
to be break-even. A 33% WR at (1, 2) RR has the same R/trade as 50% at (1, 1).
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/src")

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import donchian, ohlc_mid


PAIRS_FULL = [
    "EUR_USD", "GBP_USD", "AUD_USD", "USD_CAD", "USD_CHF", "NZD_USD", "USD_SEK",
    "AUD_CHF", "AUD_NZD", "AUD_CAD", "EUR_AUD", "EUR_CAD", "EUR_CHF", "EUR_NZD",
    "EUR_CZK", "CAD_JPY", "CAD_CHF", "USD_JPY", "EUR_GBP", "EUR_JPY", "GBP_JPY",
    "GBP_AUD", "GBP_CAD", "GBP_CHF", "GBP_NZD", "CHF_JPY", "NZD_JPY", "AUD_JPY",
    "USD_SGD", "USD_PLN", "USD_CZK", "USD_HUF", "EUR_HUF", "EUR_PLN", "EUR_SEK",
    "NZD_CAD", "NZD_CHF", "EUR_NOK", "USD_ZAR", "USD_NOK",
]

TIMEFRAMES = {"H4": 14 * 6}
PERIODS = [10, 20, 55, 100]
CONFIRMS = [1, 2, 3]
RR_VARIANTS = [(0.01, 0.01), (0.01, 0.02), (0.01, 0.03)]  # (stop, tp)
DIRECTIONS = ["long", "short"]


def find_fresh_long(close, upper, confirm):
    """Long: close > upper[shifted by 1], `confirm` consecutive bars."""
    n = len(close)
    if n < confirm + 2:
        return np.array([], dtype=int)
    upper_prev = np.full(n, np.nan)
    upper_prev[1:] = upper[:-1]  # upper[i-1]
    valid = ~np.isnan(close) & ~np.isnan(upper_prev)
    above = valid & (close > upper_prev)
    cond = np.zeros(n, dtype=bool)
    for i in range(confirm, n):
        # last `confirm` bars all closed above their respective prior-bar upper
        cond[i] = bool(np.all(above[i - confirm + 1: i + 1]))
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def find_fresh_short(close, lower, confirm):
    """Short: close < lower[shifted by 1], `confirm` consecutive bars."""
    n = len(close)
    if n < confirm + 2:
        return np.array([], dtype=int)
    lower_prev = np.full(n, np.nan)
    lower_prev[1:] = lower[:-1]
    valid = ~np.isnan(close) & ~np.isnan(lower_prev)
    below = valid & (close < lower_prev)
    cond = np.zeros(n, dtype=bool)
    for i in range(confirm, n):
        cond[i] = bool(np.all(below[i - confirm + 1: i + 1]))
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def sim_long(close, high, low, i, max_hold, stop_pct, tp_pct):
    if i + max_hold >= len(close):
        return None
    entry = close[i]
    tp = entry * (1 + tp_pct)
    stop = entry * (1 - stop_pct)
    for j in range(1, max_hold + 1):
        k = i + j
        if low[k] <= stop:
            return -1
        if high[k] >= tp:
            return +1
    return 0


def sim_short(close, high, low, i, max_hold, stop_pct, tp_pct):
    if i + max_hold >= len(close):
        return None
    entry = close[i]
    tp = entry * (1 - tp_pct)
    stop = entry * (1 + stop_pct)
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


def break_even_wr(stop_pct, tp_pct):
    """WR needed for zero expectancy at this RR (no spread, no slip)."""
    return stop_pct / (stop_pct + tp_pct)


def sweep_pair(pair, timeframe, max_hold, periods, confirms, rr_variants, directions):
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
        ch = donchian(mid, period=period)
        upper = ch["upper"].to_numpy(dtype=float)
        lower = ch["lower"].to_numpy(dtype=float)
        for direction in directions:
            for confirm in confirms:
                if direction == "long":
                    triggers = find_fresh_long(m_close, upper, int(confirm))
                else:
                    triggers = find_fresh_short(m_close, lower, int(confirm))

                for stop_pct, tp_pct in rr_variants:
                    n = w = l = t = 0
                    for i in triggers:
                        if direction == "long":
                            r = sim_long(m_close, m_high, m_low, int(i), max_hold,
                                         stop_pct, tp_pct)
                        else:
                            r = sim_short(m_close, m_high, m_low, int(i), max_hold,
                                          stop_pct, tp_pct)
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
                    be = break_even_wr(stop_pct, tp_pct)
                    rows.append({
                        "pair": pair, "tf": timeframe,
                        "period": period, "confirm": confirm,
                        "stop_pct": stop_pct, "tp_pct": tp_pct,
                        "rr_label": f"{stop_pct*100:.0f}/{tp_pct*100:.0f}",
                        "be_wr": be, "direction": direction,
                        "n": n, "w": w, "l": l, "t": t,
                        "wr_decisive": wr, "ci_low": ci_low, "ci_high": ci_high,
                    })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--out", default="/tmp/sweep_donchian_triggers.csv")
    ap.add_argument("--pairs", default=None)
    args = ap.parse_args()

    if args.smoke:
        pairs = ["EUR_USD"]
        timeframes = {"H4": 14 * 6}
        periods = [20, 55]
        confirms = [1, 2]
        rr_variants = [(0.01, 0.01), (0.01, 0.02)]
        directions = ["long", "short"]
    else:
        pairs = args.pairs.split(",") if args.pairs else PAIRS_FULL
        timeframes = TIMEFRAMES
        periods = PERIODS
        confirms = CONFIRMS
        rr_variants = RR_VARIANTS
        directions = DIRECTIONS

    n_cells = (len(pairs) * len(timeframes) * len(periods) * len(confirms)
               * len(rr_variants) * len(directions))
    print(f"Sweep: {n_cells} cells, output: {args.out}\n")

    all_rows = []
    t0 = time.time()
    for p_idx, pair in enumerate(pairs, 1):
        pair_t0 = time.time()
        for tf, max_hold in timeframes.items():
            rows = sweep_pair(pair, tf, max_hold, periods, confirms, rr_variants, directions)
            all_rows.extend(rows)
        elapsed = time.time() - pair_t0
        total_elapsed = time.time() - t0
        eta = total_elapsed / p_idx * (len(pairs) - p_idx)
        print(f"  [{p_idx}/{len(pairs)}] {pair} ({elapsed:.1f}s)  total {total_elapsed:.0f}s  ETA {eta:.0f}s")

    df = pd.DataFrame(all_rows)
    df.to_csv(args.out, index=False)
    print(f"\nWrote {len(df)} cells to {args.out}")

    if not df.empty:
        # For each cell, gate is "WR > break-even by 95% CI lower bound"
        df["edge_wr"] = df["wr_decisive"] - df["be_wr"]
        df["edge_ci_low"] = df["ci_low"] - df["be_wr"]
        clears = df[(df["edge_ci_low"] > 0.00) & (df["n"] >= 50)]
        print(f"Cells with n>=50 AND CI lower bound > break-even WR: {len(clears)}/{len(df)}")
        if not clears.empty:
            print("\nTop 25 cells by edge above break-even (n>=50, CI low > BE):")
            top = clears.sort_values("edge_wr", ascending=False).head(25)
            for _, r in top.iterrows():
                print(f"  {r['pair']:<10} p={int(r['period']):<3} cfm={int(r['confirm'])} "
                      f"RR={r['rr_label']:<5} {r['direction']:<5}  "
                      f"n={int(r['n'])} W/L/T={int(r['w'])}/{int(r['l'])}/{int(r['t'])}  "
                      f"WR={r['wr_decisive']*100:.1f}% (BE={r['be_wr']*100:.1f}%)  "
                      f"edge=+{r['edge_wr']*100:.1f}pp  CI=[{r['ci_low']*100:.1f}, {r['ci_high']*100:.1f}]")

        # Summary: WR distribution per RR variant
        print("\n=== Edge distribution per RR variant ===")
        for rr in df["rr_label"].unique():
            sub = df[df["rr_label"] == rr]
            cleared = sub[(sub["edge_ci_low"] > 0.00) & (sub["n"] >= 50)]
            print(f"  RR={rr}: cells with edge above BE = {len(cleared)}/{len(sub)} "
                  f"({100*len(cleared)/len(sub):.1f}%)  "
                  f"max edge = +{sub['edge_wr'].max()*100:.1f}pp")


if __name__ == "__main__":
    main()
