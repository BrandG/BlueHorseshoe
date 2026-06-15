"""BH Briefing — morning v2-cell signal report.

Evaluates the v2 production cells (stoch, bb, macd for now) on the most
recently closed H4 bar and prints which pair/direction combinations are
firing. Designed for human-in-the-loop trading: you read the report, you
pick which signals to take, you place the orders.

This is the human counterpart to `bh_ftmo_paper.py` (the rising_3bar
autonomous trader). Where bh_ftmo_paper places orders without confirmation,
bh_briefing only reports.

Cells are encoded inline. Adding a new strategy:
  1. Append a Cell entry to CELLS
  2. Add a branch in `evaluate_cell` if the strategy isn't already supported
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
import smtplib
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators import (
    atr,
    bollinger_bands,
    cci,
    ema,
    ichimoku,
    is_bullish_engulfing,
    macd,
    ohlc_mid,
    rsi,
    sma,
    stochastic,
)
from bh_ftmo.indicators.pivots import daily_ohlc
from bh_ftmo.indicators.sessions import Session, session_label
from bud.entry_location import atr_pct_w252, is_high_ny_skip

REPO_ROOT = Path(__file__).resolve().parents[2]  # src/bud/<this> -> repo root
CONFIG_PATH = REPO_ROOT / "src" / "bh_ftmo_config.json"
BRIEFING_DIR = REPO_ROOT / "src" / "logs" / "briefings"

# All v2 cells share these RR settings. TP reverted to 1.0% on 2026-06-12:
# the expectancy gates validated cells at 1%/1%, and the Newey-West re-gate
# on the archived spread ledgers showed the 2026-05-13 tightening to 0.5%
# halved per-trade R without improving R/slot-day (the mid-price MFE sweep
# had understated spread cost, which weighs 2x against a 0.5% target).
# See memory note project_v2_nw_regate.md.
TP_PCT = 0.01
STOP_PCT = 0.01
LOOKBACK_BARS = 300  # enough warmup for the slowest indicator (BB period=50)
H4_BAR_HOURS = 4  # FxStore stores the bar's OPEN time; close = open + this

LOG = logging.getLogger("bh_ftmo.briefing")

# Indicators whose COUNTER-TREND trades have negative test mean_R per the D1
# alignment diagnostic (docs/planning/MULTITF_FILTER_v1.md): ATR (both mid+limit)
# and candlestick (mid). When one of these fires against the daily trend the
# briefing flags it as a historical money-loser. Annotation only — nothing is
# suppressed; Brand remains the gate.
NEG_COUNTER_TREND_STRATEGIES = frozenset({"atr", "candle"})


def d1_alignment(mid: pd.DataFrame, timestamps: pd.Series, direction: str) -> str:
    """Classify a fire against the daily-bar trend at the trigger bar's NY date.

    D1 direction = sign(D1 close − D1 open) for the day containing the most recent
    (trigger) bar — the same definition as the research diagnostic. Returns
    "with-trend" if the trade direction matches the daily bar's direction,
    "counter-trend" if opposite, "flat" if the daily bar is doji/unavailable.
    With-trend trades carried ~3.3× the per-trade R in the diagnostic.
    """
    try:
        daily = daily_ohlc(mid, timestamps=timestamps)
    except Exception:  # defensive: never let annotation break a briefing
        return "flat"
    if daily.empty:
        return "flat"
    d1_open = float(daily["open"].iloc[-1])
    d1_close = float(daily["close"].iloc[-1])
    if d1_close > d1_open:
        d1_dir = "long"
    elif d1_close < d1_open:
        d1_dir = "short"
    else:
        return "flat"
    return "with-trend" if d1_dir == direction else "counter-trend"


def session_of(bar_ts: pd.Timestamp) -> str:
    """Forex session (asia/london/overlap/ny/closed) at the trigger bar's open time."""
    label = session_label(pd.Series([pd.Timestamp(bar_ts)])).iloc[0]
    return label.value if isinstance(label, Session) else str(label)


@dataclass(frozen=True)
class Cell:
    strategy: str           # "stoch", "bb", "macd"
    pair: str               # OANDA-style "USD_JPY"
    direction: str          # "long" or "short"
    entry_mode: str         # "mid" or "limit"
    params: dict[str, Any]


