#!/usr/bin/env python3
"""
Assumption Tester — Validate trading assumptions against historical data.

Phase 1: Score all symbols for N historical dates using current algorithm (lean mode).
         Cache top-ranked symbols per date to CSV.
Phase 2: Simulate trades using next-day-forward OHLCV data.
         Generate raw simulation data with daily highs/lows.
Phase 3: Analyze parameter sweep (target%, stop%, hold_days, top_n).
         Tiered exit analysis (T1 at 1%, raise stop to breakeven, T2 at 2%).

Usage:
  # Full run (Phase 1 + 2 + 3)
  python src/research/assumption_tester.py --dates 250 --top-n 20

  # Phase 1 only (scoring, saves cache)
  python src/research/assumption_tester.py --phase1-only --dates 250 --top-n 20

  # Phase 2+3 only (uses cached Phase 1 scores, optional slippage)
  python src/research/assumption_tester.py --skip-phase1 --slippage 0.002
"""

import argparse
import csv
import logging
import os
import sys
import time
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import duckdb

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bluehorseshoe.analysis.constants import (
    ATR_WINDOW,
    MAX_STOCK_PRICE,
    MIN_STOCK_PRICE,
)
from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer
from bluehorseshoe.data.duckdb_store import DuckDBStore
from bluehorseshoe.data.historical_data import get_technical_indicators


# ---------------------------------------------------------------------------
# Lightweight read-only DuckDB helpers (avoids DuckDBStore lock issues)
# ---------------------------------------------------------------------------

def _duckdb_ro(path: str):
    """Open a read-only DuckDB connection."""
    return duckdb.connect(path, read_only=True)


def _load_symbol_ro(con, symbol: str) -> Optional[pd.DataFrame]:
    """Load OHLCV for one symbol via a read-only connection."""
    df = con.execute(
        "SELECT date, open, high, low, close, volume FROM ohlcv WHERE symbol = ? ORDER BY date",
        [symbol],
    ).fetchdf()
    if df.empty:
        return None
    # Convert date column to string for consistency with DuckDBStore
    df["date"] = df["date"].astype(str)
    return df


def _get_all_symbols_ro(con) -> List[str]:
    """Get sorted list of all symbols."""
    df = con.execute("SELECT DISTINCT symbol FROM ohlcv ORDER BY symbol").fetchdf()
    return df["symbol"].tolist()


def _get_symbol_dates_ro(con, symbol: str) -> List[str]:
    """Get sorted list of dates for a symbol."""
    df = con.execute(
        "SELECT DISTINCT date FROM ohlcv WHERE symbol = ? ORDER BY date", [symbol]
    ).fetchdf()
    return [str(d) for d in df["date"].tolist()]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("assumption_tester")

_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
DUCKDB_PATH = os.environ.get(
    "DUCKDB_PATH", os.path.join(_REPO_ROOT, "data", "ohlcv.duckdb")
)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "logs", "research")

# Parameter sweep defaults
TARGET_PCTS = [round(x * 0.5, 1) for x in range(1, 11)]  # 0.5% .. 5.0%
STOP_PCTS = [round(x * 0.5, 1) for x in range(1, 11)]    # 0.5% .. 5.0%
HOLD_DAYS_RANGE = list(range(1, 11))                       # 1 .. 10
TOP_N_BUCKETS = [5, 10, 15, 20]

# Minimum data rows required for indicator computation
MIN_ROWS = 60


# =========================================================================
# Phase 1 — Score & Rank
# =========================================================================

def get_trading_dates(duckdb_path: str, n_dates: int) -> List[str]:
    """Return the most recent *n_dates* trading dates from DuckDB (using SPY as reference)."""
    con = _duckdb_ro(duckdb_path)
    dates = _get_symbol_dates_ro(con, "SPY")
    con.close()
    if not dates:
        raise RuntimeError("No SPY data in DuckDB — cannot determine trading dates")
    dates = sorted(dates)
    # We need at least 10 extra days after the last target date for forward simulation,
    # so the target dates stop 10 trading days before the end of available data.
    if len(dates) <= 10:
        raise RuntimeError(f"Only {len(dates)} SPY dates available — need at least {n_dates + 10}")
    usable = dates[:-10]  # leave last 10 for forward simulation
    return usable[-n_dates:]


