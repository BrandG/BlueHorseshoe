"""MACD as filter/confirmation — cohort-delta test on BB v1 and Stoch v1 hosts.

Question: even though MACD-as-trigger doesn't show solo edge at 1%/1% RR
(see sweep_macd_triggers.py), does MACD's *state* at entry add information
to existing strategies? I.e., are trades taken when MACD says "trend agrees
with my direction" systematically better than trades when MACD disagrees?

Methodology (mirrors feedback_signal_role_by_solo_edge.md cohort-delta pattern):

  1. Re-generate trade ledgers from BB v1 and Stoch v1 production cells.
  2. For each trade, look up MACD state at the entry bar's timestamp.
  3. Split trades into PASS (filter aligned with direction) vs FAIL cohorts.
  4. Compare avg R, WR per cohort.

State forms tested (long-trade direction; short trades use mirror):
  - macd_above_zero        — macd > 0
  - macd_above_signal      — macd > signal
  - hist_above_zero        — histogram > 0   (= macd > signal)
  - hist_rising_2          — histogram[i] > histogram[i-1] > histogram[i-2]
  - hist_rising_3          — same with 3 consecutive rises
  - macd_above_zero_for_N  — macd > 0 for the last 5 bars (established trend)

MACD parameter combos:
  - (12, 26, 9)   classic
  - (24, 52, 9)   slow (showed slight tilt in trigger sweep)
  - (6, 13, 5)    fast

Output: table of cohort deltas per (host, MACD params, filter form). No CI gates;
the user inspects the structure.
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

# Production specs from BB_STRATEGY_v1.md and STOCH_STRATEGY_v1.md.
BB_V1_SPEC = [
    # (pair, period, std, depth, direction, confirm)
    ("CAD_CHF", 10, 1.5, 0.00, "short", "none"),
    ("USD_JPY", 10, 1.5, 0.00, "long",  "rise_0.00%"),
    ("EUR_CAD", 50, 2.0, 0.00, "long",  "none"),
    ("CHF_JPY", 50, 2.0, 0.00, "long",  "none"),
]

STOCH_V1_SPEC = [
    # (pair, k_period, d_period, threshold, recovery, direction)
    ("CHF_JPY", 5,  3, 20, 1, "long"),
    ("EUR_GBP", 14, 3, 30, 1, "long"),
    ("USD_JPY", 9,  3, 25, 1, "long"),
    ("CAD_CHF", 5,  3, 15, 1, "short"),
]

MACD_PARAMS = [(12, 26, 9), (24, 52, 9), (6, 13, 5)]


# ----- BB trigger + sim (mid-only — filter test is RR-irrelevant in the sense
# that we're comparing cohorts WITHIN a host; but using same RR as production
# specs to stay apples-to-apples) -----

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
    # rise_X.XX% — long requires next bar close >= trigger close × (1 + frac);
    # short requires <= (1 - frac)
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
    # timeout — return mid R
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


# ----- Trade collection -----

@dataclass
class Trade:
    pair: str
    direction: str
    entry_idx: int   # index into the pair's bar array
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
            trades.append(Trade(pair=pair, direction=direction, entry_idx=entry_idx, r=r))
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
            trades.append(Trade(pair=pair, direction=direction, entry_idx=int(i), r=r))
    return trades, pair_data


# ----- MACD state computation per pair -----

def macd_states(pair_data: dict, fast: int, slow: int, signal: int):
    """Compute per-pair arrays of MACD state at every bar index.

    Returns dict[pair] -> dict of state_name -> np.ndarray[bool].
    """
    out = {}
    for pair, raw in pair_data.items():
        mid = ohlc_mid(raw)
        df_m = macd(mid, fast=fast, slow=slow, signal=signal)
        m = df_m["macd"].to_numpy(dtype=float)
        s = df_m["signal"].to_numpy(dtype=float)
        h = df_m["histogram"].to_numpy(dtype=float)

        states = {}
        states["macd_above_zero"] = m > 0
        states["macd_above_signal"] = m > s
        states["hist_above_zero"] = h > 0

        # hist_rising_2: h[i] > h[i-1] > h[i-2]
        rising2 = np.zeros(len(h), dtype=bool)
        rising2[2:] = (h[2:] > h[1:-1]) & (h[1:-1] > h[:-2])
        states["hist_rising_2"] = rising2

        # hist_rising_3
        rising3 = np.zeros(len(h), dtype=bool)
        rising3[3:] = (h[3:] > h[2:-1]) & (h[2:-1] > h[1:-2]) & (h[1:-2] > h[:-3])
        states["hist_rising_3"] = rising3

        # macd_above_zero_for_5
        above = m > 0
        all5 = np.zeros(len(m), dtype=bool)
        for i in range(4, len(m)):
            all5[i] = bool(np.all(above[i - 4: i + 1]))
        states["macd_above_zero_for_5"] = all5

        # NaN-mask each state to False where macd/signal/histogram is undefined
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
    # For shorts, the filter is "the bear-flavored version" — i.e., NOT the
    # bull state. Mirror by negating.
    if trade.direction == "short":
        return not raw_state
    return raw_state


def cohort_stats(trades: list[Trade], filter_passes: list[bool]):
    """Return (pass_n, pass_avg_r, pass_wr, fail_n, fail_avg_r, fail_wr, delta_r, delta_wr)."""
    rs_pass = [t.r for t, p in zip(trades, filter_passes) if p]
    rs_fail = [t.r for t, p in zip(trades, filter_passes) if not p]

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


def report_for_host(name: str, trades: list[Trade], pair_data: dict):
    print(f"\n{'=' * 70}")
    print(f"HOST: {name}")
    print(f"{'=' * 70}")
    print(f"Total trades: {len(trades)}")
    if not trades:
        return
    overall_avg_r = float(np.mean([t.r for t in trades]))
    decisive = sum(1 for t in trades if abs(t.r) > 0.999)
    wins = sum(1 for t in trades if t.r > 0.999)
    overall_wr = wins / decisive if decisive else float("nan")
    print(f"Overall: avg R = {overall_avg_r:+.3f}  WR_decisive = {overall_wr*100:.1f}%  "
          f"(n_decisive = {decisive})")

    state_names = ["macd_above_zero", "macd_above_signal", "hist_above_zero",
                   "hist_rising_2", "hist_rising_3", "macd_above_zero_for_5"]

    for fast, slow, sig in MACD_PARAMS:
        print(f"\n  MACD ({fast},{slow},{sig})")
        print(f"    {'filter':<25} {'pass_n':>7} {'p_avgR':>8} {'p_WR':>7}  "
              f"{'fail_n':>7} {'f_avgR':>8} {'f_WR':>7}  {'dAvgR':>8} {'dWR':>7}")
        states_by_pair = macd_states(pair_data, fast, slow, sig)
        for st in state_names:
            passes = [state_for_trade(t, states_by_pair, st) for t in trades]
            p_n, p_r, p_wr, f_n, f_r, f_wr, dR, dWR = cohort_stats(trades, passes)
            print(f"    {st:<25} {p_n:>7} {p_r:>+8.3f} {p_wr*100:>6.1f}%  "
                  f"{f_n:>7} {f_r:>+8.3f} {f_wr*100:>6.1f}%  "
                  f"{dR:>+8.3f} {dWR*100:>+6.1f}pp")


def main():
    print("Collecting BB v1 trades…")
    bb_trades, bb_pair_data = collect_bb_trades(BB_V1_SPEC)
    print(f"  {len(bb_trades)} trades across {len(bb_pair_data)} pairs")

    print("Collecting Stoch v1 trades…")
    stoch_trades, stoch_pair_data = collect_stoch_trades(STOCH_V1_SPEC)
    print(f"  {len(stoch_trades)} trades across {len(stoch_pair_data)} pairs")

    report_for_host("BB v1", bb_trades, bb_pair_data)
    report_for_host("Stoch v1", stoch_trades, stoch_pair_data)

    print("\nNote on cohort meaning: filter PASSES are bars where MACD's bull state")
    print("aligns with trade direction (short trades use the inverted state). FAILs")
    print("are everything else. ΔavgR > 0 means filter cohort outperforms anti-cohort.")


if __name__ == "__main__":
    main()