# v2 production cells (sourced from STOCH_STRATEGY_v1.md, BB_STRATEGY_v1.md,
# MACD_STRATEGY_v1.md after the v2 rerun + spread test). Adding more strategies
# (sma, ema, rsi, cci, atr, ichimoku, candlestick) is a future step.
CELLS: list[Cell] = [
    # Stoch v2 — 4 pairs, mid entry, 1.0%/1.0% RR
    Cell("stoch", "CAD_CHF", "short", "mid",
         {"k_period": 9,  "d_period": 3, "threshold": 20, "recovery": 1}),
    Cell("stoch", "CHF_JPY", "long", "mid",
         {"k_period": 5,  "d_period": 3, "threshold": 20, "recovery": 1}),
    Cell("stoch", "EUR_GBP", "long", "mid",
         {"k_period": 21, "d_period": 3, "threshold": 30, "recovery": 1}),
    Cell("stoch", "USD_JPY", "long", "mid",
         {"k_period": 9,  "d_period": 3, "threshold": 30, "recovery": 1}),
    # BB v2 — 5 pairs, mid entry, 1.0%/1.0% RR
    Cell("bb", "AUD_CAD", "short", "mid",
         {"period": 50, "n_std": 1.5, "depth": 0.25}),
    Cell("bb", "CAD_CHF", "short", "mid",
         {"period": 10, "n_std": 1.5, "depth": 0.00}),
    Cell("bb", "CHF_JPY", "long", "mid",
         {"period": 50, "n_std": 2.0, "depth": 0.00}),
    Cell("bb", "EUR_CAD", "long", "mid",
         {"period": 50, "n_std": 2.0, "depth": 0.00}),
    Cell("bb", "USD_JPY", "long", "mid",
         {"period": 50, "n_std": 1.5, "depth": 0.10}),
    # MACD v2 — 5 pairs, LIMIT entry only (mid was NULL), 1.0%/1.0% RR
    Cell("macd", "AUD_JPY", "long", "limit",
         {"fast": 18, "slow": 39, "signal": 5, "trigger": "signal_cross"}),
    Cell("macd", "CAD_CHF", "short", "limit",
         {"fast": 6,  "slow": 13, "signal": 5, "trigger": "signal_cross"}),
    Cell("macd", "EUR_CHF", "short", "limit",
         {"fast": 6,  "slow": 13, "signal": 9, "trigger": "signal_cross"}),
    Cell("macd", "NZD_JPY", "long", "limit",
         {"fast": 6,  "slow": 13, "signal": 5, "trigger": "zero_cross"}),
    Cell("macd", "NZD_USD", "short", "limit",
         {"fast": 6,  "slow": 13, "signal": 9, "trigger": "signal_cross"}),
    # SMA v2 distance-band — 3 pairs, mid entry, 1.0%/1.0% RR
    Cell("sma", "CAD_JPY", "long", "mid",
         {"period": 200, "k": 2.5, "atr_period": 14}),
    Cell("sma", "EUR_CAD", "long", "mid",
         {"period": 100, "k": 1.5, "atr_period": 14}),
    Cell("sma", "EUR_GBP", "long", "mid",
         {"period": 200, "k": 2.5, "atr_period": 14}),
    # EMA v2 distance-band — 4 pairs, mid entry, 1.0%/1.0% RR
    Cell("ema", "CHF_JPY", "long", "mid",
         {"period": 20,  "k": 2.0, "atr_period": 14}),
    Cell("ema", "EUR_CAD", "long", "mid",
         {"period": 100, "k": 2.0, "atr_period": 14}),
    Cell("ema", "EUR_GBP", "short", "mid",
         {"period": 200, "k": 1.5, "atr_period": 14}),
    Cell("ema", "GBP_CAD", "long", "mid",
         {"period": 200, "k": 2.0, "atr_period": 14}),
    # RSI v2 fresh-recovery — 3 pairs, mid entry, 1.0%/1.0% RR
    Cell("rsi", "CHF_JPY", "long", "mid",
         {"period": 14, "threshold": 35, "recovery": 1}),
    Cell("rsi", "EUR_GBP", "long", "mid",
         {"period": 21, "threshold": 35, "recovery": 1}),
    Cell("rsi", "USD_JPY", "long", "mid",
         {"period": 7,  "threshold": 35, "recovery": 1}),
    # CCI v2 fresh-recovery — 5 pairs, mid entry, 1.0%/1.0% RR
    Cell("cci", "CAD_CHF", "short", "mid",
         {"period": 14, "threshold": 100, "recovery": 1}),
    Cell("cci", "CHF_JPY", "long", "mid",
         {"period": 40, "threshold": 100, "recovery": 1}),
    Cell("cci", "EUR_USD", "short", "mid",
         {"period": 30, "threshold": 100, "recovery": 1}),
    Cell("cci", "USD_CAD", "long", "mid",
         {"period": 40, "threshold": 150, "recovery": 1}),
    Cell("cci", "USD_JPY", "long", "mid",
         {"period": 40, "threshold": 100, "recovery": 2}),
    # ATR v2 conditional-momentum — 3 pairs, LIMIT entry (best variant), 1.0%/1.0% RR
    Cell("atr", "EUR_NOK", "long", "limit",
         {"atr_period": 14, "k": 1.0, "trigger": "range_expansion", "range_lookback": 14}),
    Cell("atr", "NZD_CHF", "short", "limit",
         {"atr_period": 14, "k": 0.5, "trigger": "range_expansion", "range_lookback": 14}),
    Cell("atr", "USD_JPY", "long", "limit",
         {"atr_period": 14, "k": 0.5, "trigger": "range_expansion", "range_lookback": 14}),
    # Ichimoku v2 — 1 pair, LIMIT entry, 1.0%/1.0% RR
    Cell("ichimoku", "USD_SGD", "short", "limit",
         {"tenkan": 9, "kijun": 26, "senkou_b": 52, "displacement": 26,
          "trigger": "tk_cross"}),
    # Candlestick v2 — 1 pair, mid entry, 1.0%/1.0% RR
    Cell("candle", "USD_JPY", "long", "mid",
         {"pattern": "bull_engulf", "strict": False}),
]


