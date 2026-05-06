"""Walk-forward 70/30 split for Donchian breakout sweep, mid prices.

Skips RR=1/3 (zero Phase 0 survivors). Keeps RR=1/1 (24 survivors) and RR=1/2
(1 survivor) for completeness.
"""
from __future__ import annotations

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

GRANULARITY = "H4"
MAX_HOLD = 14 * 6
PERIODS = [10, 20, 55, 100]
CONFIRMS = [1, 2, 3]
RR_VARIANTS = [(0.01, 0.01), (0.01, 0.02)]
DIRECTIONS = ["long", "short"]
TRAIN_FRAC = 0.7


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
    return stop_pct / (stop_pct + tp_pct)


def split_stats(outcomes, be_wr):
    if not outcomes:
        return {f"{half}_{k}": float("nan") for half in ["tr", "te"]
                for k in ["n", "w", "l", "t", "wr", "ci_low", "ci_high",
                          "edge", "edge_ci_low"]}
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
        out[f"{label}_edge"] = wr - be_wr if not np.isnan(wr) else float("nan")
        out[f"{label}_edge_ci_low"] = ci_low - be_wr if not np.isnan(ci_low) else float("nan")
    return out


def sweep_pair(pair):
    store = FxStore()
    raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
    if raw is None or raw.empty:
        return []

    mid = ohlc_mid(raw)
    m_close = mid["close"].to_numpy(dtype=float)
    m_high = mid["high"].to_numpy(dtype=float)
    m_low = mid["low"].to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()

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

                for stop_pct, tp_pct in RR_VARIANTS:
                    be = break_even_wr(stop_pct, tp_pct)
                    outcomes = []
                    for i in triggers:
                        if direction == "long":
                            r = sim_long(m_close, m_high, m_low, int(i), MAX_HOLD,
                                         stop_pct, tp_pct)
                        else:
                            r = sim_short(m_close, m_high, m_low, int(i), MAX_HOLD,
                                          stop_pct, tp_pct)
                        if r is None:
                            continue
                        outcomes.append((pd.Timestamp(ts[i]), r))
                    s = split_stats(outcomes, be)
                    s.update({
                        "pair": pair, "tf": GRANULARITY,
                        "period": period, "confirm": confirm,
                        "stop_pct": stop_pct, "tp_pct": tp_pct,
                        "rr_label": f"{stop_pct*100:.0f}/{tp_pct*100:.0f}",
                        "be_wr": be, "direction": direction,
                        "total_n": len(outcomes),
                    })
                    rows.append(s)
    return rows


def main():
    out_path = "/root/BlueHorseshoe/research/donchian_phase0_v1/walkforward_donchian_triggers.csv"
    print(f"Walk-forward 70/30, output: {out_path}\n")

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

    surv_both = df[(df["tr_edge_ci_low"] > 0.00) & (df["te_edge_ci_low"] > 0.00)
                   & (df["tr_n"] >= 50) & (df["te_n"] >= 30)]
    print(f"\nBoth-halves edge CI > BE (tr n>=50 AND te n>=30): {len(surv_both)}/{len(df)}")

    print("\n=== Top 25 'both halves edge>BE CI' cells by test edge ===")
    top = surv_both.sort_values("te_edge", ascending=False).head(25)
    for _, r in top.iterrows():
        print(f"  {r['pair']:<10} p={int(r['period']):<3} cfm={int(r['confirm'])} "
              f"RR={r['rr_label']:<5} {r['direction']:<5}  "
              f"tr: n={int(r['tr_n'])} WR={r['tr_wr']*100:.1f}% (edge {r['tr_edge']*100:+.1f}pp)  "
              f"te: n={int(r['te_n'])} WR={r['te_wr']*100:.1f}% (edge {r['te_edge']*100:+.1f}pp) "
              f"CI=[{r['te_ci_low']*100:.1f},{r['te_ci_high']*100:.1f}]")

    print("\n=== Per-pair survivor counts ===")
    if not surv_both.empty:
        piv = surv_both.groupby(["pair", "direction"]).size().unstack(fill_value=0)
        piv["total"] = piv.sum(axis=1)
        print(piv.sort_values("total", ascending=False).to_string())


if __name__ == "__main__":
    main()
