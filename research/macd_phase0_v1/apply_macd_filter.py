"""Apply the MACD_FILTER_v1 filter to BB v1 and Stoch v1 portfolios.

Shows portfolio-level impact of the headline filter:
  macd_below_zero_for_5_bars at MACD(12, 26, 9), with direction mirror.

For each host, reports unfiltered baseline vs filtered side-by-side, including
walk-forward train/test split (same boundary used in cohort tests).

Metrics per portfolio:
  - n trades, decisive WR, avg R per trade
  - cumulative R, max drawdown (R), max consecutive losses
  - max simultaneous open positions
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

FILTER_FAST, FILTER_SLOW, FILTER_SIGNAL = 12, 26, 9
FILTER_WINDOW = 5  # "macd_below_zero for N consecutive bars"

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
        return None, None
    entry = close[i]
    tp = entry * (1 + TP_PCT)
    stop = entry * (1 - STOP_PCT)
    for j in range(1, max_hold + 1):
        k = i + j
        if low[k] <= stop:
            return -1.0, k
        if high[k] >= tp:
            return +1.0, k
    return ((close[i + max_hold] - entry) / (entry * STOP_PCT)), i + max_hold


def sim_short_mid(close, high, low, i, max_hold):
    if i + max_hold >= len(close):
        return None, None
    entry = close[i]
    tp = entry * (1 - TP_PCT)
    stop = entry * (1 + STOP_PCT)
    for j in range(1, max_hold + 1):
        k = i + j
        if high[k] >= stop:
            return -1.0, k
        if low[k] <= tp:
            return +1.0, k
    return ((entry - close[i + max_hold]) / (entry * STOP_PCT)), i + max_hold


@dataclass
class Trade:
    pair: str
    direction: str
    entry_idx: int
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    r: float
    filter_pass: bool


def macd_below_for_n(macd_arr: np.ndarray, n: int) -> np.ndarray:
    """True at bar i if macd[i-n+1..i] all < 0 (strictly)."""
    out = np.zeros(len(macd_arr), dtype=bool)
    below = macd_arr < 0
    for i in range(n - 1, len(macd_arr)):
        out[i] = bool(np.all(below[i - n + 1: i + 1]))
    out[np.isnan(macd_arr)] = False
    return out


def macd_above_for_n(macd_arr: np.ndarray, n: int) -> np.ndarray:
    out = np.zeros(len(macd_arr), dtype=bool)
    above = macd_arr > 0
    for i in range(n - 1, len(macd_arr)):
        out[i] = bool(np.all(above[i - n + 1: i + 1]))
    out[np.isnan(macd_arr)] = False
    return out


def collect_bb_trades(spec) -> list[Trade]:
    trades: list[Trade] = []
    store = FxStore()
    for pair, period, std, depth, direction, confirm in spec:
        raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
        if raw is None or raw.empty:
            continue
        ts = raw["timestamp"].to_numpy()
        mid = ohlc_mid(raw)
        m_close = mid["close"].to_numpy(dtype=float)
        m_high = mid["high"].to_numpy(dtype=float)
        m_low = mid["low"].to_numpy(dtype=float)
        bb = bollinger_bands(mid, period=period, n_std=std)
        lower = bb["lower"].to_numpy(dtype=float)
        upper = bb["upper"].to_numpy(dtype=float)
        bw = upper - lower

        df_macd = macd(mid, fast=FILTER_FAST, slow=FILTER_SLOW, signal=FILTER_SIGNAL)
        macd_arr = df_macd["macd"].to_numpy(dtype=float)
        # For long trades: filter passes when macd has been below 0 for N bars.
        # For short trades: filter passes when macd has been above 0 for N bars.
        below_for_n = macd_below_for_n(macd_arr, FILTER_WINDOW)
        above_for_n = macd_above_for_n(macd_arr, FILTER_WINDOW)

        triggers = bb_triggers(m_close, lower, upper, bw, depth, direction)
        sim = sim_long_mid if direction == "long" else sim_short_mid
        for i in triggers:
            entry_idx = bb_confirm_idx(m_close, lower, upper, int(i), direction, confirm)
            if entry_idx is None:
                continue
            r, exit_idx = sim(m_close, m_high, m_low, entry_idx, MAX_HOLD)
            if r is None:
                continue
            if direction == "long":
                fpass = bool(below_for_n[entry_idx])
            else:
                fpass = bool(above_for_n[entry_idx])
            trades.append(Trade(pair=pair, direction=direction,
                                entry_idx=entry_idx,
                                entry_ts=pd.Timestamp(ts[entry_idx]),
                                exit_ts=pd.Timestamp(ts[exit_idx]),
                                r=r, filter_pass=fpass))
    return trades


def collect_stoch_trades(spec) -> list[Trade]:
    trades: list[Trade] = []
    store = FxStore()
    for pair, k_period, d_period, threshold, recovery, direction in spec:
        raw = store.load(pair, granularity=GRANULARITY, include_incomplete=False)
        if raw is None or raw.empty:
            continue
        ts = raw["timestamp"].to_numpy()
        mid = ohlc_mid(raw)
        m_close = mid["close"].to_numpy(dtype=float)
        m_high = mid["high"].to_numpy(dtype=float)
        m_low = mid["low"].to_numpy(dtype=float)
        stoch = stochastic(mid, k_period=k_period, d_period=d_period)
        k_arr = stoch["k"].to_numpy(dtype=float)

        df_macd = macd(mid, fast=FILTER_FAST, slow=FILTER_SLOW, signal=FILTER_SIGNAL)
        macd_arr = df_macd["macd"].to_numpy(dtype=float)
        below_for_n = macd_below_for_n(macd_arr, FILTER_WINDOW)
        above_for_n = macd_above_for_n(macd_arr, FILTER_WINDOW)

        if direction == "long":
            triggers = stoch_long_triggers(k_arr, threshold, recovery)
            sim = sim_long_mid
        else:
            triggers = stoch_short_triggers(k_arr, threshold, recovery)
            sim = sim_short_mid

        for i in triggers:
            r, exit_idx = sim(m_close, m_high, m_low, int(i), MAX_HOLD)
            if r is None:
                continue
            if direction == "long":
                fpass = bool(below_for_n[int(i)])
            else:
                fpass = bool(above_for_n[int(i)])
            trades.append(Trade(pair=pair, direction=direction,
                                entry_idx=int(i),
                                entry_ts=pd.Timestamp(ts[i]),
                                exit_ts=pd.Timestamp(ts[exit_idx]),
                                r=r, filter_pass=fpass))
    return trades


def wilson_ci(wins, decisive):
    if decisive == 0:
        return float("nan"), float("nan"), float("nan")
    p = wins / decisive
    se = np.sqrt(p * (1 - p) / decisive)
    return p, max(0.0, p - 1.96 * se), min(1.0, p + 1.96 * se)


def portfolio_stats(trades: list[Trade]) -> dict:
    if not trades:
        return {"n": 0}
    rs = np.array([t.r for t in trades])
    wins = int((rs >= 1.0 - 1e-9).sum())
    losses = int((rs <= -1.0 + 1e-9).sum())
    timeouts = len(rs) - wins - losses
    decisive = wins + losses
    wr, ci_low, ci_high = wilson_ci(wins, decisive)

    cum = np.cumsum(rs)
    running_max = np.maximum.accumulate(cum)
    max_dd = float((cum - running_max).min())

    signs = np.sign(rs)
    max_consec_loss = current = 0
    for s in signs:
        if s < 0:
            current += 1
            max_consec_loss = max(max_consec_loss, current)
        else:
            current = 0

    events = []
    for t in trades:
        events.append((t.entry_ts, +1))
        events.append((t.exit_ts, -1))
    events.sort()
    max_concurrent = current_open = 0
    for _, delta in events:
        current_open += delta
        max_concurrent = max(max_concurrent, current_open)

    return {
        "n": len(rs),
        "wins": wins, "losses": losses, "timeouts": timeouts,
        "wr": wr, "ci_low": ci_low, "ci_high": ci_high,
        "avg_r": float(rs.mean()),
        "cum_r": float(cum[-1]),
        "max_dd": max_dd,
        "max_consec_loss": max_consec_loss,
        "max_concurrent": max_concurrent,
    }


def fmt_stats(s: dict) -> str:
    if s["n"] == 0:
        return "  (no trades)"
    return (f"    n={s['n']}  W/L/T={s['wins']}/{s['losses']}/{s['timeouts']}  "
            f"WR={s['wr']*100:.1f}% CI=[{s['ci_low']*100:.1f},{s['ci_high']*100:.1f}]\n"
            f"    avg R = {s['avg_r']:+.3f}  cum R = {s['cum_r']:+.1f}  "
            f"max DD = {s['max_dd']:.1f} R\n"
            f"    max consec losses = {s['max_consec_loss']}  "
            f"max simultaneous positions = {s['max_concurrent']}")


def report_for_host(name: str, trades: list[Trade]):
    print(f"\n{'=' * 78}")
    print(f"HOST: {name}")
    print(f"{'=' * 78}")
    if not trades:
        print("No trades."); return

    trades_sorted = sorted(trades, key=lambda t: t.entry_ts)
    cut = int(len(trades_sorted) * TRAIN_FRAC)
    train = trades_sorted[:cut]
    test = trades_sorted[cut:]
    boundary = test[0].entry_ts if test else trades_sorted[-1].entry_ts

    pass_pct = sum(t.filter_pass for t in trades_sorted) / len(trades_sorted) * 100
    print(f"Total trades: {len(trades_sorted)}  ({pass_pct:.1f}% pass filter)")
    print(f"Train n={len(train)}, test n={len(test)}, split at {boundary.date()}")

    for label, half in [("TRAIN", train), ("TEST", test), ("FULL", trades_sorted)]:
        print(f"\n  {label}")
        unfiltered = portfolio_stats(half)
        filtered = portfolio_stats([t for t in half if t.filter_pass])
        print("  UNFILTERED:")
        print(fmt_stats(unfiltered))
        print("  FILTERED (macd_below_zero_for_5):")
        print(fmt_stats(filtered))
        if unfiltered["n"] > 0 and filtered["n"] > 0:
            n_red = (1 - filtered["n"] / unfiltered["n"]) * 100
            r_diff = filtered["avg_r"] - unfiltered["avg_r"]
            cum_diff = filtered["cum_r"] - unfiltered["cum_r"]
            wr_diff = (filtered["wr"] - unfiltered["wr"]) * 100
            print(f"  IMPACT: trades -{n_red:.1f}%  avg R {r_diff:+.3f}  "
                  f"cum R {cum_diff:+.1f}  WR {wr_diff:+.1f}pp  "
                  f"max sim {filtered['max_concurrent']} vs {unfiltered['max_concurrent']}")


def main():
    print("Filter: MACD({},{},{}) macd_below_zero for {} consecutive bars".format(
        FILTER_FAST, FILTER_SLOW, FILTER_SIGNAL, FILTER_WINDOW))
    print("(direction-mirrored: shorts gated on macd_above_zero_for_5 instead)\n")

    print("Collecting BB v1 trades…")
    bb_trades = collect_bb_trades(BB_V1_SPEC)
    print(f"  {len(bb_trades)} trades")

    print("Collecting Stoch v1 trades…")
    stoch_trades = collect_stoch_trades(STOCH_V1_SPEC)
    print(f"  {len(stoch_trades)} trades")

    report_for_host("BB v1", bb_trades)
    report_for_host("Stoch v1", stoch_trades)


if __name__ == "__main__":
    main()