# Per-cell expectancy rank at TP=0.5R from the last 18 months of historical
# H4 data (research/mfe_tp_sweep/per_trade.csv, computed 2026-05-13). Higher
# value = stronger recent edge. Used to prioritize cells when MAX_NEW_ORDERS_PER_RUN
# or safety gates would otherwise drop fires arriving later in CELLS order.
# Refresh by re-running research/mfe_tp_sweep/run_mfe_sweep.py and grouping
# per_trade.csv by (strategy, pair, direction).mean("r_tp0.5") over last 540d.
# NOTE: ranks computed at TP=0.5R — refresh pending.
CELL_QUALITY_RANK: dict[tuple[str, str, str], float] = {
    ("ema",      "CHF_JPY", "long"):  0.3235,
    ("rsi",      "CHF_JPY", "long"):  0.3209,
    ("rsi",      "EUR_GBP", "long"):  0.3140,
    ("bb",       "CHF_JPY", "long"):  0.2911,
    ("bb",       "USD_JPY", "long"):  0.2447,
    ("macd",     "CAD_CHF", "short"): 0.2439,
    ("sma",      "EUR_GBP", "long"):  0.2434,
    ("macd",     "NZD_JPY", "long"):  0.2273,
    ("cci",      "CAD_CHF", "short"): 0.2178,
    ("ema",      "EUR_CAD", "long"):  0.1998,
    ("cci",      "CHF_JPY", "long"):  0.1968,
    ("macd",     "EUR_CHF", "short"): 0.1909,
    ("bb",       "CAD_CHF", "short"): 0.1826,
    ("macd",     "NZD_USD", "short"): 0.1757,
    ("stoch",    "CAD_CHF", "short"): 0.1725,
    ("ema",      "EUR_GBP", "short"): 0.1656,
    ("rsi",      "USD_JPY", "long"):  0.1627,
    ("sma",      "EUR_CAD", "long"):  0.1596,
    ("bb",       "AUD_CAD", "short"): 0.1250,
    ("atr",      "NZD_CHF", "short"): 0.1226,
    ("stoch",    "EUR_GBP", "long"):  0.1049,
    ("stoch",    "CHF_JPY", "long"):  0.1000,
    ("cci",      "USD_CAD", "long"):  0.0976,
    ("sma",      "CAD_JPY", "long"):  0.0946,
    ("ichimoku", "USD_SGD", "short"): 0.0927,
    ("cci",      "EUR_USD", "short"): 0.0914,
    ("candle",   "USD_JPY", "long"):  0.0862,
    ("cci",      "USD_JPY", "long"):  0.0843,
    ("ema",      "GBP_CAD", "long"):  0.0800,
    ("stoch",    "USD_JPY", "long"):  0.0522,
    ("atr",      "USD_JPY", "long"):  0.0369,
    ("bb",       "EUR_CAD", "long"):  0.0129,
    ("macd",     "AUD_JPY", "long"): -0.0122,
    ("atr",      "EUR_NOK", "long"): -0.0325,
}


def ranked_cells(cells: list[Cell] | None = None) -> list[Cell]:
    """Return cells sorted by CELL_QUALITY_RANK descending.

    Cells missing from the rank map sort last (rank = -inf), preserving their
    relative order. Use this in any consumer that processes fires under a cap
    (MAX_NEW_ORDERS_PER_RUN, direction gate, margin gate) so the highest-edge
    setups consume scarce slots first.
    """
    src = cells if cells is not None else CELLS
    return sorted(
        src,
        key=lambda c: CELL_QUALITY_RANK.get(
            (c.strategy, c.pair, c.direction), float("-inf"),
        ),
        reverse=True,
    )


def _bb_fired(mid_df: pd.DataFrame, params: dict, direction: str) -> bool:
    """Close pierces lower (long) / upper (short) band by `depth`*bandwidth,
    fresh trigger on the most recently closed bar.
    """
    bb = bollinger_bands(mid_df, period=params["period"], n_std=params["n_std"])
    close = mid_df["close"].to_numpy(dtype=float)
    lower = bb["lower"].to_numpy(dtype=float)
    upper = bb["upper"].to_numpy(dtype=float)
    bw = upper - lower
    depth = float(params["depth"])
    n = len(close)
    if n < 2:
        return False
    last = n - 1

    def cond_at(idx: int) -> bool:
        if direction == "long":
            t = lower[idx] - depth * bw[idx]
            return not np.isnan(t) and close[idx] < t
        t = upper[idx] + depth * bw[idx]
        return not np.isnan(t) and close[idx] > t

    return cond_at(last) and not cond_at(last - 1)


def _macd_fired(mid_df: pd.DataFrame, params: dict, direction: str) -> bool:
    """MACD signal_cross or zero_cross, fresh trigger on the most recently
    closed bar.
    """
    m = macd(mid_df, fast=params["fast"], slow=params["slow"], signal=params["signal"])
    macd_arr = m["macd"].to_numpy(dtype=float)
    sig_arr = m["signal"].to_numpy(dtype=float)
    n = len(macd_arr)
    if n < 2:
        return False
    last = n - 1
    if np.isnan(macd_arr[last]) or np.isnan(macd_arr[last - 1]):
        return False
    trigger = params["trigger"]
    if trigger == "signal_cross":
        if np.isnan(sig_arr[last]) or np.isnan(sig_arr[last - 1]):
            return False
        if direction == "long":
            return bool(macd_arr[last] > sig_arr[last]
                        and macd_arr[last - 1] <= sig_arr[last - 1])
        return bool(macd_arr[last] < sig_arr[last]
                    and macd_arr[last - 1] >= sig_arr[last - 1])
    # zero_cross
    if direction == "long":
        return bool(macd_arr[last] > 0 and macd_arr[last - 1] <= 0)
    return bool(macd_arr[last] < 0 and macd_arr[last - 1] >= 0)


def _osc_recovery_fired(arr: np.ndarray, threshold: float, recovery: int,
                        direction: str, *, signed: bool = False) -> bool:
    """Generic oscillator fresh-recovery trigger used by stoch, rsi, cci.

    Long: oscillator rising for `recovery` consecutive bars, base < threshold.
      - signed=False: base < threshold (e.g. Stoch %K < 20, RSI < 35)
      - signed=True:  base < -threshold (e.g. CCI < -100)
    Short: mirror.
      - signed=False: base > 100 - threshold
      - signed=True:  base >  threshold

    "Fresh" means the trigger condition is true now AND was not true on the
    previous bar.
    """
    n = len(arr)
    if n < recovery + 2:
        return False
    last = n - 1
    if signed:
        long_base, short_base = -threshold, threshold
    else:
        long_base, short_base = threshold, 100.0 - threshold

    def cond_at(idx: int) -> bool:
        base = arr[idx - recovery]
        if np.isnan(base) or np.isnan(arr[idx]):
            return False
        if direction == "long":
            consec = all(arr[idx - i] > arr[idx - i - 1] for i in range(recovery))
            return bool(consec and base < long_base)
        consec = all(arr[idx - i] < arr[idx - i - 1] for i in range(recovery))
        return bool(consec and base > short_base)

    return cond_at(last) and not cond_at(last - 1)


