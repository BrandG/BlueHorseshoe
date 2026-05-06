"""Walk-forward 70/30 split for the SMA distance-band sweep.

Mirror of research/stoch_phase0_v1/walkforward_stoch_triggers.py.

Re-runs the same 1,280-cell parameter grid as sweep_sma_band.py, but for
each cell splits trades chronologically by entry_ts at the 70/30 boundary
and reports train/test stats.

Survivor categories:
  - Lenient: WR > 50% on BOTH halves AND test n >= 30
  - Strict:  test CI lower bound > 50% AND test n >= 30
  - Both halves strict: tr_ci_low > 50% AND te_ci_low > 50% (the cleanest)

Mid prices, fixed 1%/1% RR, identical sim to Phase 0.
"""
from __future__ import annotations

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

GRANULARITY = "H4"
MAX_HOLD = 14 * 6
PERIODS = [20, 50, 100, 200]
K_VALUES = [1.0, 1.5, 2.0, 2.5]
ATR_PERIOD = 14
DIRECTIONS = ["long", "short"]
TRAIN_FRAC = 0.7

TP_PCT = 0.01
STOP_PCT = 0.01


def find_fresh_long(close: np.ndarray, sma_arr: np.ndarray, atr_arr: np.ndarray,
                     k: float) -> np.ndarray:
    valid = ~np.isnan(close) & ~np.isnan(sma_arr) & ~np.isnan(atr_arr)
    lower = sma_arr - k * atr_arr
    cond = valid & (close < lower)
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def find_fresh_short(close: np.ndarray, sma_arr: np.ndarray, atr_arr: np.ndarray,
                      k: float) -> np.ndarray:
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


def split_stats(outcomes: list[tuple[pd.Timestamp, int]]) -> dict:
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
    atr_arr = atr(mid, period=ATR_PERIOD).to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()

    rows = []
    for period in PERIODS:
        sma_arr = sma(mid, period=period).to_numpy(dtype=float)

        for direction in DIRECTIONS:
            find = find_fresh_long if direction == "long" else find_fresh_short
            sim = sim_long if direction == "long" else sim_short

            for k in K_VALUES:
                triggers = find(m_close, sma_arr, atr_arr, float(k))
                outcomes = []
                for i in triggers:
                    r = sim(m_close, m_high, m_low, int(i), MAX_HOLD)
                    if r is None:
                        continue
                    outcomes.append((pd.Timestamp(ts[i]), r))

                s = split_stats(outcomes)
                s.update({
                    "pair": pair, "tf": GRANULARITY,
                    "period": period, "k": k, "atr_period": ATR_PERIOD,
                    "direction": direction,
                    "total_n": len(outcomes),
                })
                rows.append(s)
    return rows


def main():
    out_path = "/root/BlueHorseshoe/research/sma_phase0_v1/walkforward_sma_band.csv"
    print(f"Walk-forward sweep: {len(PAIRS_FULL)} pairs × {len(PERIODS)} periods × "
          f"{len(K_VALUES)} k × {len(DIRECTIONS)} dirs = "
          f"{len(PAIRS_FULL)*len(PERIODS)*len(K_VALUES)*len(DIRECTIONS)} cells")
    print(f"Split: {int(TRAIN_FRAC*100)}/{int((1-TRAIN_FRAC)*100)} per cell, by entry_ts")
    print(f"Output: {out_path}\n")

    all_rows = []
    t0 = time.time()
    for p_idx, pair in enumerate(PAIRS_FULL, 1):
        rows = sweep_pair(pair)
        all_rows.extend(rows)
        print(f"  [{p_idx}/{len(PAIRS_FULL)}] {pair}  ({time.time()-t0:.1f}s)")

    df = pd.DataFrame(all_rows)
    df.to_csv(out_path, index=False)
    print(f"\nWrote {len(df)} cells to {out_path}")

    if df.empty:
        return

    surv_lenient = df[(df["tr_wr"] > 0.50) & (df["te_wr"] > 0.50) & (df["te_n"] >= 30)]
    surv_strict = df[(df["te_ci_low"] > 0.50) & (df["te_n"] >= 30)]
    surv_both = df[(df["tr_ci_low"] > 0.50) & (df["te_ci_low"] > 0.50)
                   & (df["tr_n"] >= 50) & (df["te_n"] >= 30)]

    print(f"\nLenient (both halves WR>50%, test n>=30):       {len(surv_lenient)}/{len(df)}")
    print(f"Strict  (test CI lower > 50%, test n>=30):       {len(surv_strict)}/{len(df)}")
    print(f"Both-halves CI > 50% (tr n>=50 AND te n>=30):    {len(surv_both)}/{len(df)}")

    print("\n=== Top 25 'both halves CI>50%' cells by test WR ===")
    top = surv_both.sort_values("te_wr", ascending=False).head(25)
    for _, r in top.iterrows():
        print(f"  {r['pair']:<10} p={int(r['period']):<3} k={r['k']:.1f} "
              f"{r['direction']:<5}  "
              f"tr: n={int(r['tr_n'])} W/L={int(r['tr_w'])}/{int(r['tr_l'])} "
              f"WR={r['tr_wr']*100:.1f}% CI=[{r['tr_ci_low']*100:.1f}, {r['tr_ci_high']*100:.1f}]  "
              f"te: n={int(r['te_n'])} W/L={int(r['te_w'])}/{int(r['te_l'])} "
              f"WR={r['te_wr']*100:.1f}% CI=[{r['te_ci_low']*100:.1f}, {r['te_ci_high']*100:.1f}]")

    print("\n=== Per-pair survivor counts (both-halves CI gate) ===")
    if not surv_both.empty:
        piv = surv_both.groupby(["pair", "direction"]).size().unstack(fill_value=0)
        piv["total"] = piv.sum(axis=1)
        print(piv.sort_values("total", ascending=False).to_string())


if __name__ == "__main__":
    main()
