"""BB Phase 0 sweep across 4 execution variants — full 40-pair universe.

Each trigger gets simulated 4 ways:
  A: market entry at trigger close + fixed 1R exits  (BB v1 baseline)
  B: market entry at trigger close + structural exits (TP=midline, stop=band-1*ATR)
  C: stop-buy entry at band (wait for confirmation) + fixed 1R exits
  D: stop-buy entry at band + structural exits — full new model

Phase 0 uses MID prices for fills. Spread test comes later.

Sim returns (outcome, r_value) where r_value is signed:
  win  = (tp - entry) / risk
  loss = -1.0
  timeout = (close_mid_at_timeout - entry) / risk
For variants A/C with fixed 1%/1% RR, win = +1 R, loss = -1 R (clean R units).
For variants B/D, R varies per trade based on (midline - entry) / (entry - lower + atr).

Phase 0 gate: expectancy CI lower bound > 0  (using mean and SE of per-trade R values).
This properly handles variable-RR variants where break-even WR is below 50%.
"""
from __future__ import annotations

import argparse
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

TIMEFRAMES = {"H4": 14 * 6}
BB_PERIODS = [10, 20, 30, 50]
BB_STDS = [1.5, 2.0, 2.5, 3.0]
DEPTHS = [0.0, 0.1, 0.25, 0.5, 0.75]
DIRECTIONS = ["long", "short"]
ATR_PERIOD = 14
WAIT_BARS = 1
TP_PCT = 0.01
STOP_PCT = 0.01
ATR_STOP_MULT = 1.0


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
    """Run forward sim for a long. Return (outcome, r_value) or (None, None).
       outcome: +1 win / -1 loss / 0 timeout.
       r_value: signed R relative to (entry - stop) risk.
    """
    n = len(m_close)
    if entry_idx + max_hold >= n:
        return None, None
    if stop >= entry_price or tp <= entry_price:
        return None, None
    risk = entry_price - stop
    for j in range(1, max_hold + 1):
        k = entry_idx + j
        if m_low[k] <= stop:
            return -1, -1.0
        if m_high[k] >= tp:
            return +1, (tp - entry_price) / risk
    # timeout
    exit_price = m_close[entry_idx + max_hold]
    return 0, (exit_price - entry_price) / risk


def _sim_short_core(m_close, m_high, m_low, entry_idx, entry_price, tp, stop, max_hold):
    """Mirror for short. tp < entry, stop > entry. risk = stop - entry."""
    n = len(m_close)
    if entry_idx + max_hold >= n:
        return None, None
    if stop <= entry_price or tp >= entry_price:
        return None, None
    risk = stop - entry_price
    for j in range(1, max_hold + 1):
        k = entry_idx + j
        if m_high[k] >= stop:
            return -1, -1.0
        if m_low[k] <= tp:
            return +1, (entry_price - tp) / risk
    exit_price = m_close[entry_idx + max_hold]
    return 0, (entry_price - exit_price) / risk


def sim_variant_A_long(m_close, m_high, m_low, i, max_hold):
    entry = m_close[i]
    return _sim_long_core(m_close, m_high, m_low, i, entry,
                          entry * (1 + TP_PCT), entry * (1 - STOP_PCT), max_hold)


def sim_variant_A_short(m_close, m_high, m_low, i, max_hold):
    entry = m_close[i]
    return _sim_short_core(m_close, m_high, m_low, i, entry,
                           entry * (1 - TP_PCT), entry * (1 + STOP_PCT), max_hold)


def sim_variant_B_long(m_close, m_high, m_low, i, max_hold, midline_i, lower_i, atr_i):
    entry = m_close[i]
    return _sim_long_core(m_close, m_high, m_low, i, entry,
                          midline_i, lower_i - ATR_STOP_MULT * atr_i, max_hold)


def sim_variant_B_short(m_close, m_high, m_low, i, max_hold, midline_i, upper_i, atr_i):
    entry = m_close[i]
    return _sim_short_core(m_close, m_high, m_low, i, entry,
                           midline_i, upper_i + ATR_STOP_MULT * atr_i, max_hold)


