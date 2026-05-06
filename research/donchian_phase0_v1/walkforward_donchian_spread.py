"""Walk-forward Donchian sweep with REAL OANDA spread (bid/ask fills).

Restricted to RR=1/1 only (RR=1/2 had 1 mid Phase-0 hit and 0 mid walk-forward
survivors; RR=1/3 had 0 Phase 0 hits). 1/1 had 24 Phase 0 hits and 1 mid
walk-forward survivor (GBP_CHF p=55 cfm=2 short).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

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

GRANULARITY = "H4"
MAX_HOLD = 14 * 6
PERIODS = [10, 20, 55, 100]
CONFIRMS = [1, 2, 3]
DIRECTIONS = ["long", "short"]
TRAIN_FRAC = 0.7

TP_PCT = 0.01
STOP_PCT = 0.01
BE_WR = 0.5  # 1/1 RR

MID_CSV = "/root/BlueHorseshoe/research/donchian_phase0_v1/walkforward_donchian_triggers.csv"


def find_fresh_long(close, upper, confirm):
    n = len(close)
    if n < confirm + 2:
        return np.array([], dtype=int)
    upper_prev = np.full(n, np.nan)
    upper_prev[1:] = upper[:-1]
    valid = ~np.isnan(close) & ~np.isnan(upper_prev)
    above = valid & (close > upper_prev)
    cond = np.zeros(n, dtype=bool)
    for i in range(confirm, n):
        cond[i] = bool(np.all(above[i - confirm + 1: i + 1]))
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def find_fresh_short(close, lower, confirm):
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


def sweep_pair(pair):
    store = FxStore()
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return []

    mid = ohlc_mid(raw)
    ts = raw["timestamp"].to_numpy()
    ca = raw["close_ask"].to_numpy(dtype=float)
    ha = raw["high_ask"].to_numpy(dtype=float)
    la = raw["low_ask"].to_numpy(dtype=float)
    cb = raw["close_bid"].to_numpy(dtype=float)
    hb = raw["high_bid"].to_numpy(dtype=float)
    lb = raw["low_bid"].to_numpy(dtype=float)
    m_close = mid["close"].to_numpy(dtype=float)

    rows = []
    for period in PERIODS:
        ch = donchian(mid, period=period)
        upper = ch["upper"].to_numpy(dtype=float)
        lower = ch["lower"].to_numpy(dtype=float)
        for direction in DIRECTIONS:
            for confirm in CONFIRMS:
                if direction == "long":
                    triggers = find_fresh_long(m_close, upper, int(confirm))
                else:
                    triggers = find_fresh_short(m_close, lower, int(confirm))
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
                    "period": period, "confirm": confirm,
                    "direction": direction,
                    "total_n": len(outcomes),
                })
                rows.append(s)
    return rows


def main():
    out_path = "/root/BlueHorseshoe/research/donchian_phase0_v1/walkforward_donchian_spread.csv"
    print(f"Donchian walk-forward with spread (RR=1/1 only), output: {out_path}\n")

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
    print(f"Robust survivors WITH SPREAD (both halves CI low > 50%): {len(robust)}/{len(df)}")

    if not robust.empty:
        print("\n=== Robust pairs WITH SPREAD ===")
        piv = robust.groupby(["pair", "direction"]).size().unstack(fill_value=0)
        piv["total"] = piv.sum(axis=1)
        print(piv.sort_values("total", ascending=False).to_string())

        print("\n=== All robust cells with spread, sorted by te WR ===")
        for _, r in robust.sort_values("te_wr", ascending=False).iterrows():
            print(f"  {r['pair']:<10} p={int(r['period']):<3} cfm={int(r['confirm'])} "
                  f"{r['direction']:<5}  "
                  f"tr: n={int(r['tr_n'])} WR={r['tr_wr']*100:.1f}%  "
                  f"te: n={int(r['te_n'])} WR={r['te_wr']*100:.1f}% "
                  f"CI=[{r['te_ci_low']*100:.1f},{r['te_ci_high']*100:.1f}]")

    # Specifically check the GBP_CHF cell that survived mid walk-forward
    print("\n=== GBP_CHF p=55 cfm=2 short (mid walk-forward survivor) — spread comparison ===")
    target = df[(df["pair"] == "GBP_CHF") & (df["period"] == 55)
                & (df["confirm"] == 2) & (df["direction"] == "short")]
    if not target.empty:
        r = target.iloc[0]
        print(f"  tr: n={int(r['tr_n'])} WR={r['tr_wr']*100:.1f}% CI=[{r['tr_ci_low']*100:.1f},{r['tr_ci_high']*100:.1f}]")
        print(f"  te: n={int(r['te_n'])} WR={r['te_wr']*100:.1f}% CI=[{r['te_ci_low']*100:.1f},{r['te_ci_high']*100:.1f}]")
        is_robust = (r["tr_ci_low"] > 0.50 and r["te_ci_low"] > 0.50
                     and r["tr_n"] >= 50 and r["te_n"] >= 30)
        print(f"  spread-robust: {'YES ★★' if is_robust else 'NO ✗'}")


if __name__ == "__main__":
    main()
