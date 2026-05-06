"""Shared methodology for v2 reruns of BB / Stoch / SMA / RSI / CCI.

Common pieces:
- Sim with R tracking (mid + spread variants)
- Walk-forward 70/30 split
- Expectancy stats (mean R, SE, 95% CI)
- Spread-robust gate
- Production cell selection (largest te_n per pair)
- Portfolio assembly
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/src")

from bh_ftmo.data.fx_store import FxStore  # noqa: F401 - re-exported


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
TP_PCT = 0.01
STOP_PCT = 0.01
TRAIN_FRAC = 0.7
LIMIT_FILL_WINDOW = 1


def sim_long_mid(close, high, low, i, max_hold):
    """Mid-price long sim, fixed 1% RR. Returns (r_value, exit_idx) or (None, None)."""
    if i + max_hold >= len(close):
        return None, None
    entry = close[i]
    tp = entry * (1 + TP_PCT)
    stop = entry * (1 - STOP_PCT)
    risk = entry - stop
    for j in range(1, max_hold + 1):
        k = i + j
        if low[k] <= stop:
            return -1.0, k
        if high[k] >= tp:
            return (tp - entry) / risk, k
    exit_p = close[i + max_hold]
    return (exit_p - entry) / risk, i + max_hold


def sim_short_mid(close, high, low, i, max_hold):
    if i + max_hold >= len(close):
        return None, None
    entry = close[i]
    tp = entry * (1 - TP_PCT)
    stop = entry * (1 + STOP_PCT)
    risk = stop - entry
    for j in range(1, max_hold + 1):
        k = i + j
        if high[k] >= stop:
            return -1.0, k
        if low[k] <= tp:
            return (entry - tp) / risk, k
    exit_p = close[i + max_hold]
    return (entry - exit_p) / risk, i + max_hold


def sim_long_limit(close, high, low, i, max_hold, fill_window=LIMIT_FILL_WINDOW):
    """Limit-at-signal-bar-low long sim. Place limit at low[i], wait fill_window bars
    after signal close. If next bar's low <= limit_price, fill at limit_price.
    Otherwise (None, None). Same TP/SL semantics as sim_long_mid, anchored at fill bar.
    """
    limit_price = low[i]
    fill_idx = None
    for j in range(1, fill_window + 1):
        k = i + j
        if k >= len(close):
            return None, None
        if low[k] <= limit_price:
            fill_idx = k
            break
    if fill_idx is None:
        return None, None
    if fill_idx + max_hold >= len(close):
        return None, None
    entry = limit_price
    tp = entry * (1 + TP_PCT)
    stop = entry * (1 - STOP_PCT)
    risk = entry - stop
    for j in range(1, max_hold + 1):
        k = fill_idx + j
        if low[k] <= stop:
            return -1.0, k
        if high[k] >= tp:
            return (tp - entry) / risk, k
    exit_p = close[fill_idx + max_hold]
    return (exit_p - entry) / risk, fill_idx + max_hold


def sim_short_limit(close, high, low, i, max_hold, fill_window=LIMIT_FILL_WINDOW):
    """Limit-at-signal-bar-high short sim. Place limit at high[i], wait fill_window bars.
    If next bar's high >= limit_price, fill at limit_price. Otherwise (None, None).
    """
    limit_price = high[i]
    fill_idx = None
    for j in range(1, fill_window + 1):
        k = i + j
        if k >= len(close):
            return None, None
        if high[k] >= limit_price:
            fill_idx = k
            break
    if fill_idx is None:
        return None, None
    if fill_idx + max_hold >= len(close):
        return None, None
    entry = limit_price
    tp = entry * (1 - TP_PCT)
    stop = entry * (1 + STOP_PCT)
    risk = stop - entry
    for j in range(1, max_hold + 1):
        k = fill_idx + j
        if high[k] >= stop:
            return -1.0, k
        if low[k] <= tp:
            return (entry - tp) / risk, k
    exit_p = close[fill_idx + max_hold]
    return (entry - exit_p) / risk, fill_idx + max_hold


def sim_long_spread(ca, hb, lb, cb, i, max_hold):
    if i + max_hold >= len(ca):
        return None, None
    entry = ca[i]
    tp = entry * (1 + TP_PCT)
    stop = entry * (1 - STOP_PCT)
    risk = entry - stop
    for j in range(1, max_hold + 1):
        k = i + j
        if lb[k] <= stop:
            return -1.0, k
        if hb[k] >= tp:
            return (tp - entry) / risk, k
    exit_p = cb[i + max_hold]
    return (exit_p - entry) / risk, i + max_hold


def sim_short_spread(cb, ha, la, ca, i, max_hold):
    if i + max_hold >= len(cb):
        return None, None
    entry = cb[i]
    tp = entry * (1 - TP_PCT)
    stop = entry * (1 + STOP_PCT)
    risk = stop - entry
    for j in range(1, max_hold + 1):
        k = i + j
        if ha[k] >= stop:
            return -1.0, k
        if la[k] <= tp:
            return (entry - tp) / risk, k
    exit_p = ca[i + max_hold]
    return (entry - exit_p) / risk, i + max_hold


def sim_long_stop(close, high, low, i, max_hold, fill_window=LIMIT_FILL_WINDOW):
    """Stop-buy at signal-bar high. Order rests ABOVE market; fills when price
    extends UP through the level (continuation). Mirror of sim_long_limit but for
    breakout/trend-following shapes.
    """
    stop_price = high[i]
    fill_idx = None
    for j in range(1, fill_window + 1):
        k = i + j
        if k >= len(close):
            return None, None
        if high[k] >= stop_price:
            fill_idx = k
            break
    if fill_idx is None:
        return None, None
    if fill_idx + max_hold >= len(close):
        return None, None
    entry = stop_price
    tp = entry * (1 + TP_PCT)
    sl = entry * (1 - STOP_PCT)
    risk = entry - sl
    for j in range(1, max_hold + 1):
        k = fill_idx + j
        if low[k] <= sl:
            return -1.0, k
        if high[k] >= tp:
            return (tp - entry) / risk, k
    exit_p = close[fill_idx + max_hold]
    return (exit_p - entry) / risk, fill_idx + max_hold


def sim_short_stop(close, high, low, i, max_hold, fill_window=LIMIT_FILL_WINDOW):
    """Stop-sell at signal-bar low. Order rests BELOW market; fills when price
    extends DOWN through the level.
    """
    stop_price = low[i]
    fill_idx = None
    for j in range(1, fill_window + 1):
        k = i + j
        if k >= len(close):
            return None, None
        if low[k] <= stop_price:
            fill_idx = k
            break
    if fill_idx is None:
        return None, None
    if fill_idx + max_hold >= len(close):
        return None, None
    entry = stop_price
    tp = entry * (1 - TP_PCT)
    sl = entry * (1 + STOP_PCT)
    risk = sl - entry
    for j in range(1, max_hold + 1):
        k = fill_idx + j
        if high[k] >= sl:
            return -1.0, k
        if low[k] <= tp:
            return (entry - tp) / risk, k
    exit_p = close[fill_idx + max_hold]
    return (entry - exit_p) / risk, fill_idx + max_hold


def sim_long_stop_spread(ca, hb, lb, cb, ha, ha_signal, i, max_hold, fill_window=LIMIT_FILL_WINDOW):
    """Spread variant of sim_long_stop. Stop at ask-high of signal bar (ha_signal[i]),
    fill when next bar's ask-high rises through (cross-spread fill: buy at ask-side level).
    Entry = stop_price (paying ask). TP/SL exits on bid side.
    """
    stop_price = ha_signal[i]
    fill_idx = None
    for j in range(1, fill_window + 1):
        k = i + j
        if k >= len(ca):
            return None, None
        if ha[k] >= stop_price:
            fill_idx = k
            break
    if fill_idx is None:
        return None, None
    if fill_idx + max_hold >= len(ca):
        return None, None
    entry = stop_price
    tp = entry * (1 + TP_PCT)
    sl = entry * (1 - STOP_PCT)
    risk = entry - sl
    for j in range(1, max_hold + 1):
        k = fill_idx + j
        if lb[k] <= sl:
            return -1.0, k
        if hb[k] >= tp:
            return (tp - entry) / risk, k
    exit_p = cb[fill_idx + max_hold]
    return (exit_p - entry) / risk, fill_idx + max_hold


def sim_short_stop_spread(cb, ha, la, ca, lb, lb_signal, i, max_hold, fill_window=LIMIT_FILL_WINDOW):
    """Spread variant of sim_short_stop. Stop at bid-low of signal bar (lb_signal[i]),
    fill when next bar's bid-low falls through. Entry = stop_price (selling at bid).
    TP/SL exits on ask side.
    """
    stop_price = lb_signal[i]
    fill_idx = None
    for j in range(1, fill_window + 1):
        k = i + j
        if k >= len(cb):
            return None, None
        if lb[k] <= stop_price:
            fill_idx = k
            break
    if fill_idx is None:
        return None, None
    if fill_idx + max_hold >= len(cb):
        return None, None
    entry = stop_price
    tp = entry * (1 - TP_PCT)
    sl = entry * (1 + STOP_PCT)
    risk = sl - entry
    for j in range(1, max_hold + 1):
        k = fill_idx + j
        if ha[k] >= sl:
            return -1.0, k
        if la[k] <= tp:
            return (entry - tp) / risk, k
    exit_p = ca[fill_idx + max_hold]
    return (entry - exit_p) / risk, fill_idx + max_hold


def sim_long_limit_spread(ca, hb, lb, cb, lb_signal, i, max_hold, fill_window=LIMIT_FILL_WINDOW):
    """Spread variant of sim_long_limit. Limit price = bid-low at signal bar (lb_signal[i]),
    fill if next bar's bid-low <= limit (cross-spread fill assumption: buy at ask of fill bar).
    For simplicity we fill at limit_price on the ask side: entry = limit_price treated as
    the level you actually transact at after spread is paid. TP/SL use bid (high/low) for
    long-side stop/tp checks, exit at bid close on max_hold.
    """
    limit_price = lb_signal[i]
    fill_idx = None
    for j in range(1, fill_window + 1):
        k = i + j
        if k >= len(ca):
            return None, None
        if lb[k] <= limit_price:
            fill_idx = k
            break
    if fill_idx is None:
        return None, None
    if fill_idx + max_hold >= len(ca):
        return None, None
    entry = limit_price
    tp = entry * (1 + TP_PCT)
    stop = entry * (1 - STOP_PCT)
    risk = entry - stop
    for j in range(1, max_hold + 1):
        k = fill_idx + j
        if lb[k] <= stop:
            return -1.0, k
        if hb[k] >= tp:
            return (tp - entry) / risk, k
    exit_p = cb[fill_idx + max_hold]
    return (exit_p - entry) / risk, fill_idx + max_hold


def sim_short_limit_spread(cb, ha, la, ca, ha_signal, i, max_hold, fill_window=LIMIT_FILL_WINDOW):
    """Spread variant of sim_short_limit. Limit price = ask-high at signal bar (ha_signal[i]),
    fill if next bar's ask-high >= limit. Entry at limit_price, TP/SL on ask side, exit at
    ask close on max_hold.
    """
    limit_price = ha_signal[i]
    fill_idx = None
    for j in range(1, fill_window + 1):
        k = i + j
        if k >= len(cb):
            return None, None
        if ha[k] >= limit_price:
            fill_idx = k
            break
    if fill_idx is None:
        return None, None
    if fill_idx + max_hold >= len(cb):
        return None, None
    entry = limit_price
    tp = entry * (1 - TP_PCT)
    stop = entry * (1 + STOP_PCT)
    risk = stop - entry
    for j in range(1, max_hold + 1):
        k = fill_idx + j
        if ha[k] >= stop:
            return -1.0, k
        if la[k] <= tp:
            return (entry - tp) / risk, k
    exit_p = ca[fill_idx + max_hold]
    return (entry - exit_p) / risk, fill_idx + max_hold


def expectancy_split(rs_with_ts, train_frac=TRAIN_FRAC):
    if not rs_with_ts:
        return {f"{half}_{k}": float("nan") for half in ["tr", "te"]
                for k in ["n", "mean_r", "se_r", "ci_low_r", "ci_high_r"]}
    sorted_data = sorted(rs_with_ts, key=lambda x: x[0])
    cut = int(len(sorted_data) * train_frac)
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


def expectancy_overall(rs):
    """Single-set expectancy (for Phase 0 cells)."""
    if not rs:
        return 0, float("nan"), float("nan"), float("nan"), float("nan")
    rs = np.asarray(rs, dtype=float)
    n = len(rs)
    mean_r = float(rs.mean())
    if n < 2:
        return n, mean_r, float("nan"), float("nan"), float("nan")
    se = float(rs.std(ddof=1) / np.sqrt(n))
    return n, mean_r, se, mean_r - 1.96 * se, mean_r + 1.96 * se


def survivor_gate_walkforward(df):
    """Return df rows with both halves CI_low_r > 0, tr_n>=50, te_n>=30."""
    if df.empty:
        return df.copy()
    return df[(df["tr_ci_low_r"] > 0.0) & (df["te_ci_low_r"] > 0.0)
              & (df["tr_n"] >= 50) & (df["te_n"] >= 30)].copy()


def select_production_cells(df_robust, key_cols):
    """Per pair, pick cell with largest te_n (ties broken by te_mean_r)."""
    selected = []
    for pair in sorted(df_robust["pair"].unique()):
        cells = df_robust[df_robust["pair"] == pair].sort_values(
            ["te_n", "te_mean_r"], ascending=[False, False])
        chosen = cells.iloc[0]
        selected.append(chosen)
    return selected


def portfolio_stats(df_split, label):
    n = len(df_split)
    if n == 0:
        return None
    rs = df_split["r"].to_numpy()
    wins = int((rs >= 1.0 - 1e-9).sum())
    losses = int((rs <= -1.0 + 1e-9).sum())
    timeouts = n - wins - losses
    wr = wins / max(wins + losses, 1)
    mean_r = float(rs.mean())
    cum = np.cumsum(rs)
    cum_r = float(cum[-1])
    running_max = np.maximum.accumulate(cum)
    max_dd = float((cum - running_max).min())
    signs = np.sign(rs)
    max_consec = curr = 0
    for s_ in signs:
        if s_ < 0:
            curr += 1
            max_consec = max(max_consec, curr)
        else:
            curr = 0
    events = []
    for _, t in df_split.iterrows():
        events.append((t["entry_ts"], +1))
        events.append((t["exit_ts"], -1))
    events.sort()
    max_concurrent = curr_open = 0
    for _, delta in events:
        curr_open += delta
        max_concurrent = max(max_concurrent, curr_open)
    print(f"  {label}: n={n} W/L/T={wins}/{losses}/{timeouts}  "
          f"WR={wr*100:.1f}%  mean_R={mean_r:+.3f}  cum_R={cum_r:+.1f}  "
          f"max_DD={max_dd:.1f}R  max_consec={max_consec}  max_simul={max_concurrent}")
    return {
        "n": n, "wins": wins, "losses": losses, "timeouts": timeouts,
        "wr": wr, "mean_r": mean_r, "cum_r": cum_r, "max_dd": max_dd,
        "max_consec": max_consec, "max_simul": max_concurrent,
    }
