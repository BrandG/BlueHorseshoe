"""Shared Bud cell replay: load H4 bars, detect fires, resolve entries.

Extracted from research/cell_revalidation_v1 (fidelity-validated against live evaluate_cell).
Fire detection is vectorized 1×/cell for the mid strategies (bb/stoch/rsi/cci/sma/ema) and
falls back to the live per-bar evaluate_cell for the rest (atr/macd/ichimoku/candle). The
caller brackets each fire — this module only finds fires and resolves the (entry_idx, price).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from bud.briefing import LOOKBACK_BARS, evaluate_cell  # noqa: E402
from bh_ftmo.data.fx_store import FxStore  # noqa: E402
from bh_ftmo.indicators.volatility import bollinger_bands, atr  # noqa: E402
from bh_ftmo.indicators.momentum import rsi, cci, stochastic  # noqa: E402
from bh_ftmo.indicators.trend import sma, ema  # noqa: E402

GRAN = "H4"


def load_pairs(pairs, *, smoke=False, smoke_bars=2500):
    """pair -> dict(hi, lo, cl, ts, spread, mid_df). Mid OHLC + spread from bid/ask."""
    store = FxStore(read_only=True)
    out = {}
    try:
        for pair in pairs:
            raw = store.load(pair, granularity=GRAN)
            raw = raw[raw["is_complete"]].reset_index(drop=True)
            if smoke:
                raw = raw.tail(smoke_bars).reset_index(drop=True)
            if len(raw) <= LOOKBACK_BARS + 2:
                continue
            mid = pd.DataFrame({
                "open": (raw["open_bid"] + raw["open_ask"]) / 2.0,
                "high": (raw["high_bid"] + raw["high_ask"]) / 2.0,
                "low": (raw["low_bid"] + raw["low_ask"]) / 2.0,
                "close": (raw["close_bid"] + raw["close_ask"]) / 2.0,
            })
            out[pair] = {
                "mid_df": mid,
                "hi": mid["high"].to_numpy(float),
                "lo": mid["low"].to_numpy(float),
                "cl": mid["close"].to_numpy(float),
                "ts": raw["timestamp"].values.astype("datetime64[ns]"),
                "spread": (raw["close_ask"] - raw["close_bid"]).abs().to_numpy(float),
            }
    finally:
        store.close()
    return out


# --- vectorized fire detection (mirrors briefing._*_fired; fidelity-checked) ---
def _fresh(cond):
    out = cond.copy()
    out[1:] = cond[1:] & ~cond[:-1]
    out[0] = False
    return out


def _rolling_all(b, w):
    acc = b.copy()
    for j in range(1, w):
        acc[j:] = acc[j:] & b[:-j]
        acc[:j] = False
    return acc


def _osc_mask(arr, threshold, recovery, direction, signed):
    n = len(arr)
    long_base = -threshold if signed else threshold
    short_base = threshold if signed else 100.0 - threshold
    rising = np.zeros(n, bool); rising[1:] = arr[1:] > arr[:-1]
    falling = np.zeros(n, bool); falling[1:] = arr[1:] < arr[:-1]
    base = np.full(n, np.nan)
    if recovery < n:
        base[recovery:] = arr[:-recovery]
    ok = ~np.isnan(base) & ~np.isnan(arr)
    if direction == "long":
        cond = _rolling_all(rising, recovery) & (base < long_base) & ok
    else:
        cond = _rolling_all(falling, recovery) & (base > short_base) & ok
    return _fresh(cond)


def fire_mask(cell, mid):
    """Boolean fire array, or None if the strategy isn't vectorized."""
    p, d = cell.params, cell.direction
    close = mid["close"].to_numpy(float)
    if cell.strategy == "bb":
        bb = bollinger_bands(mid, period=p["period"], n_std=p["n_std"])
        lower = bb["lower"].to_numpy(float); upper = bb["upper"].to_numpy(float)
        bw = upper - lower
        if d == "long":
            t = lower - float(p["depth"]) * bw; cond = (close < t) & ~np.isnan(t)
        else:
            t = upper + float(p["depth"]) * bw; cond = (close > t) & ~np.isnan(t)
        return _fresh(cond)
    if cell.strategy == "stoch":
        arr = stochastic(mid, k_period=p["k_period"], d_period=p["d_period"])["k"].to_numpy(float)
        return _osc_mask(arr, float(p["threshold"]), int(p["recovery"]), d, signed=False)
    if cell.strategy == "rsi":
        arr = rsi(mid, period=p["period"]).to_numpy(float)
        return _osc_mask(arr, float(p["threshold"]), int(p["recovery"]), d, signed=False)
    if cell.strategy == "cci":
        arr = cci(mid, period=p["period"]).to_numpy(float)
        return _osc_mask(arr, float(p["threshold"]), int(p["recovery"]), d, signed=True)
    if cell.strategy in ("sma", "ema"):
        ma = (sma if cell.strategy == "sma" else ema)(mid, period=p["period"]).to_numpy(float)
        a = atr(mid, period=p["atr_period"]).to_numpy(float)
        k = float(p["k"]); ok = ~np.isnan(close) & ~np.isnan(ma) & ~np.isnan(a)
        cond = ((close < ma - k * a) if d == "long" else (close > ma + k * a)) & ok
        return _fresh(cond)
    return None


def fire_events(cell, P):
    """List of fires as dicts: entry_idx, fwd_start, entry, side, entry_ts, symbol, spread.

    Resolves mid vs limit fills exactly as the live trader does. Geometry-agnostic — the
    caller applies stop/target. entry/stop levels are mid-based (matches live).
    """
    mid = P["mid_df"]; hi = P["hi"]; lo = P["lo"]; ts = P["ts"]; spread = P["spread"]
    n = len(mid)
    side = 1 if cell.direction == "long" else -1
    mask = fire_mask(cell, mid)
    if mask is not None:
        idxs = [i for i in np.flatnonzero(mask) if LOOKBACK_BARS <= i < n - 1]
    else:
        idxs = [i for i in range(LOOKBACK_BARS, n - 1)
                if evaluate_cell(cell, mid.iloc[i - LOOKBACK_BARS + 1: i + 1])]
    events = []
    for i in idxs:
        if cell.entry_mode == "mid":
            entry = float(mid["close"].iloc[i]); entry_idx, fwd_start = i, i + 1
        else:  # limit: order rests on the trigger bar's low/high for the next bar only
            entry = float(mid["low"].iloc[i] if side == 1 else mid["high"].iloc[i])
            j = i + 1
            if j >= n:
                continue
            touched = (lo[j] <= entry) if side == 1 else (hi[j] >= entry)
            if not touched:
                continue
            entry_idx, fwd_start = j, j
        events.append({
            "entry_idx": entry_idx, "fwd_start": fwd_start, "entry": entry, "side": side,
            "entry_ts": pd.Timestamp(ts[entry_idx]), "symbol": cell.pair,
            "spread": float(spread[entry_idx]),
        })
    return events