def _stop_entry_fill_long(m_high, i, level, wait_bars):
    """Return fill_idx if filled within wait window, else None."""
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


def sim_variant_C_long(m_close, m_high, m_low, i, max_hold, lower_i):
    fill = _stop_entry_fill_long(m_high, i, lower_i, WAIT_BARS)
    if fill is None:
        return None, None
    entry = lower_i
    return _sim_long_core(m_close, m_high, m_low, fill, entry,
                          entry * (1 + TP_PCT), entry * (1 - STOP_PCT), max_hold)


def sim_variant_C_short(m_close, m_high, m_low, i, max_hold, upper_i):
    fill = _stop_entry_fill_short(m_low, i, upper_i, WAIT_BARS)
    if fill is None:
        return None, None
    entry = upper_i
    return _sim_short_core(m_close, m_high, m_low, fill, entry,
                           entry * (1 - TP_PCT), entry * (1 + STOP_PCT), max_hold)


def sim_variant_D_long(m_close, m_high, m_low, i, max_hold, midline_i, lower_i, atr_i):
    fill = _stop_entry_fill_long(m_high, i, lower_i, WAIT_BARS)
    if fill is None:
        return None, None
    entry = lower_i
    return _sim_long_core(m_close, m_high, m_low, fill, entry,
                          midline_i, lower_i - ATR_STOP_MULT * atr_i, max_hold)


def sim_variant_D_short(m_close, m_high, m_low, i, max_hold, midline_i, upper_i, atr_i):
    fill = _stop_entry_fill_short(m_low, i, upper_i, WAIT_BARS)
    if fill is None:
        return None, None
    entry = upper_i
    return _sim_short_core(m_close, m_high, m_low, fill, entry,
                           midline_i, upper_i + ATR_STOP_MULT * atr_i, max_hold)


def expectancy_stats(r_values):
    """Return (n, mean_r, se, ci_low, ci_high)."""
    if not r_values:
        return 0, float("nan"), float("nan"), float("nan"), float("nan")
    rs = np.asarray(r_values, dtype=float)
    n = len(rs)
    mean_r = float(rs.mean())
    if n < 2:
        return n, mean_r, float("nan"), float("nan"), float("nan")
    se = float(rs.std(ddof=1) / np.sqrt(n))
    ci_low = mean_r - 1.96 * se
    ci_high = mean_r + 1.96 * se
    return n, mean_r, se, ci_low, ci_high


