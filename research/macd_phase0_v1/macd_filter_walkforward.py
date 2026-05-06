"""MACD-as-filter walk-forward cohort-delta test.

Mirror of macd_filter_cohort_test.py but splits each host's trade ledger
70/30 by entry timestamp and reports cohort delta on each half. A filter is
"walk-forward stable" if the sign of dAvgR is preserved across train and test.

Filters tested (chosen from the in-sample run as the strongest positives + the
strongest negatives — confirming both directions guards against accidentally
recommending a sign-flipping signal):

  Positive candidates:
    - macd_above_signal        (= hist_above_zero)
    - hist_rising_2
    - hist_rising_3

  Anti-edge candidates (verifying the negative is real, not noise):
    - macd_above_zero
    - macd_above_zero_for_5

MACD param combos: (12,26,9), (24,52,9), (6,13,5) — same as in-sample.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/src")

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import bollinger_bands, macd, ohlc_mid, stochastic


GRANULARITY = "H4"
MAX_HOLD = 14 * 6
TP_PCT = 0.01
STOP_PCT = 0.01
TRAIN_FRAC = 0.7

BB_V1_SPEC = [
    ("CAD_CHF", 10, 1.5, 0.00, "short", "none"),
    ("USD_JPY", 10, 1.5, 0.00, "long",  "rise_0.00%"),
    ("EUR_CAD", 50, 2.0, 0.00, "long",  "none"),
    ("CHF_JPY", 50, 2.0, 0.00, "long",  "none"),
]

STOCH_V1_SPEC = [
    ("CHF_JPY", 5,  3, 20, 1, "long"),
    ("EUR_GBP", 14, 3, 30, 1, "long"),
    ("USD_JPY", 9,  3, 25, 1, "long"),
    ("CAD_CHF", 5,  3, 15, 1, "short"),
]

MACD_PARAMS = [(12, 26, 9), (24, 52, 9), (6, 13, 5)]
FILTER_NAMES = [
    "macd_above_signal",
    "hist_rising_2",
    "hist_rising_3",
    "macd_above_zero",
    "macd_above_zero_for_5",
    # Negated forms — explicit "established opposite-direction trend" filters.
    # The cohort theory (mean reversion off an established trend) actually works
    # in our favor here: e.g. "BB long when MACD has been < 0 for 5 bars".
    "macd_below_zero",
    "macd_below_zero_for_5",
    "macd_below_signal",
    "hist_falling_2",
    "hist_falling_3",
]


def _find_fresh(arr_cond):
    fresh = arr_cond & ~np.roll(arr_cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def bb_triggers(close, lower, upper, bw, depth, direction):
    if direction == "long":
        return _find_fresh(close < (lower - depth * bw))
    return _find_fresh(close > (upper + depth * bw))


def bb_confirm_idx(close_mid, lower, upper, i, direction, confirm_str):
    if confirm_str == "none":
        return i
    if i + 1 >= len(close_mid):
        return None
    if confirm_str == "bare":
        if direction == "long":
            return i + 1 if close_mid[i + 1] > lower[i + 1] else None
        return i + 1 if close_mid[i + 1] < upper[i + 1] else None
    frac = float(confirm_str.replace("rise_", "").replace("%", "")) / 100.0
    if direction == "long":
        return i + 1 if close_mid[i + 1] >= close_mid[i] * (1 + frac) else None
    return i + 1 if close_mid[i + 1] <= close_mid[i] * (1 - frac) else None


def stoch_long_triggers(k_arr, threshold, recovery):
    n = len(k_arr)
    if n < recovery + 1:
        return np.array([], dtype=int)
    diffs_pos = np.zeros(n, dtype=bool)
    diffs_pos[1:] = k_arr[1:] > k_arr[:-1]
    rising = np.zeros(n, dtype=bool)
    for i in range(recovery, n):
        rising[i] = bool(np.all(diffs_pos[i - recovery + 1: i + 1]))
    base = np.full(n, np.nan)
    base[recovery:] = k_arr[: n - recovery]
    cond = (~np.isnan(base)) & (~np.isnan(k_arr)) & rising & (base < threshold)
    return _find_fresh(cond)


def stoch_short_triggers(k_arr, threshold, recovery):
    n = len(k_arr)
    if n < recovery + 1:
        return np.array([], dtype=int)
    diffs_neg = np.zeros(n, dtype=bool)
    diffs_neg[1:] = k_arr[1:] < k_arr[:-1]
    falling = np.zeros(n, dtype=bool)
    for i in range(recovery, n):
        falling[i] = bool(np.all(diffs_neg[i - recovery + 1: i + 1]))
    base = np.full(n, np.nan)
    base[recovery:] = k_arr[: n - recovery]
    upper = 100.0 - threshold
    cond = (~np.isnan(base)) & (~np.isnan(k_arr)) & falling & (base > upper)
    return _find_fresh(cond)


def sim_long_mid(close, high, low, i, max_hold):
    if i + max_hold >= len(close):
        return None
    entry = close[i]
    tp = entry * (1 + TP_PCT)
    stop = entry * (1 - STOP_PCT)
    for j in range(1, max_hold + 1):
        k = i + j
        if low[k] <= stop:
            return -1.0
        if high[k] >= tp:
            return +1.0
    return (close[i + max_hold] - entry) / (entry * STOP_PCT)


def sim_short_mid(close, high, low, i, max_hold):
    if i + max_hold >= len(close):
        return None
    entry = close[i]
    tp = entry * (1 - TP_PCT)
    stop = entry * (1 + STOP_PCT)
    for j in range(1, max_hold + 1):
        k = i + j
        if high[k] >= stop:
            return -1.0
        if low[k] <= tp:
            return +1.0
    return (entry - close[i + max_hold]) / (entry * STOP_PCT)


@dataclass
class Trade:
    pair: str
    direction: str
    entry_idx: int
    entry_ts: pd.Timestamp
    r: float


def collect_bb_trades(spec) -> tuple[list[Trade], dict]:
    trades: list[Trade] = []
    pair_data: dict[str, pd.DataFrame] = {}
    store = FxStore()
    for pair, period, std, depth, direction, confirm in spec:
        raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
        if raw is None or raw.empty:
            continue
        pair_data[pair] = raw
        ts = raw["timestamp"].to_numpy()
        mid = ohlc_mid(raw)
        m_close = mid["close"].to_numpy(dtype=float)
        m_high = mid["high"].to_numpy(dtype=float)
        m_low = mid["low"].to_numpy(dtype=float)
        bb = bollinger_bands(mid, period=period, n_std=std)
        lower = bb["lower"].to_numpy(dtype=float)
        upper = bb["upper"].to_numpy(dtype=float)
        bw = upper - lower

        triggers = bb_triggers(m_close, lower, upper, bw, depth, direction)
        sim = sim_long_mid if direction == "long" else sim_short_mid
        for i in triggers:
            entry_idx = bb_confirm_idx(m_close, lower, upper, int(i), direction, confirm)
            if entry_idx is None:
                continue
            r = sim(m_close, m_high, m_low, entry_idx, MAX_HOLD)
            if r is None:
                continue
            trades.append(Trade(pair=pair, direction=direction,
                                entry_idx=entry_idx, entry_ts=pd.Timestamp(ts[entry_idx]),
                                r=r))
    return trades, pair_data


def collect_stoch_trades(spec) -> tuple[list[Trade], dict]:
    trades: list[Trade] = []
    pair_data: dict[str, pd.DataFrame] = {}
    store = FxStore()
    for pair, k_period, d_period, threshold, recovery, direction in spec:
        raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
        if raw is None or raw.empty:
            continue
        pair_data[pair] = raw
        ts = raw["timestamp"].to_numpy()
        mid = ohlc_mid(raw)
        m_close = mid["close"].to_numpy(dtype=float)
        m_high = mid["high"].to_numpy(dtype=float)
        m_low = mid["low"].to_numpy(dtype=float)
        stoch = stochastic(mid, k_period=k_period, d_period=d_period)
        k_arr = stoch["k"].to_numpy(dtype=float)

        if direction == "long":
            triggers = stoch_long_triggers(k_arr, threshold, recovery)
            sim = sim_long_mid
        else:
            triggers = stoch_short_triggers(k_arr, threshold, recovery)
            sim = sim_short_mid

        for i in triggers:
            r = sim(m_close, m_high, m_low, int(i), MAX_HOLD)
            if r is None:
                continue
            trades.append(Trade(pair=pair, direction=direction,
                                entry_idx=int(i), entry_ts=pd.Timestamp(ts[i]),
                                r=r))
    return trades, pair_data


def macd_states(pair_data: dict, fast: int, slow: int, signal: int):
    out = {}
    for pair, raw in pair_data.items():
        mid = ohlc_mid(raw)
        df_m = macd(mid, fast=fast, slow=slow, signal=signal)
        m = df_m["macd"].to_numpy(dtype=float)
        s = df_m["signal"].to_numpy(dtype=float)
        h = df_m["histogram"].to_numpy(dtype=float)

        states = {
            "macd_above_zero": m > 0,
            "macd_above_signal": m > s,
            "hist_above_zero": h > 0,
        }
        rising2 = np.zeros(len(h), dtype=bool)
        rising2[2:] = (h[2:] > h[1:-1]) & (h[1:-1] > h[:-2])
        states["hist_rising_2"] = rising2

        rising3 = np.zeros(len(h), dtype=bool)
        rising3[3:] = (h[3:] > h[2:-1]) & (h[2:-1] > h[1:-2]) & (h[1:-2] > h[:-3])
        states["hist_rising_3"] = rising3

        above = m > 0
        all5 = np.zeros(len(m), dtype=bool)
        for i in range(4, len(m)):
            all5[i] = bool(np.all(above[i - 4: i + 1]))
        states["macd_above_zero_for_5"] = all5

        # Negated forms — require MACD to be defined (not NaN) and below.
        states["macd_below_zero"] = m < 0
        states["macd_below_signal"] = m < s

        below = m < 0
        below5 = np.zeros(len(m), dtype=bool)
        for i in range(4, len(m)):
            below5[i] = bool(np.all(below[i - 4: i + 1]))
        states["macd_below_zero_for_5"] = below5

        falling2 = np.zeros(len(h), dtype=bool)
        falling2[2:] = (h[2:] < h[1:-1]) & (h[1:-1] < h[:-2])
        states["hist_falling_2"] = falling2

        falling3 = np.zeros(len(h), dtype=bool)
        falling3[3:] = (h[3:] < h[2:-1]) & (h[2:-1] < h[1:-2]) & (h[1:-2] < h[:-3])
        states["hist_falling_3"] = falling3

        nan_mask = np.isnan(m) | np.isnan(s) | np.isnan(h)
        for k in states:
            states[k] = states[k] & ~nan_mask
        out[pair] = states
    return out


def state_for_trade(trade: Trade, states_by_pair: dict, state_name: str) -> bool:
    arr = states_by_pair[trade.pair][state_name]
    if trade.entry_idx >= len(arr):
        return False
    raw_state = bool(arr[trade.entry_idx])
    if trade.direction == "short":
        return not raw_state
    return raw_state


def cohort_stats(trades, passes):
    rs_pass = [t.r for t, p in zip(trades, passes) if p]
    rs_fail = [t.r for t, p in zip(trades, passes) if not p]

    def _stats(rs):
        if not rs:
            return 0, float("nan"), float("nan")
        rs_arr = np.array(rs)
        wins = int((rs_arr >= 1.0 - 1e-9).sum())
        losses = int((rs_arr <= -1.0 + 1e-9).sum())
        decisive = wins + losses
        wr = wins / decisive if decisive > 0 else float("nan")
        return len(rs), float(rs_arr.mean()), wr

    p_n, p_r, p_wr = _stats(rs_pass)
    f_n, f_r, f_wr = _stats(rs_fail)
    delta_r = (p_r - f_r) if (not np.isnan(p_r) and not np.isnan(f_r)) else float("nan")
    delta_wr = (p_wr - f_wr) if (not np.isnan(p_wr) and not np.isnan(f_wr)) else float("nan")
    return p_n, p_r, p_wr, f_n, f_r, f_wr, delta_r, delta_wr


def _safe_signs_match(a, b):
    if np.isnan(a) or np.isnan(b):
        return False
    if a == 0 or b == 0:
        return False
    return (a > 0) == (b > 0)


def report_for_host(name: str, trades: list[Trade], pair_data: dict):
    print(f"\n{'=' * 78}")
    print(f"HOST: {name}")
    print(f"{'=' * 78}")
    if not trades:
        print("No trades.")
        return

    trades_sorted = sorted(trades, key=lambda t: t.entry_ts)
    cut = int(len(trades_sorted) * TRAIN_FRAC)
    train = trades_sorted[:cut]
    test = trades_sorted[cut:]
    boundary = test[0].entry_ts if test else trades_sorted[-1].entry_ts

    print(f"Total trades: {len(trades_sorted)}  (train n={len(train)}, test n={len(test)})")
    print(f"Train/test split timestamp: {boundary.date()}")
    overall_r = float(np.mean([t.r for t in trades_sorted]))
    print(f"Overall avg R: {overall_r:+.3f}")

    for fast, slow, sig in MACD_PARAMS:
        print(f"\n  MACD ({fast},{slow},{sig})")
        print(f"    {'filter':<24}  {'TR_pass':>7} {'tr_dR':>7} {'tr_dWR':>7}   "
              f"{'TE_pass':>7} {'te_dR':>7} {'te_dWR':>7}   stable")
        states_by_pair = macd_states(pair_data, fast, slow, sig)
        for st in FILTER_NAMES:
            tr_passes = [state_for_trade(t, states_by_pair, st) for t in train]
            te_passes = [state_for_trade(t, states_by_pair, st) for t in test]
            tr = cohort_stats(train, tr_passes)
            te = cohort_stats(test, te_passes)
            tr_pn, _, _, _, _, _, tr_dR, tr_dWR = tr
            te_pn, _, _, _, _, _, te_dR, te_dWR = te
            stable = _safe_signs_match(tr_dR, te_dR)
            stable_str = "STABLE" if stable else "FLIP"
            print(f"    {st:<24}  {tr_pn:>7} {tr_dR:>+7.3f} {tr_dWR*100:>+6.1f}pp   "
                  f"{te_pn:>7} {te_dR:>+7.3f} {te_dWR*100:>+6.1f}pp   {stable_str}")


def main():
    print("Collecting BB v1 trades…")
    bb_trades, bb_pair_data = collect_bb_trades(BB_V1_SPEC)
    print(f"  {len(bb_trades)} trades")

    print("Collecting Stoch v1 trades…")
    stoch_trades, stoch_pair_data = collect_stoch_trades(STOCH_V1_SPEC)
    print(f"  {len(stoch_trades)} trades")

    report_for_host("BB v1", bb_trades, bb_pair_data)
    report_for_host("Stoch v1", stoch_trades, stoch_pair_data)

    print("\nLegend: tr_dR / te_dR are (avg R of pass cohort) - (avg R of fail cohort).")
    print("STABLE = sign of dR matches between train and test halves.")


if __name__ == "__main__":
    main()
