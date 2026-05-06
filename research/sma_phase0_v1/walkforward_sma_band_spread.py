"""Walk-forward SMA distance-band sweep with REAL OANDA spread (bid/ask fills).

Mirror of research/stoch_phase0_v1/walkforward_stoch_spread.py.

Same 1,280-cell grid as walkforward_sma_band.py, but with bid/ask fills
instead of mid prices. SMA + ATR are still computed on mid OHLC (that's what
the trader sees), but every fill pays spread:

  - Long entry:    close_ask of trigger bar
  - Long stop hit: low_bid[k]  <= entry_ask * (1 - STOP_PCT)
  - Long TP hit:   high_bid[k] >= entry_ask * (1 + TP_PCT)
  - Long timeout:  exit at close_bid[entry+max_hold]
  - Short: mirror (entry close_bid, stop/TP against ask, timeout close_ask)

Walk-forward 70/30. Robust survivor: both halves CI low > 50%, tr_n>=50, te_n>=30.

Reads walkforward_sma_band.csv (mid output) for side-by-side mid → spread comparison.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

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

MID_CSV = "/root/BlueHorseshoe/research/sma_phase0_v1/walkforward_sma_band.csv"


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


def sim_long_spread(close_ask, high_bid, low_bid, close_bid, i, max_hold):
    if i + max_hold >= len(close_ask):
        return None
    entry = close_ask[i]
    tp = entry * (1 + TP_PCT)
    stop = entry * (1 - STOP_PCT)
    for j in range(1, max_hold + 1):
        k = i + j
        if low_bid[k] <= stop:
            return -1
        if high_bid[k] >= tp:
            return +1
    return 0


def sim_short_spread(close_bid, high_ask, low_ask, close_ask, i, max_hold):
    if i + max_hold >= len(close_bid):
        return None
    entry = close_bid[i]
    tp = entry * (1 - TP_PCT)
    stop = entry * (1 + STOP_PCT)
    for j in range(1, max_hold + 1):
        k = i + j
        if high_ask[k] >= stop:
            return -1
        if low_ask[k] <= tp:
            return +1
    return 0


def wilson_ci(wins, decisive):
    if decisive == 0:
        return float("nan"), float("nan"), float("nan")
    p = wins / decisive
    se = np.sqrt(p * (1 - p) / decisive)
    return p, max(0.0, p - 1.96 * se), min(1.0, p + 1.96 * se)


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
    atr_arr = atr(mid, period=ATR_PERIOD).to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()
    ca = raw["close_ask"].to_numpy(dtype=float)
    ha = raw["high_ask"].to_numpy(dtype=float)
    la = raw["low_ask"].to_numpy(dtype=float)
    cb = raw["close_bid"].to_numpy(dtype=float)
    hb = raw["high_bid"].to_numpy(dtype=float)
    lb = raw["low_bid"].to_numpy(dtype=float)

    rows = []
    for period in PERIODS:
        sma_arr = sma(mid, period=period).to_numpy(dtype=float)

        for direction in DIRECTIONS:
            find = find_fresh_long if direction == "long" else find_fresh_short

            for k in K_VALUES:
                triggers = find(m_close, sma_arr, atr_arr, float(k))
                outcomes = []
                for i in triggers:
                    if direction == "long":
                        r = sim_long_spread(ca, hb, lb, cb, int(i), MAX_HOLD)
                    else:
                        r = sim_short_spread(cb, ha, la, ca, int(i), MAX_HOLD)
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
    out_path = "/root/BlueHorseshoe/research/sma_phase0_v1/walkforward_sma_band_spread.csv"
    n_cells = (len(PAIRS_FULL) * len(PERIODS) * len(K_VALUES) * len(DIRECTIONS))
    print(f"Walk-forward with REAL spread: {n_cells} cells, 70/30 split per cell")
    print("Fills: long enters at close_ask / exits against bid; short mirror.\n")

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

    robust = df[(df["tr_ci_low"] > 0.50) & (df["te_ci_low"] > 0.50)
                & (df["tr_n"] >= 50) & (df["te_n"] >= 30)].copy()
    print(f"Robust survivors WITH SPREAD (both halves CI low > 50%, tr_n>=50, te_n>=30): "
          f"{len(robust)}/{len(df)}")

    mid_path = Path(MID_CSV)
    if mid_path.exists():
        mid_df = pd.read_csv(mid_path)
        mid_robust = mid_df[(mid_df["tr_ci_low"] > 0.50) & (mid_df["te_ci_low"] > 0.50)
                            & (mid_df["tr_n"] >= 50) & (mid_df["te_n"] >= 30)].copy()
        print(f"For comparison, mid robust survivors: {len(mid_robust)}\n")

        key_cols = ["pair", "period", "k", "direction"]
        merged = mid_robust.merge(
            df[key_cols + ["tr_wr", "te_wr", "tr_n", "te_n", "tr_ci_low", "te_ci_low"]],
            on=key_cols, suffixes=("_mid", "_spr"),
        )
        merged["delta_te_wr"] = (merged["te_wr_spr"] - merged["te_wr_mid"]) * 100
        merged["spr_robust"] = (
            (merged["tr_ci_low_spr"] > 0.50) & (merged["te_ci_low_spr"] > 0.50)
            & (merged["tr_n_spr"] >= 50) & (merged["te_n_spr"] >= 30)
        )
        flips = (~merged["spr_robust"]).sum()
        print(f"Cells robust on mid that LOSE robustness with spread: {flips}/{len(merged)}\n")

        print("=== Mid → Spread comparison (mid-robust cells) ===")
        merged_sorted = merged.sort_values("te_wr_spr", ascending=False)
        print(f"{'pair':<10} {'p':>4} {'k':>5} {'dir':<5}  "
              f"{'mid te WR':>10}  {'spr te WR':>10}  {'Δ':>6}  {'spr CI':>14}  flag")
        for _, r in merged_sorted.iterrows():
            flag = "★★ ROBUST" if r["spr_robust"] else "✗ FAIL"
            ci_str = f"[{r['tr_ci_low_spr']*100:.1f},{r['te_ci_low_spr']*100:.1f}]"
            print(f"  {r['pair']:<8} {int(r['period']):>4} {r['k']:>5.1f} {r['direction']:<5}  "
                  f"{r['te_wr_mid']*100:>9.1f}%  {r['te_wr_spr']*100:>9.1f}%  "
                  f"{r['delta_te_wr']:>+5.1f}  {ci_str:>14}  {flag}")
    else:
        print(f"(Mid CSV not found at {mid_path}; skipping side-by-side.)")

    if not robust.empty:
        print("\n=== Robust pairs WITH SPREAD ===")
        piv = robust.groupby(["pair", "direction"]).size().unstack(fill_value=0)
        piv["total"] = piv.sum(axis=1)
        print(piv.sort_values("total", ascending=False).to_string())

        print("\n=== All robust cells with spread, sorted by te WR ===")
        big = robust.sort_values("te_wr", ascending=False)
        for _, r in big.iterrows():
            print(f"  {r['pair']:<10} p={int(r['period']):<3} k={r['k']:.1f} "
                  f"{r['direction']:<5}  "
                  f"tr: n={int(r['tr_n'])} W/L={int(r['tr_w'])}/{int(r['tr_l'])} "
                  f"WR={r['tr_wr']*100:.1f}% CI=[{r['tr_ci_low']*100:.1f}, {r['tr_ci_high']*100:.1f}]  "
                  f"te: n={int(r['te_n'])} W/L={int(r['te_w'])}/{int(r['te_l'])} "
                  f"WR={r['te_wr']*100:.1f}% CI=[{r['te_ci_low']*100:.1f}, {r['te_ci_high']*100:.1f}]")


if __name__ == "__main__":
    main()