def _stoch_fired(mid_df: pd.DataFrame, params: dict, direction: str) -> bool:
    s = stochastic(mid_df, k_period=params["k_period"], d_period=params["d_period"])
    return _osc_recovery_fired(s["k"].to_numpy(dtype=float),
                               float(params["threshold"]),
                               int(params["recovery"]),
                               direction, signed=False)


def _rsi_fired(mid_df: pd.DataFrame, params: dict, direction: str) -> bool:
    r = rsi(mid_df, period=params["period"]).to_numpy(dtype=float)
    return _osc_recovery_fired(r, float(params["threshold"]),
                               int(params["recovery"]),
                               direction, signed=False)


def _cci_fired(mid_df: pd.DataFrame, params: dict, direction: str) -> bool:
    c = cci(mid_df, period=params["period"]).to_numpy(dtype=float)
    return _osc_recovery_fired(c, float(params["threshold"]),
                               int(params["recovery"]),
                               direction, signed=True)


def _ma_distance_fired(mid_df: pd.DataFrame, params: dict, direction: str,
                       ma_fn) -> bool:
    """SMA/EMA distance-band trigger: close pierces (MA - k·ATR) [long] or
    (MA + k·ATR) [short], fresh."""
    ma_arr = ma_fn(mid_df, period=params["period"]).to_numpy(dtype=float)
    atr_arr = atr(mid_df, period=params["atr_period"]).to_numpy(dtype=float)
    close = mid_df["close"].to_numpy(dtype=float)
    k = float(params["k"])
    n = len(close)
    if n < 2:
        return False
    last = n - 1

    def cond_at(idx: int) -> bool:
        if np.isnan(close[idx]) or np.isnan(ma_arr[idx]) or np.isnan(atr_arr[idx]):
            return False
        if direction == "long":
            return bool(close[idx] < ma_arr[idx] - k * atr_arr[idx])
        return bool(close[idx] > ma_arr[idx] + k * atr_arr[idx])

    return cond_at(last) and not cond_at(last - 1)


def _sma_fired(mid_df: pd.DataFrame, params: dict, direction: str) -> bool:
    return _ma_distance_fired(mid_df, params, direction, sma)


def _ema_fired(mid_df: pd.DataFrame, params: dict, direction: str) -> bool:
    return _ma_distance_fired(mid_df, params, direction, ema)


def _atr_fired(mid_df: pd.DataFrame, params: dict, direction: str) -> bool:
    """ATR conditional-momentum: close_breakout (price moves k·ATR vs prev close)
    or range_expansion (bar's range > k·mean_range AND closed in trigger
    direction). Both fresh-edge.
    """
    open_arr = mid_df["open"].to_numpy(dtype=float)
    high = mid_df["high"].to_numpy(dtype=float)
    low = mid_df["low"].to_numpy(dtype=float)
    close = mid_df["close"].to_numpy(dtype=float)
    n = len(close)
    if n < 3:
        return False
    last = n - 1
    trigger = params["trigger"]
    k = float(params["k"])

    if trigger == "close_breakout":
        atr_arr = atr(mid_df, period=params["atr_period"]).to_numpy(dtype=float)

        def cond_at(idx: int) -> bool:
            if idx < 1 or np.isnan(close[idx - 1]) or np.isnan(atr_arr[idx - 1]):
                return False
            if direction == "long":
                return bool(close[idx] > close[idx - 1] + k * atr_arr[idx - 1])
            return bool(close[idx] < close[idx - 1] - k * atr_arr[idx - 1])

        return cond_at(last) and not cond_at(last - 1)

    # range_expansion: bar's range > k * prior mean(range, lookback) AND close
    # is in trigger direction relative to open
    lookback = int(params.get("range_lookback", 14))
    rng = high - low
    mean_rng = pd.Series(rng).rolling(lookback, min_periods=lookback).mean().to_numpy()

    def cond_at(idx: int) -> bool:
        if idx < 1 or np.isnan(mean_rng[idx - 1]):
            return False
        big_bar = rng[idx] > k * mean_rng[idx - 1]
        directional = (close[idx] > open_arr[idx]) if direction == "long" else (close[idx] < open_arr[idx])
        return bool(big_bar and directional)

    return cond_at(last) and not cond_at(last - 1)


def _ichimoku_fired(mid_df: pd.DataFrame, params: dict, direction: str) -> bool:
    """Ichimoku tk_cross: tenkan crosses kijun in trigger direction (fresh)."""
    ich = ichimoku(mid_df,
                   tenkan_period=params["tenkan"],
                   kijun_period=params["kijun"],
                   senkou_b_period=params["senkou_b"],
                   displacement=params["displacement"])
    tenkan = ich["tenkan"].to_numpy(dtype=float)
    kijun = ich["kijun"].to_numpy(dtype=float)
    n = len(tenkan)
    if n < 2:
        return False
    last = n - 1
    trigger = params["trigger"]
    if trigger != "tk_cross":
        # Only tk_cross is in the production set; defensive fallback
        return False
    if (np.isnan(tenkan[last]) or np.isnan(kijun[last])
            or np.isnan(tenkan[last - 1]) or np.isnan(kijun[last - 1])):
        return False
    if direction == "long":
        return bool(tenkan[last] > kijun[last] and tenkan[last - 1] <= kijun[last - 1])
    return bool(tenkan[last] < kijun[last] and tenkan[last - 1] >= kijun[last - 1])


