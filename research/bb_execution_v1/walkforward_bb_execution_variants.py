"""Walk-forward 70/30 split across 4 BB execution variants.

Same sim logic as sweep_bb_execution_variants.py. For each cell, splits trades
chronologically by entry timestamp (or for variants C/D, fill timestamp) at the
70/30 boundary and reports per-half expectancy.

Survivor gate: both halves have expectancy CI lower > 0, tr n>=50, te n>=30.

Mid prices only (no spread). Spread test follows.
"""
from __future__ import annotations

import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/src")

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import atr, bollinger_bands, ohlc_mid


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
BB_PERIODS = [10, 20, 30, 50]
BB_STDS = [1.5, 2.0, 2.5, 3.0]
DEPTHS = [0.0, 0.1, 0.25, 0.5, 0.75]
DIRECTIONS = ["long", "short"]
ATR_PERIOD = 14
WAIT_BARS = 1
TP_PCT = 0.01
STOP_PCT = 0.01
ATR_STOP_MULT = 1.0
TRAIN_FRAC = 0.7


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


def _sim_long_core(m_close, m_high, m_low, entry_idx, entry_price, tp, stop, max_hold):
    n = len(m_close)
    if entry_idx + max_hold >= n:
        return None
    if stop >= entry_price or tp <= entry_price:
        return None
    risk = entry_price - stop
    for j in range(1, max_hold + 1):
        k = entry_idx + j
        if m_low[k] <= stop:
            return -1.0
        if m_high[k] >= tp:
            return (tp - entry_price) / risk
    exit_price = m_close[entry_idx + max_hold]
    return (exit_price - entry_price) / risk


def _sim_short_core(m_close, m_high, m_low, entry_idx, entry_price, tp, stop, max_hold):
    n = len(m_close)
    if entry_idx + max_hold >= n:
        return None
    if stop <= entry_price or tp >= entry_price:
        return None
    risk = stop - entry_price
    for j in range(1, max_hold + 1):
        k = entry_idx + j
        if m_high[k] >= stop:
            return -1.0
        if m_low[k] <= tp:
            return (entry_price - tp) / risk
    exit_price = m_close[entry_idx + max_hold]
    return (entry_price - exit_price) / risk


def _stop_entry_fill_long(m_high, i, level, wait_bars):
    n = len(m_high)
    for w in range(1, wait_bars + 1):
        k = i + w
        if k >= n:
            return None
        if m_high[k] >= level:
            return k
    return None


def _stop_entry_fill_short(m_low, i, level, wait_bars):
    n = len(m_low)
    for w in range(1, wait_bars + 1):
        k = i + w
        if k >= n:
            return None
        if m_low[k] <= level:
            return k
    return None


def run_variant(direction, variant, m_close, m_high, m_low, i, max_hold,
                middle_i, lower_i, upper_i, atr_i):
    """Return (r_value, decision_idx) where decision_idx is the bar at which the trade
    is committed (trigger bar for A/B, fill bar for C/D). Used for chronological split.
    """
    if direction == "long":
        if variant == "A":
            entry = m_close[i]
            r = _sim_long_core(m_close, m_high, m_low, i, entry,
                               entry * (1 + TP_PCT), entry * (1 - STOP_PCT), max_hold)
            return r, i
        elif variant == "B":
            entry = m_close[i]
            r = _sim_long_core(m_close, m_high, m_low, i, entry,
                               middle_i, lower_i - ATR_STOP_MULT * atr_i, max_hold)
            return r, i
        elif variant == "C":
            fill = _stop_entry_fill_long(m_high, i, lower_i, WAIT_BARS)
            if fill is None:
                return None, None
            entry = lower_i
            r = _sim_long_core(m_close, m_high, m_low, fill, entry,
                               entry * (1 + TP_PCT), entry * (1 - STOP_PCT), max_hold)
            return r, fill
        elif variant == "D":
            fill = _stop_entry_fill_long(m_high, i, lower_i, WAIT_BARS)
            if fill is None:
                return None, None
            entry = lower_i
            r = _sim_long_core(m_close, m_high, m_low, fill, entry,
                               middle_i, lower_i - ATR_STOP_MULT * atr_i, max_hold)
            return r, fill
    else:  # short
        if variant == "A":
            entry = m_close[i]
            r = _sim_short_core(m_close, m_high, m_low, i, entry,
                                entry * (1 - TP_PCT), entry * (1 + STOP_PCT), max_hold)
            return r, i
        elif variant == "B":
            entry = m_close[i]
            r = _sim_short_core(m_close, m_high, m_low, i, entry,
                                middle_i, upper_i + ATR_STOP_MULT * atr_i, max_hold)
            return r, i
        elif variant == "C":
            fill = _stop_entry_fill_short(m_low, i, upper_i, WAIT_BARS)
            if fill is None:
                return None, None
            entry = upper_i
            r = _sim_short_core(m_close, m_high, m_low, fill, entry,
                                entry * (1 - TP_PCT), entry * (1 + STOP_PCT), max_hold)
            return r, fill
        elif variant == "D":
            fill = _stop_entry_fill_short(m_low, i, upper_i, WAIT_BARS)
            if fill is None:
                return None, None
            entry = upper_i
            r = _sim_short_core(m_close, m_high, m_low, fill, entry,
                                middle_i, upper_i + ATR_STOP_MULT * atr_i, max_hold)
            return r, fill
    return None, None