def sweep_pair(pair, timeframe, max_hold, periods, stds, depths, directions):
    store = FxStore()
    raw = store.load(pair, granularity=timeframe, include_incomplete=False)
    if raw is None or raw.empty:
        return []

    mid = ohlc_mid(raw)
    m_close = mid["close"].to_numpy(dtype=float)
    m_high = mid["high"].to_numpy(dtype=float)
    m_low = mid["low"].to_numpy(dtype=float)
    atr_arr = atr(mid, period=ATR_PERIOD).to_numpy(dtype=float)

    rows = []
    for period in periods:
        for std in stds:
            bb = bollinger_bands(mid, period=period, n_std=std)
            lower = bb["lower"].to_numpy(dtype=float)
            upper = bb["upper"].to_numpy(dtype=float)
            middle = bb["middle"].to_numpy(dtype=float)
            bw = upper - lower

            for direction in directions:
                if direction == "long":
                    find = find_fresh_long
                    band = lower
                else:
                    find = find_fresh_short
                    band = upper

                for depth in depths:
                    triggers = find(m_close, band, bw, depth)
                    r_by_variant = {v: [] for v in "ABCD"}
                    counts_by_variant = {v: {"w": 0, "l": 0, "t": 0} for v in "ABCD"}

                    for i in triggers:
                        i = int(i)
                        if np.isnan(atr_arr[i]) or np.isnan(middle[i]) or np.isnan(lower[i]):
                            continue

                        if direction == "long":
                            results = [
                                sim_variant_A_long(m_close, m_high, m_low, i, max_hold),
                                sim_variant_B_long(m_close, m_high, m_low, i, max_hold,
                                                    middle[i], lower[i], atr_arr[i]),
                                sim_variant_C_long(m_close, m_high, m_low, i, max_hold, lower[i]),
                                sim_variant_D_long(m_close, m_high, m_low, i, max_hold,
                                                    middle[i], lower[i], atr_arr[i]),
                            ]
                        else:
                            results = [
                                sim_variant_A_short(m_close, m_high, m_low, i, max_hold),
                                sim_variant_B_short(m_close, m_high, m_low, i, max_hold,
                                                     middle[i], upper[i], atr_arr[i]),
                                sim_variant_C_short(m_close, m_high, m_low, i, max_hold, upper[i]),
                                sim_variant_D_short(m_close, m_high, m_low, i, max_hold,
                                                     middle[i], upper[i], atr_arr[i]),
                            ]

                        for v, (outcome, r_val) in zip("ABCD", results):
                            if outcome is None:
                                continue
                            r_by_variant[v].append(r_val)
                            if outcome == +1:
                                counts_by_variant[v]["w"] += 1
                            elif outcome == -1:
                                counts_by_variant[v]["l"] += 1
                            else:
                                counts_by_variant[v]["t"] += 1

                    for v in "ABCD":
                        n, mean_r, se, ci_low, ci_high = expectancy_stats(r_by_variant[v])
                        c = counts_by_variant[v]
                        rows.append({
                            "pair": pair, "tf": timeframe,
                            "period": period, "std": std, "depth": depth,
                            "direction": direction, "variant": v,
                            "n": n, "w": c["w"], "l": c["l"], "t": c["t"],
                            "mean_r": mean_r, "se_r": se,
                            "ci_low_r": ci_low, "ci_high_r": ci_high,
                        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--out", default="/root/BlueHorseshoe/research/bb_execution_v1/sweep.csv")
    ap.add_argument("--pairs", default=None)
    args = ap.parse_args()

    if args.smoke:
        pairs = ["EUR_USD", "EUR_CAD"]
        timeframes = {"H4": 14 * 6}
        periods = [20, 30]
        stds = [2.0]
        depths = [0.0, 0.25]
        directions = ["long", "short"]
    else:
        pairs = args.pairs.split(",") if args.pairs else PAIRS_FULL
        timeframes = TIMEFRAMES
        periods = BB_PERIODS
        stds = BB_STDS
        depths = DEPTHS
        directions = DIRECTIONS

    n_param_cells = len(periods) * len(stds) * len(depths) * len(directions)
    print(f"Sweep: {len(pairs)} pairs × {n_param_cells} params × 4 variants = "
          f"{len(pairs) * n_param_cells * 4} rows")
    print(f"Output: {args.out}\n")

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
    print(f"\nWrote {len(df)} rows to {args.out}\n")

    if df.empty:
        return

    print("=== Phase 0 cells with n>=50 AND expectancy CI lower > 0, by variant ===\n")
    for v in "ABCD":
        sub = df[df["variant"] == v]
        clears = sub[(sub["ci_low_r"] > 0.0) & (sub["n"] >= 50)]
        n_clears = len(clears)
        print(f"  Variant {v}: {n_clears}/{len(sub)} cells ({100*n_clears/len(sub):.1f}%)")
        if n_clears > 0:
            print(f"    Top 5 by mean R:")
            for _, r in clears.sort_values("mean_r", ascending=False).head(5).iterrows():
                wr = r["w"] / max(r["w"] + r["l"], 1)
                print(f"      {r['pair']:<10} p={int(r['period'])} std={r['std']:.1f} "
                      f"depth={r['depth']:.2f} {r['direction']:<5}  "
                      f"n={int(r['n'])} W/L/T={int(r['w'])}/{int(r['l'])}/{int(r['t'])} "
                      f"WR={wr*100:.1f}% mean_R={r['mean_r']:+.3f} "
                      f"CI=[{r['ci_low_r']:+.3f}, {r['ci_high_r']:+.3f}]")
        print()


if __name__ == "__main__":
    main()