def _candle_fired(mid_df: pd.DataFrame, params: dict, direction: str) -> bool:
    """Candlestick pattern fires when the most-recent bar matches the pattern.
    Currently supports `bull_engulf` (the only production cell)."""
    pattern = params["pattern"]
    strict = bool(params.get("strict", False))
    if pattern == "bull_engulf":
        kwargs = {"min_body_frac": 0.5} if strict else {}
        mask = is_bullish_engulfing(mid_df, **kwargs).to_numpy(dtype=bool)
    else:
        return False
    if len(mask) < 1:
        return False
    return bool(mask[-1])


_EVALUATORS = {
    "stoch": _stoch_fired,
    "bb": _bb_fired,
    "macd": _macd_fired,
    "sma": _sma_fired,
    "ema": _ema_fired,
    "rsi": _rsi_fired,
    "cci": _cci_fired,
    "atr": _atr_fired,
    "ichimoku": _ichimoku_fired,
    "candle": _candle_fired,
}


def evaluate_cell(cell: Cell, mid_df: pd.DataFrame) -> bool:
    fn = _EVALUATORS.get(cell.strategy)
    if fn is None:
        raise ValueError(f"no evaluator for strategy: {cell.strategy}")
    return fn(mid_df, cell.params, cell.direction)


def _price_precision(pair: str) -> int:
    """5 decimals for major pairs, 3 for JPY/HUF. Mirrors bh_ftmo_paper."""
    quote = pair.split("_", 1)[1]
    return 3 if quote in {"JPY", "HUF"} else 5


# Research-backed exit override for the validated long mean-reversion cells.
# research/exit_geometry_v1 (EXIT_SWEEP_v1.md): on the long-MR book, TP 1.5% / SL 1.0% /
# 10-day hold beats the global 1%/1%/14d v2 default on total money — the steadier total-money
# winner, profitable across all three eras (A/B + recent holdout). Scoped to ONLY the cells the
# sweep validated — long, mean-reversion (bb/rsi/ema/stoch), mid entry. Every other cell (shorts,
# trend strategies macd/atr/ichimoku/sma, limit entries) keeps the global 1%/1% convention; the
# sweep says nothing about those. Stop is unchanged (1.0%) — only the target widens to 1.5%.
# Applied inside compute_entry_stop_target so the live trader AND this briefing agree; the 10-day
# hold is enforced trader-side via the position age cap (LONG_MR_MAX_HOLD_DAYS).
LONG_MR_EXIT_STRATEGIES = frozenset({"bb", "rsi", "ema", "stoch"})
LONG_MR_TP_PCT = 0.015
LONG_MR_SL_PCT = 0.010
LONG_MR_MAX_HOLD_DAYS = 10


def uses_long_mr_exit(strategy: str, direction: str, entry_mode: str) -> bool:
    """True for the long mean-reversion mid cells whose exits the exit-geometry sweep validated."""
    return (
        strategy in LONG_MR_EXIT_STRATEGIES
        and direction == "long"
        and entry_mode == "mid"
    )


def cell_uses_long_mr_exit(cell: Cell) -> bool:
    """Cell-level wrapper for :func:`uses_long_mr_exit`."""
    return uses_long_mr_exit(cell.strategy, cell.direction, cell.entry_mode)


def compute_entry_stop_target(cell: Cell, mid_df: pd.DataFrame) -> tuple[float, float, float]:
    """Return (entry_price, stop_price, target_price) for the cell's trigger bar.

    mid entries fill at the trigger bar's close (market on next tick = the
    'now' price). limit entries fill at the trigger bar's low (long) or high
    (short), valid only for the next H4 bar.

    Validated long-MR cells (:func:`cell_uses_long_mr_exit`) use the research-backed
    TP 1.5% / SL 1.0% geometry; every other cell uses the global 1%/1% v2 convention.
    """
    if cell_uses_long_mr_exit(cell):
        tp, sl = LONG_MR_TP_PCT, LONG_MR_SL_PCT
    else:
        tp, sl = TP_PCT, STOP_PCT
    if cell.entry_mode == "mid":
        entry = float(mid_df["close"].iloc[-1])
    else:  # limit
        entry = float(mid_df["low"].iloc[-1] if cell.direction == "long"
                      else mid_df["high"].iloc[-1])
    if cell.direction == "long":
        return entry, entry * (1 - sl), entry * (1 + tp)
    return entry, entry * (1 + sl), entry * (1 - tp)