def _enrich_once(df_raw: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Add technical indicator columns to a raw OHLCV DataFrame (one-time per symbol)."""
    if df_raw is None or len(df_raw) < MIN_ROWS:
        return None
    indicator_dicts = get_technical_indicators(df_raw)
    return pd.DataFrame(indicator_dicts)


def _score_symbol_for_date(
    df_enriched: pd.DataFrame,
    target_date: str,
    trader: SwingTrader,
) -> List[dict]:
    """Score a symbol for one date using both strategies. Returns 0-2 candidate dicts."""
    df_slice = df_enriched[df_enriched["date"] <= target_date].tail(100)
    if len(df_slice) < MIN_ROWS:
        return []

    last_close = df_slice["close"].values[-1]
    if not (MIN_STOCK_PRICE < last_close < MAX_STOCK_PRICE):
        return []

    # Check avg volume (need avg_volume_20 column)
    avg_vol = df_slice["avg_volume_20"].values[-1] if "avg_volume_20" in df_slice.columns else 0
    if pd.isna(avg_vol) or avg_vol < 100_000:
        return []

    results = []

    # --- Baseline ---
    bl_components = TechnicalAnalyzer.calculate_technical_score(
        df_slice, strategy="baseline", aggregation="sum"
    )
    bl_score = bl_components.get("total", 0.0)
    if bl_score > 0:
        bl_setup = trader.calculate_baseline_setup(
            df_slice,
            ml_stop_multiplier=2.0,
            ml_target_multiplier=3.0,
            technical_score=bl_score,
        )
        if bl_setup.get("is_realistic") and bl_setup.get("rr_ratio", 0) >= 0.5:
            entry = bl_setup["entry_price"]
            if MIN_STOCK_PRICE < entry < MAX_STOCK_PRICE:
                results.append({
                    "strategy": "baseline",
                    "score": bl_score,
                    "entry_price": entry,
                    "stop_loss": bl_setup["stop_loss"],
                    "take_profit": bl_setup["take_profit"],
                    "rr_ratio": bl_setup["rr_ratio"],
                })

    # --- Mean Reversion ---
    mr_components = TechnicalAnalyzer.calculate_technical_score(
        df_slice, strategy="mean_reversion", aggregation="sum"
    )
    mr_score = mr_components.get("total", 0.0)
    if mr_score > 0:
        mr_setup = trader.calculate_mean_reversion_setup(
            df_slice,
            ml_stop_multiplier=1.5,
            ml_target_multiplier=2.0,
        )
        if mr_setup.get("is_realistic") and mr_setup.get("rr_ratio", 0) >= 0.5:
            entry = mr_setup["entry_price"]
            if MIN_STOCK_PRICE < entry < MAX_STOCK_PRICE:
                results.append({
                    "strategy": "mean_reversion",
                    "score": mr_score,
                    "entry_price": entry,
                    "stop_loss": mr_setup["stop_loss"],
                    "take_profit": mr_setup["take_profit"],
                    "rr_ratio": mr_setup["rr_ratio"],
                })

    return results


# --- Worker function for ProcessPoolExecutor ---

_worker_con = None  # read-only duckdb connection
_worker_trader: Optional[SwingTrader] = None

# Number of rows before the earliest target date needed for indicator lookback
LOOKBACK_BUFFER = 250


def _init_scoring_worker(duckdb_path: str):
    """Initialize per-process resources (read-only DuckDB — no lock conflicts)."""
    global _worker_con, _worker_trader
    _worker_con = _duckdb_ro(duckdb_path)
    _worker_trader = SwingTrader(database=None)


def _score_symbol_across_dates(args: Tuple[str, List[str], str]) -> List[dict]:
    """
    Score one symbol across all target dates. Runs in a worker process.

    Loads only the data window needed (earliest_date - lookback to latest_date).
    Uses tail(100) for scoring to minimize per-call overhead.

    Returns list of dicts: [{date, symbol, strategy, score, entry_price, ...}, ...]
    """
    symbol, target_dates, earliest_load_date = args
    con = _worker_con
    trader = _worker_trader

    # Load only the needed window via read-only connection
    df_raw = con.execute(
        "SELECT date, open, high, low, close, volume FROM ohlcv "
        "WHERE symbol = ? AND date >= ? ORDER BY date",
        [symbol, earliest_load_date],
    ).fetchdf()
    if df_raw is None or len(df_raw) < MIN_ROWS:
        return []
    df_raw["date"] = df_raw["date"].astype(str)

    # Quick price/volume pre-filter on last row
    last_close = df_raw["close"].values[-1]
    if not (MIN_STOCK_PRICE < last_close < MAX_STOCK_PRICE):
        return []

    df_enriched = _enrich_once(df_raw)
    if df_enriched is None:
        return []

    # Check avg volume from enriched data
    avg_vol = df_enriched["avg_volume_20"].values[-1] if "avg_volume_20" in df_enriched.columns else 0
    if pd.isna(avg_vol) or avg_vol < 100_000:
        return []

    all_results = []
    for tdate in target_dates:
        candidates = _score_symbol_for_date(df_enriched, tdate, trader)
        for c in candidates:
            c["date"] = tdate
            c["symbol"] = symbol
            all_results.append(c)

    return all_results


def phase1_score_and_rank(
    duckdb_path: str,
    target_dates: List[str],
    top_n: int,
    n_workers: int,
    output_path: str,
) -> pd.DataFrame:
    """
    Phase 1: Score all symbols across all target dates, rank, and save top-N per date.

    Parallelizes by symbol — each worker loads one symbol's full history,
    enriches indicators once, then scores across all dates.
    """
    con = _duckdb_ro(duckdb_path)
    symbols = _get_all_symbols_ro(con)

    # Calculate earliest date we need data from (earliest target date - lookback buffer)
    all_spy_dates = _get_symbol_dates_ro(con, "SPY")
    all_spy_dates = sorted(all_spy_dates)
    earliest_target = min(target_dates)
    # Find the date LOOKBACK_BUFFER trading days before earliest target
    try:
        idx = all_spy_dates.index(earliest_target)
        earliest_load_idx = max(0, idx - LOOKBACK_BUFFER)
        earliest_load_date = all_spy_dates[earliest_load_idx]
    except ValueError:
        earliest_load_date = earliest_target  # fallback
    con.close()

    log.info(
        "Phase 1: scoring %d symbols across %d dates with %d workers (data from %s)",
        len(symbols), len(target_dates), n_workers, earliest_load_date,
    )

    work_items = [(sym, target_dates, earliest_load_date) for sym in symbols]

    all_candidates = []
    t0 = time.time()
    completed = 0

    with ProcessPoolExecutor(
        max_workers=n_workers,
        initializer=_init_scoring_worker,
        initargs=(duckdb_path,),
    ) as pool:
        futures = {pool.submit(_score_symbol_across_dates, item): item[0] for item in work_items}
        for future in as_completed(futures):
            completed += 1
            if completed % 100 == 0:
                elapsed = time.time() - t0
                rate = completed / elapsed
                eta = (len(symbols) - completed) / rate if rate > 0 else 0
                log.info(
                    "  %d/%d symbols done (%.1f sym/s, ETA %.0f min)",
                    completed, len(symbols), rate, eta / 60,
                )
            try:
                results = future.result()
                all_candidates.extend(results)
            except Exception as e:
                sym = futures[future]
                log.warning("Error scoring %s: %s", sym, e)

    elapsed = time.time() - t0
    log.info("Phase 1 scoring complete: %d candidates in %.1f min", len(all_candidates), elapsed / 60)

    if not all_candidates:
        log.error("No candidates produced — check data availability")
        return pd.DataFrame()

    df = pd.DataFrame(all_candidates)

    # --- Ranking mode ---
    # per_strategy=True: take top N from EACH strategy (total = N * num_strategies)
    # per_strategy=False: deduplicate by symbol, combined ranking (original behavior)
    per_strategy = os.environ.get("PER_STRATEGY", "1") == "1"

    if per_strategy:
        # Rank within each (date, strategy), take top N from each
        frames = []
        for strat in df["strategy"].unique():
            strat_df = df[df["strategy"] == strat].copy()
            strat_df["rank"] = strat_df.groupby("date")["score"].rank(
                ascending=False, method="first"
            ).astype(int)
            frames.append(strat_df[strat_df["rank"] <= top_n])
        df_top = pd.concat(frames, ignore_index=True)
        df_top = df_top.sort_values(["date", "strategy", "rank"])
        log.info(
            "Per-strategy ranking: %s",
            {s: len(df_top[df_top['strategy'] == s]) for s in df_top['strategy'].unique()},
        )
    else:
        # Original: deduplicate by symbol, combined ranking
        df = df.sort_values("score", ascending=False).drop_duplicates(
            subset=["date", "symbol"], keep="first"
        )
        df["rank"] = df.groupby("date")["score"].rank(ascending=False, method="first").astype(int)
        df_top = df[df["rank"] <= top_n].copy()
        df_top = df_top.sort_values(["date", "rank"])

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df_top.to_csv(output_path, index=False)
    log.info("Phase 1 saved %d rows to %s", len(df_top), output_path)

    return df_top


# =========================================================================
# Phase 2 — Trade Simulation
# =========================================================================

def _classify_market_regime(duckdb_path: str, target_dates: List[str]) -> Dict[str, str]:
    """
    Classify each target date as 'bullish' or 'bearish' based on SPY's
    position relative to its 50-day simple moving average.

    Returns dict: {date_str: 'bullish'|'bearish'}
    """
    con = _duckdb_ro(duckdb_path)
    spy = con.execute(
        "SELECT date, close FROM ohlcv WHERE symbol = 'SPY' ORDER BY date"
    ).fetchdf()
    con.close()

    if spy.empty:
        return {d: "unknown" for d in target_dates}

    spy["date"] = spy["date"].astype(str)
    spy["sma_50"] = spy["close"].rolling(50).mean()

    regime = {}
    for d in target_dates:
        row = spy[spy["date"] <= d].tail(1)
        if row.empty or pd.isna(row["sma_50"].values[0]):
            regime[d] = "unknown"
        elif row["close"].values[0] > row["sma_50"].values[0]:
            regime[d] = "bullish"
        else:
            regime[d] = "bearish"

    return regime


def phase2_simulate(
    scores_df: pd.DataFrame,
    duckdb_path: str,
    max_forward_days: int = 10,
    output_path: str = "",
) -> pd.DataFrame:
    """
    Phase 2: For each (date, symbol) in scores, load forward OHLCV and record
    daily highs/lows for simulation.

    Entry = next trading day's open price.
    Adds market regime classification per date.
    """
    con = _duckdb_ro(duckdb_path)

    # Classify market regime for all dates
    all_dates = sorted(scores_df["date"].unique().tolist())
    regime_map = _classify_market_regime(duckdb_path, all_dates)
    bull_count = sum(1 for v in regime_map.values() if v == "bullish")
    bear_count = sum(1 for v in regime_map.values() if v == "bearish")
    log.info("Market regime: %d bullish dates, %d bearish dates", bull_count, bear_count)

    log.info("Phase 2: simulating %d trades", len(scores_df))

    rows = []
    missing = 0

    for _, row in scores_df.iterrows():
        symbol = row["symbol"]
        pred_date = row["date"]

        # Load forward data: all data after prediction date
        df_all = _load_symbol_ro(con, symbol)
        if df_all is None:
            missing += 1
            continue

        # Get rows strictly after pred_date
        df_fwd = df_all[df_all["date"] > pred_date].head(max_forward_days + 1)
        if len(df_fwd) < 2:
            missing += 1
            continue

        entry_price = df_fwd.iloc[0]["open"]
        if entry_price <= 0 or pd.isna(entry_price):
            missing += 1
            continue

        sim_row = {
            "date": pred_date,
            "symbol": symbol,
            "strategy": row["strategy"],
            "rank": row["rank"],
            "score": row["score"],
            "regime": regime_map.get(pred_date, "unknown"),
            "setup_entry": row.get("entry_price", 0),
            "setup_stop": row.get("stop_loss", 0),
            "setup_target": row.get("take_profit", 0),
            "entry_price": entry_price,
            "entry_date": df_fwd.iloc[0]["date"],
        }

        # Record daily highs, lows, closes for up to max_forward_days
        # Day 1 = the entry day (we already used its open for entry)
        max_adverse = 0.0  # Most negative % move from entry
        for i in range(min(max_forward_days, len(df_fwd))):
            day_num = i + 1
            day_row = df_fwd.iloc[i]
            day_high_pct = (day_row["high"] - entry_price) / entry_price
            day_low_pct = (day_row["low"] - entry_price) / entry_price
            day_close_pct = (day_row["close"] - entry_price) / entry_price

            sim_row[f"d{day_num}_high_pct"] = round(day_high_pct, 6)
            sim_row[f"d{day_num}_low_pct"] = round(day_low_pct, 6)
            sim_row[f"d{day_num}_close_pct"] = round(day_close_pct, 6)

            if day_low_pct < max_adverse:
                max_adverse = day_low_pct

        sim_row["max_adverse_excursion"] = round(max_adverse, 6)
        sim_row["forward_days_available"] = min(max_forward_days, len(df_fwd))
        rows.append(sim_row)

    con.close()

    if missing:
        log.warning("Phase 2: %d trades had insufficient forward data", missing)

    df_sims = pd.DataFrame(rows)
    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        df_sims.to_csv(output_path, index=False)
        log.info("Phase 2 saved %d simulations to %s", len(df_sims), output_path)

    return df_sims


# =========================================================================
# Phase 3 — Analysis
# =========================================================================

def _simulate_trade(sim_row: dict, target_pct: float, stop_pct: float, hold_days: int) -> dict:
    """
    Simulate one trade with given parameters.

    Returns dict with outcome, pnl_pct, exit_day, and whether this was a
    winner that would have been stopped out at various levels.
    """
    target_frac = target_pct / 100.0
    stop_frac = stop_pct / 100.0

    for day in range(1, hold_days + 1):
        low_key = f"d{day}_low_pct"
        high_key = f"d{day}_high_pct"
        close_key = f"d{day}_close_pct"

        if low_key not in sim_row:
            # Ran out of forward data
            last_close_key = f"d{day - 1}_close_pct" if day > 1 else None
            pnl = sim_row.get(last_close_key, 0.0) if last_close_key else 0.0
            return {"outcome": "timeout", "pnl_pct": pnl, "exit_day": day - 1}

        day_low = sim_row[low_key]
        day_high = sim_row[high_key]

        # Check stop FIRST (conservative)
        if day_low <= -stop_frac:
            return {"outcome": "loss", "pnl_pct": -stop_pct, "exit_day": day}

        # Then check target
        if day_high >= target_frac:
            return {"outcome": "win", "pnl_pct": target_pct, "exit_day": day}

    # Timeout — exit at close of last hold day
    last_close_key = f"d{hold_days}_close_pct"
    pnl = sim_row.get(last_close_key, 0.0) * 100.0
    return {"outcome": "timeout", "pnl_pct": pnl, "exit_day": hold_days}


def _simulate_tiered_trade(sim_row: dict, t1_pct: float, t2_pct: float, stop_pct: float, hold_days: int) -> dict:
    """
    Simulate a tiered exit trade:
    - Buy full position at entry
    - Sell half at T1 (t1_pct)
    - Raise stop to breakeven after T1 hit
    - Sell remaining half at T2 (t2_pct) or breakeven stop
    """
    t1_frac = t1_pct / 100.0
    t2_frac = t2_pct / 100.0
    stop_frac = stop_pct / 100.0

    t1_hit = False
    t1_day = 0

    for day in range(1, hold_days + 1):
        low_key = f"d{day}_low_pct"
        high_key = f"d{day}_high_pct"
        close_key = f"d{day}_close_pct"

        if low_key not in sim_row:
            break

        day_low = sim_row[low_key]
        day_high = sim_row[high_key]

        if not t1_hit:
            # Before T1: check original stop first
            if day_low <= -stop_frac:
                return {
                    "t1_hit": False, "t1_day": 0,
                    "t2_hit": False, "t2_day": 0,
                    "outcome": "full_loss",
                    "pnl_pct": -stop_pct,
                    "exit_day": day,
                }
            if day_high >= t1_frac:
                t1_hit = True
                t1_day = day
                # Check if T2 also hit on the same day
                if day_high >= t2_frac:
                    return {
                        "t1_hit": True, "t1_day": day,
                        "t2_hit": True, "t2_day": day,
                        "outcome": "full_win",
                        "pnl_pct": (t1_pct + t2_pct) / 2.0,
                        "exit_day": day,
                    }
        else:
            # After T1: stop is now breakeven (0%)
            if day_low <= 0:
                # Stopped out at breakeven on T2 half
                return {
                    "t1_hit": True, "t1_day": t1_day,
                    "t2_hit": False, "t2_day": 0,
                    "outcome": "t1_only",
                    "pnl_pct": t1_pct / 2.0,  # Half position won T1, half at breakeven
                    "exit_day": day,
                }
            if day_high >= t2_frac:
                return {
                    "t1_hit": True, "t1_day": t1_day,
                    "t2_hit": True, "t2_day": day,
                    "outcome": "full_win",
                    "pnl_pct": (t1_pct + t2_pct) / 2.0,
                    "exit_day": day,
                }

    # Timeout
    last_day = min(hold_days, sim_row.get("forward_days_available", hold_days))
    last_close_key = f"d{last_day}_close_pct"
    last_close_pct = sim_row.get(last_close_key, 0.0) * 100.0

    if t1_hit:
        # T1 half won, T2 half exits at last close
        pnl = (t1_pct + last_close_pct) / 2.0
    else:
        pnl = last_close_pct

    return {
        "t1_hit": t1_hit, "t1_day": t1_day,
        "t2_hit": False, "t2_day": 0,
        "outcome": "timeout",
        "pnl_pct": pnl,
        "exit_day": last_day,
    }


def phase3_analyze_all(
    sims_df: pd.DataFrame,
    slippage_pct: float = 0.0,
    output_dir: str = "",
) -> None:
    """
    Run Phase 3 analysis for ALL data, then per-strategy, then per-regime.
    """
    if sims_df.empty:
        log.error("No simulation data to analyze")
        return

    # --- Overall ---
    log.info("=== Analyzing: ALL trades ===")
    phase3_analyze(sims_df.copy(), slippage_pct, output_dir, segment_label="ALL")

    # --- Per strategy ---
    if "strategy" in sims_df.columns:
        for strat in sorted(sims_df["strategy"].unique()):
            subset = sims_df[sims_df["strategy"] == strat]
            if len(subset) < 20:
                continue
            strat_dir = os.path.join(output_dir, f"strategy_{strat}")
            os.makedirs(strat_dir, exist_ok=True)
            log.info("=== Analyzing: strategy=%s (%d trades) ===", strat, len(subset))
            phase3_analyze(subset.copy(), slippage_pct, strat_dir, segment_label=f"Strategy: {strat}")

    # --- Per regime ---
    if "regime" in sims_df.columns:
        for regime in sorted(sims_df["regime"].unique()):
            subset = sims_df[sims_df["regime"] == regime]
            if len(subset) < 20:
                continue
            regime_dir = os.path.join(output_dir, f"regime_{regime}")
            os.makedirs(regime_dir, exist_ok=True)
            log.info("=== Analyzing: regime=%s (%d trades) ===", regime, len(subset))
            phase3_analyze(subset.copy(), slippage_pct, regime_dir, segment_label=f"Regime: {regime}")

    # --- Per strategy + regime combo ---
    if "strategy" in sims_df.columns and "regime" in sims_df.columns:
        for strat in sorted(sims_df["strategy"].unique()):
            for regime in sorted(sims_df["regime"].unique()):
                subset = sims_df[(sims_df["strategy"] == strat) & (sims_df["regime"] == regime)]
                if len(subset) < 20:
                    continue
                combo_dir = os.path.join(output_dir, f"{strat}_{regime}")
                os.makedirs(combo_dir, exist_ok=True)
                log.info("=== Analyzing: %s + %s (%d trades) ===", strat, regime, len(subset))
                phase3_analyze(
                    subset.copy(), slippage_pct, combo_dir,
                    segment_label=f"{strat} / {regime}",
                )


def phase3_analyze(
    sims_df: pd.DataFrame,
    slippage_pct: float = 0.0,
    output_dir: str = "",
    segment_label: str = "ALL",
) -> None:
    """
    Phase 3: Run parameter sweep and tiered exit analysis for one segment.

    Outputs:
    - parameter_sweep.csv: win rate + EV for every (target, stop, hold, top_n) combo
    - tiered_exit.csv: T1/T2 analysis
    - stop_analysis.csv: for each stop level, winners stopped out vs losers caught
    - Console summary of key findings
    """
    if sims_df.empty:
        log.error("No simulation data to analyze")
        return

    # Apply slippage: adjust entry by slippage_pct, recalculate daily pcts
    if slippage_pct > 0:
        log.info("Applying %.2f%% slippage to entry prices", slippage_pct * 100)
        slip_frac = slippage_pct
        for col in sims_df.columns:
            if col.endswith("_high_pct") or col.endswith("_low_pct") or col.endswith("_close_pct"):
                # Adjust: new_pct = (1 + old_pct) / (1 + slip) - 1
                sims_df[col] = (1 + sims_df[col]) / (1 + slip_frac) - 1
        sims_df["max_adverse_excursion"] = (1 + sims_df["max_adverse_excursion"]) / (1 + slip_frac) - 1

    sim_dicts = sims_df.to_dict("records")

    # --- Parameter Sweep ---
    log.info(
        "Parameter sweep: %d targets x %d stops x %d hold_days x %d top_n = %d combos",
        len(TARGET_PCTS), len(STOP_PCTS), len(HOLD_DAYS_RANGE), len(TOP_N_BUCKETS),
        len(TARGET_PCTS) * len(STOP_PCTS) * len(HOLD_DAYS_RANGE) * len(TOP_N_BUCKETS),
    )

    sweep_rows = []
    for target_pct in TARGET_PCTS:
        for stop_pct in STOP_PCTS:
            for hold_days in HOLD_DAYS_RANGE:
                for top_n in TOP_N_BUCKETS:
                    eligible = [s for s in sim_dicts if s["rank"] <= top_n]
                    if not eligible:
                        continue

                    wins = losses = timeouts = 0
                    total_pnl = 0.0
                    win_pnls = []
                    loss_pnls = []

                    for sim in eligible:
                        result = _simulate_trade(sim, target_pct, stop_pct, hold_days)
                        if result["outcome"] == "win":
                            wins += 1
                            win_pnls.append(result["pnl_pct"])
                        elif result["outcome"] == "loss":
                            losses += 1
                            loss_pnls.append(result["pnl_pct"])
                        else:
                            timeouts += 1
                            # Count timeout P&L as a loss if negative, win if positive
                            if result["pnl_pct"] >= 0:
                                win_pnls.append(result["pnl_pct"])
                            else:
                                loss_pnls.append(result["pnl_pct"])
                        total_pnl += result["pnl_pct"]

                    total = wins + losses + timeouts
                    win_rate = wins / total if total > 0 else 0
                    avg_win = np.mean(win_pnls) if win_pnls else 0
                    avg_loss = np.mean(loss_pnls) if loss_pnls else 0
                    expected_value = total_pnl / total if total > 0 else 0

                    sweep_rows.append({
                        "target_pct": target_pct,
                        "stop_pct": stop_pct,
                        "hold_days": hold_days,
                        "top_n": top_n,
                        "total_trades": total,
                        "wins": wins,
                        "losses": losses,
                        "timeouts": timeouts,
                        "win_rate": round(win_rate, 4),
                        "avg_win_pct": round(avg_win, 4),
                        "avg_loss_pct": round(avg_loss, 4),
                        "expected_value_pct": round(expected_value, 4),
                        "total_pnl_pct": round(total_pnl, 2),
                    })

    sweep_df = pd.DataFrame(sweep_rows)
    if output_dir:
        path = os.path.join(output_dir, "parameter_sweep.csv")
        sweep_df.to_csv(path, index=False)
        log.info("Parameter sweep saved to %s", path)

    # --- Stop Analysis (winners stopped out vs losers caught) ---
    log.info("Running stop analysis...")
    stop_rows = []
    for stop_pct in STOP_PCTS:
        stop_frac = stop_pct / 100.0
        for top_n in TOP_N_BUCKETS:
            eligible = [s for s in sim_dicts if s["rank"] <= top_n]

            # A "natural winner" at 2%/5d for this analysis
            ref_target, ref_hold = 2.0, 5
            natural_winners = set()
            natural_losers = set()

            for i, sim in enumerate(eligible):
                # Would this trade have hit 2% in 5 days without any stop?
                result_no_stop = _simulate_trade(sim, ref_target, 99.0, ref_hold)
                if result_no_stop["outcome"] == "win":
                    natural_winners.add(i)
                else:
                    natural_losers.add(i)

            # Now check how many of each group the stop catches
            winners_stopped = 0
            losers_stopped = 0
            for i, sim in enumerate(eligible):
                mae = sim.get("max_adverse_excursion", 0)
                # Was this trade stopped out?
                stopped = False
                for day in range(1, ref_hold + 1):
                    low_key = f"d{day}_low_pct"
                    if low_key in sim and sim[low_key] <= -stop_frac:
                        stopped = True
                        break

                if stopped:
                    if i in natural_winners:
                        winners_stopped += 1
                    elif i in natural_losers:
                        losers_stopped += 1

            stop_rows.append({
                "stop_pct": stop_pct,
                "top_n": top_n,
                "ref_target_pct": ref_target,
                "ref_hold_days": ref_hold,
                "natural_winners": len(natural_winners),
                "natural_losers": len(natural_losers),
                "winners_stopped_out": winners_stopped,
                "losers_caught": losers_stopped,
                "winner_preservation_rate": round(
                    1 - winners_stopped / len(natural_winners), 4
                ) if natural_winners else 0,
                "loser_catch_rate": round(
                    losers_stopped / len(natural_losers), 4
                ) if natural_losers else 0,
            })

    stop_df = pd.DataFrame(stop_rows)
    if output_dir:
        path = os.path.join(output_dir, "stop_analysis.csv")
        stop_df.to_csv(path, index=False)
        log.info("Stop analysis saved to %s", path)

    # --- Tiered Exit Analysis ---
    log.info("Running tiered exit analysis...")
    tiered_rows = []
    for stop_pct in STOP_PCTS:
        for hold_days in HOLD_DAYS_RANGE:
            for top_n in TOP_N_BUCKETS:
                eligible = [s for s in sim_dicts if s["rank"] <= top_n]
                if not eligible:
                    continue

                outcomes = defaultdict(int)
                pnls = []
                t2_days = []

                for sim in eligible:
                    result = _simulate_tiered_trade(sim, 1.0, 2.0, stop_pct, hold_days)
                    outcomes[result["outcome"]] += 1
                    pnls.append(result["pnl_pct"])
                    if result.get("t2_hit"):
                        t2_days.append(result["t2_day"])

                total = len(eligible)
                tiered_rows.append({
                    "stop_pct": stop_pct,
                    "hold_days": hold_days,
                    "top_n": top_n,
                    "total_trades": total,
                    "full_win": outcomes["full_win"],
                    "t1_only": outcomes["t1_only"],
                    "full_loss": outcomes["full_loss"],
                    "timeout": outcomes["timeout"],
                    "full_win_rate": round(outcomes["full_win"] / total, 4) if total else 0,
                    "t1_hit_rate": round(
                        (outcomes["full_win"] + outcomes["t1_only"]) / total, 4
                    ) if total else 0,
                    "avg_pnl_pct": round(np.mean(pnls), 4) if pnls else 0,
                    "expected_value_pct": round(sum(pnls) / total, 4) if total else 0,
                    "avg_days_to_t2": round(np.mean(t2_days), 1) if t2_days else 0,
                    "median_days_to_t2": round(np.median(t2_days), 1) if t2_days else 0,
                })

    tiered_df = pd.DataFrame(tiered_rows)
    if output_dir:
        path = os.path.join(output_dir, "tiered_exit.csv")
        tiered_df.to_csv(path, index=False)
        log.info("Tiered exit analysis saved to %s", path)

    # --- Console Summary ---
    _print_summary(sweep_df, stop_df, tiered_df, slippage_pct, segment_label)


def _print_summary(sweep_df, stop_df, tiered_df, slippage_pct, segment_label="ALL"):
    """Print human-readable summary of key findings."""
    print("\n" + "=" * 80)
    print(f"  ASSUMPTION TEST RESULTS  [{segment_label}]  (slippage: {slippage_pct * 100:.1f}%)")
    print("=" * 80)

    # --- Test 1: 2% target, 5 day hold ---
    print("\n--- TEST 1: 2% target / 5-day hold / top 20 ---")
    t1 = sweep_df[
        (sweep_df["target_pct"] == 2.0)
        & (sweep_df["hold_days"] == 5)
        & (sweep_df["top_n"] == 20)
    ].sort_values("expected_value_pct", ascending=False)
    if not t1.empty:
        best = t1.iloc[0]
        print(f"  Best stop: {best['stop_pct']}%")
        print(f"  Win rate: {best['win_rate']:.1%}  |  Avg win: {best['avg_win_pct']:.2f}%  |  Avg loss: {best['avg_loss_pct']:.2f}%")
        print(f"  Expected value per trade: {best['expected_value_pct']:.3f}%")
        print(f"  Total trades tested: {int(best['total_trades'])}")

    # --- Test 2: 1% target, 2 day hold ---
    print("\n--- TEST 2: 1% target / 2-day hold / top 20 ---")
    t2 = sweep_df[
        (sweep_df["target_pct"] == 1.0)
        & (sweep_df["hold_days"] == 2)
        & (sweep_df["top_n"] == 20)
    ].sort_values("expected_value_pct", ascending=False)
    if not t2.empty:
        best = t2.iloc[0]
        print(f"  Best stop: {best['stop_pct']}%")
        print(f"  Win rate: {best['win_rate']:.1%}  |  Avg win: {best['avg_win_pct']:.2f}%  |  Avg loss: {best['avg_loss_pct']:.2f}%")
        print(f"  Expected value per trade: {best['expected_value_pct']:.3f}%")

    # --- Test 3: Tiered exit ---
    print("\n--- TEST 3: Tiered exit (T1=1%, T2=2%) / top 20 ---")
    t3 = tiered_df[tiered_df["top_n"] == 20].sort_values("expected_value_pct", ascending=False)
    if not t3.empty:
        best = t3.iloc[0]
        print(f"  Best combo: stop={best['stop_pct']}%, hold={int(best['hold_days'])}d")
        print(f"  Full win rate (both T1+T2): {best['full_win_rate']:.1%}")
        print(f"  T1 hit rate: {best['t1_hit_rate']:.1%}")
        print(f"  Avg P&L per trade: {best['avg_pnl_pct']:.3f}%")
        print(f"  Expected value per trade: {best['expected_value_pct']:.3f}%")
        if best["avg_days_to_t2"] > 0:
            print(f"  Avg days to T2: {best['avg_days_to_t2']:.1f}")

    # --- Overall best parameters ---
    print("\n--- OPTIMAL PARAMETERS (highest EV, top 20) ---")
    top20 = sweep_df[sweep_df["top_n"] == 20]
    if not top20.empty:
        best_ev = top20.sort_values("expected_value_pct", ascending=False).iloc[0]
        print(f"  Target: {best_ev['target_pct']}%  |  Stop: {best_ev['stop_pct']}%  |  Hold: {int(best_ev['hold_days'])}d")
        print(f"  Win rate: {best_ev['win_rate']:.1%}  |  EV: {best_ev['expected_value_pct']:.3f}%")
        print(f"  Avg win: {best_ev['avg_win_pct']:.2f}%  |  Avg loss: {best_ev['avg_loss_pct']:.2f}%")

    # --- Top N comparison ---
    print("\n--- TOP-N COMPARISON (2% target, 5d hold, best stop per bucket) ---")
    for top_n in TOP_N_BUCKETS:
        subset = sweep_df[
            (sweep_df["target_pct"] == 2.0)
            & (sweep_df["hold_days"] == 5)
            & (sweep_df["top_n"] == top_n)
        ].sort_values("expected_value_pct", ascending=False)
        if not subset.empty:
            best = subset.iloc[0]
            print(f"  Top {top_n:2d}: win={best['win_rate']:.1%}  EV={best['expected_value_pct']:.3f}%  stop={best['stop_pct']}%")

    # --- Stop tradeoff ---
    print("\n--- STOP TRADEOFF (2% target, 5d, top 20) ---")
    s20 = stop_df[stop_df["top_n"] == 20]
    if not s20.empty:
        print(f"  {'Stop':>6s}  {'Winners Kept':>13s}  {'Losers Caught':>14s}  {'Preservation':>13s}  {'Catch Rate':>11s}")
        for _, r in s20.iterrows():
            nw = int(r['natural_winners'])
            nl = int(r['natural_losers'])
            ws = int(r['winners_stopped_out'])
            lc = int(r['losers_caught'])
            print(
                f"  {r['stop_pct']:5.1f}%  "
                f"{nw - ws:>6d}/{nw:<6d}  "
                f"{lc:>6d}/{nl:<6d}  "
                f"{r['winner_preservation_rate']:>12.1%}  "
                f"{r['loser_catch_rate']:>10.1%}"
            )

    print("\n" + "=" * 80)


# =========================================================================
# CLI
# =========================================================================

def main():
    parser = argparse.ArgumentParser(description="Assumption Tester — validate trading assumptions")
    parser.add_argument("--dates", type=int, default=100, help="Number of trading dates to test (default: 100)")
    parser.add_argument("--top-n", type=int, default=20, help="Top N symbols to track per date (default: 20)")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers (default: 4)")
    parser.add_argument("--per-strategy", action="store_true", default=True, help="Rank per strategy (default: True)")
    parser.add_argument("--combined", action="store_true", help="Use combined ranking (original behavior)")
    parser.add_argument("--phase1-only", action="store_true", help="Run only Phase 1 (scoring)")
    parser.add_argument("--skip-phase1", action="store_true", help="Skip Phase 1, use cached scores")
    parser.add_argument("--slippage", type=float, default=0.0, help="Entry slippage as decimal (e.g. 0.002 for 0.2%%)")
    parser.add_argument("--duckdb", type=str, default=DUCKDB_PATH, help="Path to DuckDB file")
    parser.add_argument("--output-dir", type=str, default=OUTPUT_DIR, help="Output directory for CSV files")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    # Set per-strategy mode via env var (read by phase1_score_and_rank)
    if args.combined:
        os.environ["PER_STRATEGY"] = "0"
    else:
        os.environ["PER_STRATEGY"] = "1"

    scores_path = os.path.join(args.output_dir, "phase1_scores.csv")
    sims_path = os.path.join(args.output_dir, "trade_simulations.csv")

    # --- Phase 1 ---
    if not args.skip_phase1:
        target_dates = get_trading_dates(args.duckdb, args.dates)

        log.info("Target dates: %s to %s (%d dates)", target_dates[0], target_dates[-1], len(target_dates))

        scores_df = phase1_score_and_rank(
            duckdb_path=args.duckdb,
            target_dates=target_dates,
            top_n=args.top_n,
            n_workers=args.workers,
            output_path=scores_path,
        )

        if args.phase1_only:
            log.info("Phase 1 complete. Exiting (--phase1-only).")
            return
    else:
        if not os.path.exists(scores_path):
            log.error("No cached scores at %s — run Phase 1 first", scores_path)
            return
        scores_df = pd.read_csv(scores_path)
        log.info("Loaded %d cached scores from %s", len(scores_df), scores_path)

    # --- Phase 2 ---
    sims_df = phase2_simulate(
        scores_df=scores_df,
        duckdb_path=args.duckdb,
        max_forward_days=10,
        output_path=sims_path,
    )

    # --- Phase 3 ---
    phase3_analyze_all(
        sims_df=sims_df,
        slippage_pct=args.slippage,
        output_dir=args.output_dir,
    )

    # --- Re-run with slippage if initial run was at 0% ---
    if args.slippage == 0 and os.path.exists(sims_path) and os.path.getsize(sims_path) > 0:
        log.info("Re-running Phase 3 with 0.2%% slippage for comparison...")
        sims_df_slip = pd.read_csv(sims_path)
        slip_output = os.path.join(args.output_dir, "with_slippage")
        os.makedirs(slip_output, exist_ok=True)
        phase3_analyze_all(
            sims_df=sims_df_slip,
            slippage_pct=0.002,
            output_dir=slip_output,
        )


if __name__ == "__main__":
    main()