def expectancy_split(rs_with_ts):
    """Split chronologically at TRAIN_FRAC; return per-half stats."""
    if not rs_with_ts:
        return {f"{half}_{k}": float("nan") for half in ["tr", "te"]
                for k in ["n", "mean_r", "se_r", "ci_low_r", "ci_high_r"]}
    sorted_data = sorted(rs_with_ts, key=lambda x: x[0])
    cut = int(len(sorted_data) * TRAIN_FRAC)
    halves = {"tr": sorted_data[:cut], "te": sorted_data[cut:]}
    out = {}
    for label, half in halves.items():
        rs = np.asarray([r for _, r in half], dtype=float)
        n = len(rs)
        if n == 0:
            mean_r = se = ci_low = ci_high = float("nan")
        elif n == 1:
            mean_r = float(rs[0])
            se = ci_low = ci_high = float("nan")
        else:
            mean_r = float(rs.mean())
            se = float(rs.std(ddof=1) / np.sqrt(n))
            ci_low = mean_r - 1.96 * se
            ci_high = mean_r + 1.96 * se
        out[f"{label}_n"] = n
        out[f"{label}_mean_r"] = mean_r
        out[f"{label}_se_r"] = se
        out[f"{label}_ci_low_r"] = ci_low
        out[f"{label}_ci_high_r"] = ci_high
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
    atr_arr = atr(mid, period=ATR_PERIOD).to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()

    rows = []
    for period in BB_PERIODS:
        for std in BB_STDS:
            bb = bollinger_bands(mid, period=period, n_std=std)
            lower = bb["lower"].to_numpy(dtype=float)
            upper = bb["upper"].to_numpy(dtype=float)
            middle = bb["middle"].to_numpy(dtype=float)
            bw = upper - lower

            for direction in DIRECTIONS:
                if direction == "long":
                    triggers = find_fresh_long(m_close, lower, bw, 0.0)  # placeholder
                # We need to recompute triggers per-depth; fix the loop structure
                pass

    # Redo with proper depth loop
    rows = []
    for period in BB_PERIODS:
        for std in BB_STDS:
            bb = bollinger_bands(mid, period=period, n_std=std)
            lower = bb["lower"].to_numpy(dtype=float)
            upper = bb["upper"].to_numpy(dtype=float)
            middle = bb["middle"].to_numpy(dtype=float)
            bw = upper - lower

            for direction in DIRECTIONS:
                if direction == "long":
                    find = find_fresh_long
                    band = lower
                else:
                    find = find_fresh_short
                    band = upper

                for depth in DEPTHS:
                    triggers = find(m_close, band, bw, depth)
                    rs_by_variant = {v: [] for v in "ABCD"}
                    for i in triggers:
                        i = int(i)
                        if np.isnan(atr_arr[i]) or np.isnan(middle[i]) or np.isnan(lower[i]):
                            continue
                        for v in "ABCD":
                            r, idx = run_variant(direction, v, m_close, m_high, m_low,
                                                  i, MAX_HOLD,
                                                  middle[i], lower[i], upper[i], atr_arr[i])
                            if r is None:
                                continue
                            rs_by_variant[v].append((pd.Timestamp(ts[idx]), r))

                    for v in "ABCD":
                        s = expectancy_split(rs_by_variant[v])
                        s.update({
                            "pair": pair, "tf": GRANULARITY,
                            "period": period, "std": std, "depth": depth,
                            "direction": direction, "variant": v,
                            "total_n": len(rs_by_variant[v]),
                        })
                        rows.append(s)
    return rows


def main():
    out_path = "/root/BlueHorseshoe/research/bb_execution_v1/walkforward.csv"
    print(f"Walk-forward 70/30, output: {out_path}\n")

    all_rows = []
    t0 = time.time()
    for p_idx, pair in enumerate(PAIRS_FULL, 1):
        rows = sweep_pair(pair)
        all_rows.extend(rows)
        print(f"  [{p_idx}/{len(PAIRS_FULL)}] {pair}  ({time.time()-t0:.1f}s)")

    df = pd.DataFrame(all_rows)
    df.to_csv(out_path, index=False)
    print(f"\nWrote {len(df)} rows to {out_path}\n")

    if df.empty:
        return

    print("=== Walk-forward survivors per variant (both halves CI_low_r > 0, tr n>=50, te n>=30) ===\n")
    for v in "ABCD":
        sub = df[df["variant"] == v]
        surv = sub[(sub["tr_ci_low_r"] > 0.0) & (sub["te_ci_low_r"] > 0.0)
                   & (sub["tr_n"] >= 50) & (sub["te_n"] >= 30)]
        print(f"  Variant {v}: {len(surv)}/{len(sub)} cells ({100*len(surv)/len(sub):.1f}%)")
        if not surv.empty:
            piv = surv.groupby(["pair", "direction"]).size().unstack(fill_value=0)
            piv["total"] = piv.sum(axis=1)
            print(f"    Per-pair survivors:")
            print(piv.sort_values("total", ascending=False).head(10).to_string())
            print(f"    Top 5 by te mean_R:")
            for _, r in surv.sort_values("te_mean_r", ascending=False).head(5).iterrows():
                print(f"      {r['pair']:<10} p={int(r['period'])} std={r['std']:.1f} "
                      f"depth={r['depth']:.2f} {r['direction']:<5}  "
                      f"tr: n={int(r['tr_n'])} R={r['tr_mean_r']:+.3f} "
                      f"CI=[{r['tr_ci_low_r']:+.3f},{r['tr_ci_high_r']:+.3f}]  "
                      f"te: n={int(r['te_n'])} R={r['te_mean_r']:+.3f} "
                      f"CI=[{r['te_ci_low_r']:+.3f},{r['te_ci_high_r']:+.3f}]")
        print()


if __name__ == "__main__":
    main()