def render_console_report(
    fires: list[dict],
    now_utc: datetime,
    total_cells: int,
    bar_ts_by_pair: dict[str, pd.Timestamp],
    verbose: bool = False,
    cells: Optional[list[Cell]] = None,
) -> str:
    lines = []
    lines.append(f"BH Briefing — H4 v2 signals  ({now_utc.strftime('%Y-%m-%d %H:%M UTC')})")
    if bar_ts_by_pair:
        latest = max(bar_ts_by_pair.values()) + pd.Timedelta(hours=H4_BAR_HOURS)
        earliest = min(bar_ts_by_pair.values()) + pd.Timedelta(hours=H4_BAR_HOURS)
        if latest == earliest:
            lines.append(f"Trigger bar (closed): {latest.strftime('%Y-%m-%d %H:%M UTC')}  "
                         f"(uniform across {len(bar_ts_by_pair)} pairs)")
        else:
            lines.append(f"Trigger bars (closed): {earliest.strftime('%Y-%m-%d %H:%M UTC')} "
                         f"to {latest.strftime('%Y-%m-%d %H:%M UTC')} "
                         f"(staggered across {len(bar_ts_by_pair)} pairs)")
    lines.append(f"Cells evaluated: {total_cells}  Fires: {len(fires)}")
    n_high_ny = sum(1 for f in fires if f.get("high_ny_skip"))
    lines.append(
        f"High∩NY skip-flagged (strong-4 long, research: SKIP): {n_high_ny}")
    lines.append("")
    if not fires:
        lines.append("(no signals fired on most recent H4 bar)")
    else:
        by_pair_dir: dict[tuple[str, str], list[dict]] = {}
        for f in fires:
            by_pair_dir.setdefault((f["pair"], f["direction"]), []).append(f)
        # Most-confirmed first, then alphabetical
        for (pair, direction), items in sorted(by_pair_dir.items(),
                                                key=lambda kv: (-len(kv[1]), kv[0])):
            n = len(items)
            strategies = ", ".join(it["strategy"] for it in items)
            lines.append(f"  {pair} {direction.upper():<5}  {n}× {strategies}")
            for it in items:
                prec = it["precision"]
                entry_text = (f"market  @ {it['entry']:.{prec}f}"
                              if it["entry_mode"] == "mid"
                              else f"limit   @ {it['entry']:.{prec}f}  (1 H4-bar fill window)")
                lines.append(f"      {it['strategy']:<6} {entry_text}")
                lines.append(f"             stop {it['stop']:.{prec}f}   "
                             f"target {it['target']:.{prec}f}   "
                             f"({STOP_PCT*100:.1f}% / {TP_PCT*100:.1f}%)")
                align = it.get("d1_align", "flat")
                warn = "  ⚠ negative counter-trend (historical money-loser)" if it.get("ct_warn") else ""
                lines.append(f"             D1 {align:<13} session {it.get('session', '?')}{warn}")
                if it.get("high_ny_skip"):
                    pct = it.get("atr_pct")
                    pct_txt = (f"ATR pctile {pct*100:.0f}"
                               if isinstance(pct, (int, float)) and pct == pct else "ATR high")
                    lines.append(
                        f"             ⊘ HIGH∩NY ({pct_txt}) — research recommends SKIP "
                        f"(−0.07R/trade, +17% book)")
            lines.append("")

    if verbose and cells is not None:
        fired_keys = {(f["strategy"], f["pair"], f["direction"]) for f in fires}
        lines.append("--- All evaluated cells ---")
        for c in cells:
            mark = "FIRED" if (c.strategy, c.pair, c.direction) in fired_keys else "    ."
            param_summary = " ".join(f"{k}={v}" for k, v in c.params.items())
            lines.append(f"  {mark}  {c.strategy:<6} {c.pair:<8} {c.direction:<5} "
                         f"{c.entry_mode:<5}  {param_summary}")
    return "\n".join(lines)


