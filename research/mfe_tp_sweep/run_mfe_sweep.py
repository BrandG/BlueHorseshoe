"""MFE/TP sweep across v2 production cells.

For each of the 33 cells deployed in bh_ftmo_v2_paper (sourced from
bh_briefing.CELLS), replays every historical fire under a parameterized
TP/SL simulator. Sweeps TP_R in {0.2..1.5} at fixed 1.0R SL and reports:

  - per-trade: entry_ts, mfe_R (MFE as multiple of risk), mae_R, max_hold_close_R
  - per-cell: hit-rate, expectancy at each TP, expectancy CI lower bound
  - per-strategy aggregate: total n, mean R per TP, CI lower bound, peak TP
  - overall portfolio

Why mid-price (not spread): we want the TP-placement signal. Spread adds a
roughly fixed pip cost that compresses every TP, but doesn't move the peak.
A spread-aware second pass can refine the headline number once a TP is chosen.

Within-bar order: when both SL and TP would have hit in the same bar, we
assume SL hit first (conservative; matches `_lib.py` semantics).

Output:
  - per_trade.csv: every historical fire with MFE/MAE/final-at-each-TP
  - per_cell_tp.csv: hit rate + expectancy table per cell per TP
  - per_strategy_tp.csv: aggregated per strategy
  - portfolio_tp.csv: overall portfolio per TP
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/src")

from bh_briefing import CELLS, Cell
from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import (
    ohlc_mid, bollinger_bands, macd, stochastic, sma, ema, rsi, cci, atr, ichimoku,
    is_hammer, is_shooting_star, is_bullish_engulfing, is_bearish_engulfing,
)


# Match v2 conventions
GRANULARITY = "H4"
MAX_HOLD = 14 * 6           # 84 H4 bars = 14 trading days
STOP_PCT = 0.01             # fixed 1% SL (1R)
LIMIT_FILL_WINDOW = 1
TP_GRID = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.25, 1.5]
OUT_DIR = Path("/root/BlueHorseshoe/research/mfe_tp_sweep")
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# MFE-tracking sim. SL fixed at STOP_PCT; no TP — walks until SL or max_hold.
# Returns dict with mfe_R, mae_R, sl_hit (bool), bars_to_exit, max_hold_close_R.
# ---------------------------------------------------------------------------

def mfe_sim_long(close, high, low, entry_idx, max_hold):
    """Returns dict or None if not enough bars."""
    n = len(close)
    if entry_idx + max_hold >= n:
        return None
    entry = close[entry_idx]
    stop = entry * (1 - STOP_PCT)
    risk = entry - stop  # positive
    mfe_R = 0.0
    mae_R = 0.0
    for j in range(1, max_hold + 1):
        k = entry_idx + j
        # Track MFE/MAE on this bar
        bar_mfe = (high[k] - entry) / risk
        bar_mae = (low[k] - entry) / risk
        if bar_mfe > mfe_R:
            mfe_R = bar_mfe
        if bar_mae < mae_R:
            mae_R = bar_mae
        if low[k] <= stop:
            return {
                "mfe_R": mfe_R, "mae_R": mae_R,
                "sl_hit": True, "bars_to_exit": j,
                "max_hold_close_R": -1.0,  # would have closed at SL
            }
    exit_p = close[entry_idx + max_hold]
    return {
        "mfe_R": mfe_R, "mae_R": mae_R,
        "sl_hit": False, "bars_to_exit": max_hold,
        "max_hold_close_R": (exit_p - entry) / risk,
    }


def mfe_sim_short(close, high, low, entry_idx, max_hold):
    n = len(close)
    if entry_idx + max_hold >= n:
        return None
    entry = close[entry_idx]
    stop = entry * (1 + STOP_PCT)
    risk = stop - entry  # positive
    mfe_R = 0.0
    mae_R = 0.0
    for j in range(1, max_hold + 1):
        k = entry_idx + j
        bar_mfe = (entry - low[k]) / risk
        bar_mae = (entry - high[k]) / risk
        if bar_mfe > mfe_R:
            mfe_R = bar_mfe
        if bar_mae < mae_R:
            mae_R = bar_mae
        if high[k] >= stop:
            return {
                "mfe_R": mfe_R, "mae_R": mae_R,
                "sl_hit": True, "bars_to_exit": j,
                "max_hold_close_R": -1.0,
            }
    exit_p = close[entry_idx + max_hold]
    return {
        "mfe_R": mfe_R, "mae_R": mae_R,
        "sl_hit": False, "bars_to_exit": max_hold,
        "max_hold_close_R": (entry - exit_p) / risk,
    }


def mfe_sim_long_limit(close, high, low, signal_idx, max_hold,
                       fill_window=LIMIT_FILL_WINDOW):
    """Limit fill at signal-bar low. Returns None if not filled."""
    limit_price = low[signal_idx]
    fill_idx = None
    for j in range(1, fill_window + 1):
        k = signal_idx + j
        if k >= len(close):
            return None
        if low[k] <= limit_price:
            fill_idx = k
            break
    if fill_idx is None:
        return None
    if fill_idx + max_hold >= len(close):
        return None
    entry = limit_price
    stop = entry * (1 - STOP_PCT)
    risk = entry - stop
    mfe_R = 0.0
    mae_R = 0.0
    for j in range(1, max_hold + 1):
        k = fill_idx + j
        bar_mfe = (high[k] - entry) / risk
        bar_mae = (low[k] - entry) / risk
        if bar_mfe > mfe_R:
            mfe_R = bar_mfe
        if bar_mae < mae_R:
            mae_R = bar_mae
        if low[k] <= stop:
            return {
                "mfe_R": mfe_R, "mae_R": mae_R,
                "sl_hit": True, "bars_to_exit": j,
                "max_hold_close_R": -1.0, "fill_idx": fill_idx,
            }
    exit_p = close[fill_idx + max_hold]
    return {
        "mfe_R": mfe_R, "mae_R": mae_R,
        "sl_hit": False, "bars_to_exit": max_hold,
        "max_hold_close_R": (exit_p - entry) / risk, "fill_idx": fill_idx,
    }


def mfe_sim_short_limit(close, high, low, signal_idx, max_hold,
                        fill_window=LIMIT_FILL_WINDOW):
    limit_price = high[signal_idx]
    fill_idx = None
    for j in range(1, fill_window + 1):
        k = signal_idx + j
        if k >= len(close):
            return None
        if high[k] >= limit_price:
            fill_idx = k
            break
    if fill_idx is None:
        return None
    if fill_idx + max_hold >= len(close):
        return None
    entry = limit_price
    stop = entry * (1 + STOP_PCT)
    risk = stop - entry
    mfe_R = 0.0
    mae_R = 0.0
    for j in range(1, max_hold + 1):
        k = fill_idx + j
        bar_mfe = (entry - low[k]) / risk
        bar_mae = (entry - high[k]) / risk
        if bar_mfe > mfe_R:
            mfe_R = bar_mfe
        if bar_mae < mae_R:
            mae_R = bar_mae
        if high[k] >= stop:
            return {
                "mfe_R": mfe_R, "mae_R": mae_R,
                "sl_hit": True, "bars_to_exit": j,
                "max_hold_close_R": -1.0, "fill_idx": fill_idx,
            }
    exit_p = close[fill_idx + max_hold]
    return {
        "mfe_R": mfe_R, "mae_R": mae_R,
        "sl_hit": False, "bars_to_exit": max_hold,
        "max_hold_close_R": (entry - exit_p) / risk, "fill_idx": fill_idx,
    }


# ---------------------------------------------------------------------------
# Apply a TP_R cap to an MFE result. Returns final_R under that TP.
#
# Rule:
#   - If sl_hit AND mfe_R >= tp_R: TP-first is possible but undetermined
#     within bar. Conservative: SL first ⇒ final_R = -1.
#     BUT — if MFE happened BEFORE the SL bar (i.e. mfe peaked on an earlier
#     bar than the SL hit), then TP would have been taken before SL. We need
#     bar-level data for that. Falling back to conservative: only credit TP
#     if mfe_R >= tp_R AND NOT sl_hit (TP hit cleanly in a non-SL bar).
#   - The conservative rule undercounts TP hits in tight-TP regimes. For a
#     non-conservative read, use the optimistic rule (credit TP whenever
#     mfe_R >= tp_R).
#
# We compute BOTH conservative and optimistic, plus a precise variant that
# tracks bar-of-MFE-peak vs bar-of-SL.
# ---------------------------------------------------------------------------

def apply_tp_conservative(mfe_R, sl_hit, max_hold_close_R, tp_R):
    """If SL hit at all → -1, unless TP cleanly taken before SL. We don't
    know bar order without re-sim; assume SL wins ties. So:
      - sl_hit=False and mfe_R >= tp_R → +tp_R
      - sl_hit=False and mfe_R <  tp_R → max_hold_close_R
      - sl_hit=True                    → -1
    """
    if sl_hit:
        return -1.0
    if mfe_R >= tp_R:
        return tp_R
    return max_hold_close_R


def apply_tp_optimistic(mfe_R, sl_hit, max_hold_close_R, tp_R):
    """Credit TP whenever MFE crossed it, regardless of SL.
    Overstates win rate when SL hit on same bar as MFE peak, but
    is realistic when TP < MFE peak was reached on bars BEFORE the SL bar.
    """
    if mfe_R >= tp_R:
        return tp_R
    if sl_hit:
        return -1.0
    return max_hold_close_R


# ---------------------------------------------------------------------------
# Precise per-trade re-sim: walks bar by bar with TP+SL, picks whichever
# triggers first; if both within same bar, SL wins (matches _lib semantics).
# This is the ground truth and is what we report.
# ---------------------------------------------------------------------------

def resim_long(close, high, low, entry_price_arr, entry_idx, max_hold, tp_R):
    """entry_price_arr is either close[entry_idx] (mid) or limit fill price.
    Returns (final_R, bars_to_exit).
    """
    entry = entry_price_arr
    stop = entry * (1 - STOP_PCT)
    risk = entry - stop
    tp = entry + tp_R * risk
    for j in range(1, max_hold + 1):
        k = entry_idx + j
        if low[k] <= stop:
            return -1.0, j
        if high[k] >= tp:
            return tp_R, j
    exit_p = close[entry_idx + max_hold]
    return (exit_p - entry) / risk, max_hold


def resim_short(close, high, low, entry_price_arr, entry_idx, max_hold, tp_R):
    entry = entry_price_arr
    stop = entry * (1 + STOP_PCT)
    risk = stop - entry
    tp = entry - tp_R * risk
    for j in range(1, max_hold + 1):
        k = entry_idx + j
        if high[k] >= stop:
            return -1.0, j
        if low[k] <= tp:
            return tp_R, j
    exit_p = close[entry_idx + max_hold]
    return (entry - exit_p) / risk, max_hold


# ---------------------------------------------------------------------------
# Per-strategy vectorized fire-finders (adapted from research/_v2_rerun/run_*_v2.py
# and research/bb_execution_v1/portfolio_bb_v2.py). Each returns an array
# of bar indices where the cell fires.
# ---------------------------------------------------------------------------

def _fresh(cond):
    fresh = cond & ~np.roll(cond, 1)
    fresh[0] = False
    return np.where(fresh)[0]


def _osc_fresh_long(arr, threshold, recovery, signed=False):
    n = len(arr)
    if n < recovery + 2:
        return np.array([], dtype=int)
    base = np.full(n, np.nan)
    base[recovery:] = arr[: n - recovery]
    diffs_pos = np.zeros(n, dtype=bool)
    diffs_pos[1:] = arr[1:] > arr[:-1]
    rising = np.zeros(n, dtype=bool)
    for i in range(recovery, n):
        rising[i] = bool(np.all(diffs_pos[i - recovery + 1: i + 1]))
    long_base = -threshold if signed else threshold
    valid = ~np.isnan(base) & ~np.isnan(arr)
    cond = valid & rising & (base < long_base)
    return _fresh(cond)


def _osc_fresh_short(arr, threshold, recovery, signed=False):
    n = len(arr)
    if n < recovery + 2:
        return np.array([], dtype=int)
    base = np.full(n, np.nan)
    base[recovery:] = arr[: n - recovery]
    diffs_neg = np.zeros(n, dtype=bool)
    diffs_neg[1:] = arr[1:] < arr[:-1]
    falling = np.zeros(n, dtype=bool)
    for i in range(recovery, n):
        falling[i] = bool(np.all(diffs_neg[i - recovery + 1: i + 1]))
    short_base = threshold if signed else (100.0 - threshold)
    valid = ~np.isnan(base) & ~np.isnan(arr)
    cond = valid & falling & (base > short_base)
    return _fresh(cond)


def triggers_stoch(mid, params, direction):
    s = stochastic(mid, k_period=params["k_period"], d_period=params["d_period"])
    k_arr = s["k"].to_numpy(dtype=float)
    if direction == "long":
        return _osc_fresh_long(k_arr, float(params["threshold"]),
                               int(params["recovery"]))
    return _osc_fresh_short(k_arr, float(params["threshold"]),
                            int(params["recovery"]))


def triggers_rsi(mid, params, direction):
    r = rsi(mid, period=params["period"]).to_numpy(dtype=float)
    if direction == "long":
        return _osc_fresh_long(r, float(params["threshold"]),
                               int(params["recovery"]))
    return _osc_fresh_short(r, float(params["threshold"]),
                            int(params["recovery"]))


def triggers_cci(mid, params, direction):
    c = cci(mid, period=params["period"]).to_numpy(dtype=float)
    if direction == "long":
        return _osc_fresh_long(c, float(params["threshold"]),
                               int(params["recovery"]), signed=True)
    return _osc_fresh_short(c, float(params["threshold"]),
                            int(params["recovery"]), signed=True)


def triggers_bb(mid, params, direction):
    bb = bollinger_bands(mid, period=params["period"], n_std=params["n_std"])
    close = mid["close"].to_numpy(dtype=float)
    lower = bb["lower"].to_numpy(dtype=float)
    upper = bb["upper"].to_numpy(dtype=float)
    bw = upper - lower
    depth = float(params["depth"])
    if direction == "long":
        thr = lower - depth * bw
        cond = close < thr
    else:
        thr = upper + depth * bw
        cond = close > thr
    cond = np.where(np.isnan(thr), False, cond)
    return _fresh(cond.astype(bool))


def triggers_macd(mid, params, direction):
    m = macd(mid, fast=params["fast"], slow=params["slow"], signal=params["signal"])
    macd_arr = m["macd"].to_numpy(dtype=float)
    sig_arr = m["signal"].to_numpy(dtype=float)
    n = len(macd_arr)
    trigger = params["trigger"]
    if trigger == "signal_cross":
        if direction == "long":
            cond = np.zeros(n, dtype=bool)
            cond[1:] = (macd_arr[1:] > sig_arr[1:]) & (macd_arr[:-1] <= sig_arr[:-1])
            cond &= ~np.isnan(macd_arr) & ~np.isnan(sig_arr)
        else:
            cond = np.zeros(n, dtype=bool)
            cond[1:] = (macd_arr[1:] < sig_arr[1:]) & (macd_arr[:-1] >= sig_arr[:-1])
            cond &= ~np.isnan(macd_arr) & ~np.isnan(sig_arr)
        return np.where(cond)[0]
    # zero_cross
    if direction == "long":
        cond = np.zeros(n, dtype=bool)
        cond[1:] = (macd_arr[1:] > 0) & (macd_arr[:-1] <= 0)
        cond &= ~np.isnan(macd_arr)
    else:
        cond = np.zeros(n, dtype=bool)
        cond[1:] = (macd_arr[1:] < 0) & (macd_arr[:-1] >= 0)
        cond &= ~np.isnan(macd_arr)
    return np.where(cond)[0]


def triggers_sma(mid, params, direction):
    close = mid["close"].to_numpy(dtype=float)
    sma_arr = sma(mid, period=params["period"]).to_numpy(dtype=float)
    atr_arr = atr(mid, period=params["atr_period"]).to_numpy(dtype=float)
    k = float(params["k"])
    valid = ~np.isnan(close) & ~np.isnan(sma_arr) & ~np.isnan(atr_arr)
    if direction == "long":
        cond = valid & (close < (sma_arr - k * atr_arr))
    else:
        cond = valid & (close > (sma_arr + k * atr_arr))
    return _fresh(cond)


def triggers_ema(mid, params, direction):
    close = mid["close"].to_numpy(dtype=float)
    ema_arr = ema(mid, period=params["period"]).to_numpy(dtype=float)
    atr_arr = atr(mid, period=params["atr_period"]).to_numpy(dtype=float)
    k = float(params["k"])
    valid = ~np.isnan(close) & ~np.isnan(ema_arr) & ~np.isnan(atr_arr)
    if direction == "long":
        cond = valid & (close < (ema_arr - k * atr_arr))
    else:
        cond = valid & (close > (ema_arr + k * atr_arr))
    return _fresh(cond)


def triggers_atr(mid, params, direction):
    """ATR range_expansion only (production cells all use this trigger)."""
    if params["trigger"] != "range_expansion":
        raise NotImplementedError(f"atr trigger {params['trigger']} not implemented")
    open_arr = mid["open"].to_numpy(dtype=float)
    close = mid["close"].to_numpy(dtype=float)
    high = mid["high"].to_numpy(dtype=float)
    low = mid["low"].to_numpy(dtype=float)
    lookback = int(params["range_lookback"])
    k = float(params["k"])
    rng = high - low
    mean_rng = pd.Series(rng).rolling(lookback, min_periods=lookback).mean().to_numpy()
    prev_mean = np.full(len(close), np.nan)
    prev_mean[1:] = mean_rng[:-1]
    if direction == "long":
        is_bull = close > open_arr
        cond = (rng > k * prev_mean) & is_bull
    else:
        is_bear = close < open_arr
        cond = (rng > k * prev_mean) & is_bear
    cond = np.where(np.isnan(prev_mean), False, cond)
    return _fresh(cond.astype(bool))


def triggers_ichimoku(mid, params, direction):
    """Only tk_cross supported (production cell)."""
    if params["trigger"] != "tk_cross":
        raise NotImplementedError(f"ichimoku trigger {params['trigger']} not implemented")
    ich = ichimoku(mid, tenkan_period=params["tenkan"], kijun_period=params["kijun"],
                   senkou_b_period=params["senkou_b"],
                   displacement=params["displacement"])
    tenkan = ich["tenkan"].to_numpy(dtype=float)
    kijun = ich["kijun"].to_numpy(dtype=float)
    if direction == "long":
        above = tenkan > kijun
        cond = above & ~np.roll(above, 1)
    else:
        below = tenkan < kijun
        cond = below & ~np.roll(below, 1)
    cond[0] = False
    cond &= ~np.isnan(tenkan) & ~np.isnan(kijun)
    return np.where(cond)[0]


def triggers_candle(mid, params, direction):
    pattern = params["pattern"]
    strict = params.get("strict", False)
    if pattern == "bull_engulf":
        m = is_bullish_engulfing(mid, min_body_frac=0.5) if strict else is_bullish_engulfing(mid)
    elif pattern == "bear_engulf":
        m = is_bearish_engulfing(mid, min_body_frac=0.5) if strict else is_bearish_engulfing(mid)
    elif pattern == "hammer":
        m = is_hammer(mid, body_frac_max=0.25, lower_shadow_min=0.6, upper_shadow_max=0.10) if strict else is_hammer(mid)
    elif pattern == "shooting_star":
        m = is_shooting_star(mid, body_frac_max=0.25, upper_shadow_min=0.6, lower_shadow_max=0.10) if strict else is_shooting_star(mid)
    else:
        raise ValueError(f"unknown candle pattern: {pattern}")
    return np.where(m.to_numpy(dtype=bool))[0]


TRIGGER_FUNCS = {
    "stoch": triggers_stoch,
    "rsi": triggers_rsi,
    "cci": triggers_cci,
    "bb": triggers_bb,
    "macd": triggers_macd,
    "sma": triggers_sma,
    "ema": triggers_ema,
    "atr": triggers_atr,
    "ichimoku": triggers_ichimoku,
    "candle": triggers_candle,
}


# ---------------------------------------------------------------------------
# Per-cell processing
# ---------------------------------------------------------------------------

def process_cell(cell: Cell, raw: pd.DataFrame) -> list[dict]:
    """Returns list of per-trade dicts."""
    mid = ohlc_mid(raw)
    close = mid["close"].to_numpy(dtype=float)
    high = mid["high"].to_numpy(dtype=float)
    low = mid["low"].to_numpy(dtype=float)
    ts = raw["timestamp"].to_numpy()

    trig_func = TRIGGER_FUNCS[cell.strategy]
    indices = trig_func(mid, cell.params, cell.direction)

    trades = []
    is_long = cell.direction == "long"
    is_limit = cell.entry_mode == "limit"

    for sig_idx in indices:
        sig_idx = int(sig_idx)
        if is_limit:
            sim = mfe_sim_long_limit if is_long else mfe_sim_short_limit
            res = sim(close, high, low, sig_idx, MAX_HOLD, LIMIT_FILL_WINDOW)
            if res is None:
                continue
            entry_idx = res["fill_idx"]
            entry_price = low[sig_idx] if is_long else high[sig_idx]
        else:
            sim = mfe_sim_long if is_long else mfe_sim_short
            res = sim(close, high, low, sig_idx, MAX_HOLD)
            if res is None:
                continue
            entry_idx = sig_idx
            entry_price = close[sig_idx]

        row = {
            "strategy": cell.strategy,
            "pair": cell.pair,
            "direction": cell.direction,
            "entry_mode": cell.entry_mode,
            "signal_ts": pd.Timestamp(ts[sig_idx]),
            "entry_ts": pd.Timestamp(ts[entry_idx]),
            "entry_price": entry_price,
            "mfe_R": res["mfe_R"],
            "mae_R": res["mae_R"],
            "sl_hit": res["sl_hit"],
            "bars_to_exit": res["bars_to_exit"],
            "max_hold_close_R": res["max_hold_close_R"],
        }
        # Precise per-TP re-sim using actual bar walk
        resim = resim_long if is_long else resim_short
        for tp_R in TP_GRID:
            r_val, bars_val = resim(close, high, low, entry_price, entry_idx,
                                    MAX_HOLD, tp_R)
            row[f"r_tp{tp_R}"] = r_val
            row[f"bars_tp{tp_R}"] = bars_val
        trades.append(row)
    return trades


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def expectancy_stats(rs: np.ndarray) -> dict:
    if len(rs) == 0:
        return {"n": 0, "mean_R": np.nan, "se_R": np.nan,
                "ci_lo_R": np.nan, "ci_hi_R": np.nan, "win_rate": np.nan}
    mean = float(np.mean(rs))
    se = float(np.std(rs, ddof=1) / np.sqrt(len(rs))) if len(rs) > 1 else float("nan")
    ci_lo = mean - 1.96 * se if se == se else np.nan
    ci_hi = mean + 1.96 * se if se == se else np.nan
    wr = float(np.mean(rs > 0))
    return {"n": len(rs), "mean_R": mean, "se_R": se,
            "ci_lo_R": ci_lo, "ci_hi_R": ci_hi, "win_rate": wr}


def build_aggregations(trades_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows_cell = []
    rows_strat = []
    rows_port = []
    tp_cols = [f"r_tp{t}" for t in TP_GRID]

    for tp_R, col in zip(TP_GRID, tp_cols):
        # Per cell
        for (strat, pair, direction), grp in trades_df.groupby(["strategy", "pair", "direction"]):
            stats = expectancy_stats(grp[col].to_numpy())
            rows_cell.append({"strategy": strat, "pair": pair, "direction": direction,
                              "tp_R": tp_R, **stats})
        # Per strategy
        for strat, grp in trades_df.groupby("strategy"):
            stats = expectancy_stats(grp[col].to_numpy())
            rows_strat.append({"strategy": strat, "tp_R": tp_R, **stats})
        # Portfolio
        stats = expectancy_stats(trades_df[col].to_numpy())
        rows_port.append({"tp_R": tp_R, **stats})

    return (pd.DataFrame(rows_cell), pd.DataFrame(rows_strat),
            pd.DataFrame(rows_port))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    store = FxStore()
    all_trades = []
    t0 = time.time()
    for i, cell in enumerate(CELLS):
        raw = store.load(cell.pair, granularity=GRANULARITY, include_incomplete=False)
        if raw is None or raw.empty:
            print(f"  [skip] {cell.strategy:>9}/{cell.pair} no data")
            continue
        trades = process_cell(cell, raw)
        all_trades.extend(trades)
        print(f"  [{i+1:>2}/{len(CELLS)}] {cell.strategy:>9}/{cell.pair}/{cell.direction:>5}"
              f"/{cell.entry_mode:<5} → {len(trades):>5} trades")

    df = pd.DataFrame(all_trades)
    print(f"\nTotal trades: {len(df):,}   elapsed: {time.time()-t0:.1f}s")

    df.to_csv(OUT_DIR / "per_trade.csv", index=False)
    print(f"Wrote {OUT_DIR/'per_trade.csv'}")

    cell_df, strat_df, port_df = build_aggregations(df)
    cell_df.to_csv(OUT_DIR / "per_cell_tp.csv", index=False)
    strat_df.to_csv(OUT_DIR / "per_strategy_tp.csv", index=False)
    port_df.to_csv(OUT_DIR / "portfolio_tp.csv", index=False)
    print(f"Wrote per_cell_tp.csv, per_strategy_tp.csv, portfolio_tp.csv")

    # Console summary: portfolio TP sweep + per-strategy peak TP
    print("\n=== Portfolio TP sweep (across all 33 cells) ===")
    print(port_df.to_string(index=False,
                            float_format=lambda x: f"{x:.4f}" if isinstance(x, float) else x))

    print("\n=== Per-strategy peak TP (by CI lower bound) ===")
    for strat, grp in strat_df.groupby("strategy"):
        valid = grp.dropna(subset=["ci_lo_R"])
        if valid.empty:
            continue
        peak = valid.loc[valid["ci_lo_R"].idxmax()]
        print(f"  {strat:>10}  n={int(peak['n']):>5}  "
              f"peak TP={peak['tp_R']:.2f}R  mean_R={peak['mean_R']:.3f}  "
              f"CI_lo={peak['ci_lo_R']:.3f}  WR={peak['win_rate']:.3f}")


if __name__ == "__main__":
    main()