def render_html_report(
    fires: list[dict],
    now_utc: datetime,
    total_cells: int,
    bar_ts_by_pair: dict[str, pd.Timestamp],
    cells: list[Cell],
) -> str:
    """Self-contained HTML with inline styles (Gmail strips <style> blocks)."""
    body_style = ("font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; "
                  "color: #1a1a1a; max-width: 760px; margin: 18px auto; padding: 0 12px;")
    h1_style = "font-size: 20px; margin: 0 0 6px;"
    meta_style = "color: #555; font-size: 13px; margin: 2px 0;"
    section_style = "margin-top: 22px;"
    sig_style = ("border: 1px solid #d6d6d6; border-radius: 6px; padding: 10px 12px; "
                 "margin: 10px 0; background: #fafafa;")
    pair_style = "font-size: 16px; font-weight: 600; margin: 0 0 4px;"
    long_color = "#0a7d2c"
    short_color = "#b1390e"
    badge_style_long = (f"display: inline-block; padding: 1px 6px; border-radius: 3px; "
                        f"background: {long_color}; color: #fff; font-size: 12px; "
                        f"margin-right: 6px; font-weight: 600;")
    badge_style_short = (f"display: inline-block; padding: 1px 6px; border-radius: 3px; "
                         f"background: {short_color}; color: #fff; font-size: 12px; "
                         f"margin-right: 6px; font-weight: 600;")
    confs_style = "color: #555; font-size: 13px; margin: 0 0 8px;"
    row_style = ("font-family: ui-monospace, SFMono-Regular, Menlo, monospace; "
                 "font-size: 13px; margin: 2px 0;")
    label_style = "color: #777; display: inline-block; min-width: 56px;"
    table_style = ("border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 8px;")
    th_style = ("text-align: left; border-bottom: 1px solid #d6d6d6; "
                "padding: 6px 8px; color: #555; font-weight: 600;")
    td_style = "padding: 4px 8px; border-bottom: 1px solid #efefef;"

    parts = [f'<body style="{body_style}">']
    parts.append(f'<h1 style="{h1_style}">BH Briefing — H4 v2 signals</h1>')
    parts.append(f'<p style="{meta_style}">Run: {html.escape(now_utc.strftime("%Y-%m-%d %H:%M UTC"))}</p>')
    if bar_ts_by_pair:
        latest = max(bar_ts_by_pair.values()) + pd.Timedelta(hours=H4_BAR_HOURS)
        earliest = min(bar_ts_by_pair.values()) + pd.Timedelta(hours=H4_BAR_HOURS)
        if latest == earliest:
            parts.append(f'<p style="{meta_style}">Trigger bar (closed): '
                         f'{html.escape(latest.strftime("%Y-%m-%d %H:%M UTC"))} '
                         f'(uniform across {len(bar_ts_by_pair)} pairs)</p>')
        else:
            parts.append(f'<p style="{meta_style}">Trigger bars (closed): '
                         f'{html.escape(earliest.strftime("%Y-%m-%d %H:%M UTC"))} '
                         f'to {html.escape(latest.strftime("%Y-%m-%d %H:%M UTC"))}</p>')
    parts.append(f'<p style="{meta_style}">Cells evaluated: {total_cells} &nbsp;|&nbsp; '
                 f'Fires: <b>{len(fires)}</b></p>')

    parts.append(f'<div style="{section_style}">')
    if not fires:
        parts.append(f'<p style="{meta_style}">(no signals fired on most recent H4 bar)</p>')
    else:
        by_pair_dir: dict[tuple[str, str], list[dict]] = {}
        for f in fires:
            by_pair_dir.setdefault((f["pair"], f["direction"]), []).append(f)
        for (pair, direction), items in sorted(by_pair_dir.items(),
                                                key=lambda kv: (-len(kv[1]), kv[0])):
            badge = badge_style_long if direction == "long" else badge_style_short
            confs = ", ".join(it["strategy"] for it in items)
            parts.append(f'<div style="{sig_style}">')
            parts.append(f'<div style="{pair_style}">'
                         f'<span style="{badge}">{html.escape(direction.upper())}</span>'
                         f'{html.escape(pair)}'
                         f'</div>')
            parts.append(f'<div style="{confs_style}">{len(items)}× confirmation'
                         f'{"s" if len(items) > 1 else ""}: {html.escape(confs)}</div>')
            for it in items:
                prec = it["precision"]
                entry_label = ("market" if it["entry_mode"] == "mid" else "limit")
                fill_note = "" if it["entry_mode"] == "mid" else " (1 H4-bar fill window)"
                parts.append(f'<div style="{row_style}">'
                             f'<span style="{label_style}">{html.escape(it["strategy"])}</span>'
                             f' {html.escape(entry_label)} @ '
                             f'<b>{it["entry"]:.{prec}f}</b>{html.escape(fill_note)}'
                             f'</div>')
                parts.append(f'<div style="{row_style}">'
                             f'<span style="{label_style}">stop</span>'
                             f' {it["stop"]:.{prec}f}'
                             f' &nbsp; <span style="color:#777;">target</span>'
                             f' {it["target"]:.{prec}f}'
                             f' &nbsp; <span style="color:#777;">RR</span>'
                             f' {STOP_PCT*100:.1f}% / {TP_PCT*100:.1f}%'
                             f'</div>')
                # D1-alignment + session annotations (annotate-only; nothing suppressed)
                align = it.get("d1_align", "flat")
                align_bg = {"with-trend": "#0a7d2c", "counter-trend": "#9a6700"}.get(align, "#777")
                tag_base = ("display: inline-block; padding: 1px 6px; border-radius: 3px; "
                            "color: #fff; font-size: 11px; margin-right: 6px; font-weight: 600;")
                neutral_tag = ("display: inline-block; padding: 1px 6px; border-radius: 3px; "
                               "border: 1px solid #c8c8c8; color: #555; font-size: 11px; "
                               "margin-right: 6px;")
                parts.append(f'<div style="{row_style}">'
                             f'<span style="{tag_base} background: {align_bg};">'
                             f'{html.escape(align)}</span>'
                             f'<span style="{neutral_tag}">{html.escape(it.get("session", "?"))}</span>'
                             + (f'<span style="color:#b1390e; font-weight:600;">'
                                f'⚠ negative counter-trend (historical money-loser)</span>'
                                if it.get("ct_warn") else "")
                             + '</div>')
                if it.get("high_ny_skip"):
                    pct = it.get("atr_pct")
                    pct_txt = (f"ATR pctile {pct*100:.0f}"
                               if isinstance(pct, (int, float)) and pct == pct else "ATR high")
                    parts.append(
                        f'<div style="{row_style}">'
                        f'<span style="{tag_base} background: #b1390e;">⊘ HIGH∩NY</span>'
                        f'<span style="color:#b1390e; font-weight:600;">'
                        f'research recommends SKIP ({html.escape(pct_txt)}; '
                        f'−0.07R/trade, +17% book)</span>'
                        f'</div>')
            parts.append('</div>')
    parts.append('</div>')

    # Roster of all evaluated cells, for transparency
    fired_keys = {(f["strategy"], f["pair"], f["direction"]) for f in fires}
    parts.append(f'<div style="{section_style}">')
    parts.append(f'<h2 style="font-size: 15px; margin: 0 0 6px;">All evaluated cells</h2>')
    parts.append(f'<table style="{table_style}">')
    parts.append(f'<tr>'
                 f'<th style="{th_style}">Status</th>'
                 f'<th style="{th_style}">Strategy</th>'
                 f'<th style="{th_style}">Pair</th>'
                 f'<th style="{th_style}">Direction</th>'
                 f'<th style="{th_style}">Entry</th>'
                 f'<th style="{th_style}">Params</th>'
                 f'</tr>')
    for c in cells:
        is_fired = (c.strategy, c.pair, c.direction) in fired_keys
        row_bg = "background:#fffbe5;" if is_fired else ""
        status = ("<b>fired</b>" if is_fired else
                  '<span style="color:#bbb;">.</span>')
        param_summary = " ".join(f"{k}={v}" for k, v in c.params.items())
        parts.append(f'<tr style="{row_bg}">'
                     f'<td style="{td_style}">{status}</td>'
                     f'<td style="{td_style}">{html.escape(c.strategy)}</td>'
                     f'<td style="{td_style}">{html.escape(c.pair)}</td>'
                     f'<td style="{td_style}">{html.escape(c.direction)}</td>'
                     f'<td style="{td_style}">{html.escape(c.entry_mode)}</td>'
                     f'<td style="{td_style}; font-family: ui-monospace, monospace;">'
                     f'{html.escape(param_summary)}</td>'
                     f'</tr>')
    parts.append('</table>')
    parts.append('</div>')

    parts.append('</body>')
    return ("<!DOCTYPE html>\n<html><head><meta charset='utf-8'>"
            "<title>BH Briefing</title></head>\n" + "\n".join(parts) + "\n</html>")


def _send_html_email(subject: str, html_body: str) -> bool:
    """Send HTML email via SMTP_* env vars. Mirrors send_failure_email but with
    text/html mime subtype.
    """
    server = os.environ.get("SMTP_SERVER")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    recipient = os.environ.get("EMAIL_RECIPIENT")
    sender = os.environ.get("EMAIL_SENDER", user or "bh-ftmo@localhost")
    port = int(os.environ.get("SMTP_PORT", "587"))

    if not (server and user and password and recipient):
        LOG.warning("SMTP not fully configured; skipping email")
        return False

    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    try:
        with smtplib.SMTP(server, port, timeout=30) as s:
            s.starttls()
            s.login(user, password)
            s.sendmail(sender, [recipient], msg.as_string())
        LOG.info("briefing email sent to %s", recipient)
        return True
    except Exception as exc:  # noqa: BLE001
        LOG.warning("briefing email failed (%s): %s", type(exc).__name__, exc)
        return False


def evaluate_fires() -> tuple[list[dict], list[Cell], dict[str, pd.Timestamp]]:
    """Load H4 bars, evaluate every cell on the most-recently-closed bar,
    return the (fires, ordered_cells, bar_ts_by_pair) tuple.

    Extracted from run() so external tools (e.g. bh_briefing_ftmo.py) can
    consume the v2 cell fire-evaluation without driving the rendering layer.
    """
    pair_set = {c.pair for c in CELLS}
    LOG.info("evaluating %d cells across %d pairs", len(CELLS), len(pair_set))

    store = FxStore(read_only=True)
    bars: dict[str, pd.DataFrame] = {}
    bar_ts_by_pair: dict[str, pd.Timestamp] = {}
    try:
        for pair in pair_set:
            df = store.load(pair, granularity="H4", include_incomplete=False)
            if df is None or df.empty or len(df) < 60:
                LOG.warning("skipping %s: insufficient bars (%d)",
                            pair, 0 if df is None else len(df))
                continue
            bars[pair] = df.tail(LOOKBACK_BARS).reset_index(drop=True)
            bar_ts_by_pair[pair] = pd.Timestamp(bars[pair]["timestamp"].iloc[-1])
    finally:
        store.close()

    # Iterate cells in CELL_QUALITY_RANK descending order so the briefing's
    # fired-list AND full-cell table both surface highest-edge setups first.
    ordered_cells = ranked_cells()

    fires: list[dict] = []
    for cell in ordered_cells:
        df = bars.get(cell.pair)
        if df is None:
            continue
        mid = ohlc_mid(df)
        if not evaluate_cell(cell, mid):
            continue
        entry, stop, target = compute_entry_stop_target(cell, mid)
        bar_ts = pd.Timestamp(df["timestamp"].iloc[-1])
        align = d1_alignment(mid, df["timestamp"], cell.direction)
        fires.append({
            "strategy": cell.strategy,
            "pair": cell.pair,
            "direction": cell.direction,
            "entry_mode": cell.entry_mode,
            "bar_ts": bar_ts,
            "entry": entry,
            "stop": stop,
            "target": target,
            "precision": _price_precision(cell.pair),
            "d1_align": align,
            "session": session_of(bar_ts),
            "ct_warn": align == "counter-trend"
                       and cell.strategy in NEG_COUNTER_TREND_STRATEGIES,
            "atr_pct": atr_pct_w252(mid),
            "high_ny_skip": is_high_ny_skip(
                cell.strategy, cell.direction, bar_ts, mid),
        })
    return fires, ordered_cells, bar_ts_by_pair


def run(*, verbose: bool = False, email: bool = False,
        email_only_if_fires: bool = False) -> int:
    fires, ordered_cells, bar_ts_by_pair = evaluate_fires()

    now_utc = datetime.now(UTC)
    report = render_console_report(
        fires, now_utc,
        total_cells=len(ordered_cells),
        bar_ts_by_pair=bar_ts_by_pair,
        verbose=verbose, cells=ordered_cells,
    )
    print(report)

    html_body = render_html_report(
        fires, now_utc,
        total_cells=len(ordered_cells),
        bar_ts_by_pair=bar_ts_by_pair,
        cells=ordered_cells,
    )
    BRIEFING_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = BRIEFING_DIR / f"briefing_{now_utc.strftime('%Y-%m-%d_%H%M')}.html"
    archive_path.write_text(html_body, encoding="utf-8")
    LOG.info("archived briefing → %s", archive_path)

    if email:
        if email_only_if_fires and not fires:
            LOG.info("no fires — skipping email (--email-only-if-fires)")
        else:
            bar_label = ""
            if bar_ts_by_pair:
                bar_label = f" — bar {max(bar_ts_by_pair.values()).strftime('%Y-%m-%d %H:%M UTC')}"
            subject = f"[BH Briefing] {len(fires)} fire(s){bar_label}"
            _send_html_email(subject, html_body)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="BH FTMO morning briefing — v2 signals")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="List every cell with fired/not-fired status")
    parser.add_argument("--email", action="store_true",
                        help="Email the HTML briefing via SMTP_* env vars "
                             "(the HTML is always archived to src/logs/briefings/)")
    parser.add_argument("--email-only-if-fires", action="store_true",
                        help="With --email: skip the SMTP send when there are "
                             "no fires (cron-friendly)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s",
                        stream=sys.stderr)
    return run(verbose=args.verbose, email=args.email,
               email_only_if_fires=args.email_only_if_fires)


if __name__ == "__main__":
    raise SystemExit(main())
