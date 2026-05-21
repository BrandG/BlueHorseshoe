"""generate_baseline_ledger_lean.py — Lean Phase 1 driver.

Bypasses ``SwingTrader.__init__``, ``MarketRegime``, ``MLInference``,
``ScoreManager``, ``swing_predict``, and the production ``Backtester``
entirely. Reads OHLCV directly from DuckDB, computes indicators once
per symbol up-front, scores each symbol per date via
``TechnicalAnalyzer.calculate_score_for_strategy`` (DB-free static),
builds T1/T2/stop bracket via ``SwingTrader.calculate_{baseline,
mean_reversion}_setup`` (pure functions of ``df``), and simulates the
forward bracket inline.

Skips by design:
  - MarketRegime advisory + breadth check (per CLAUDE.md, advisory only)
  - ML probability + stop-loss + profit-target overlays (separate question)
  - Relative-strength bonus, score acceleration, intraday context bonus
  - News/sentiment lookups
  - ScoreManager persistence

What this captures vs production:
  - Same scoring weights (loaded from src/weights.json via TechnicalAnalyzer)
  - Same entry / stop / target formulas (calculate_baseline_setup etc.)
  - Same realistic/RR/price-band filters
  - Same split bracket shape (T1 = entry × 1.02, T2 = setup target,
    single stop = setup stop), 50/50 tranche
  - Causal indicator computation — no look-ahead

KNOWN simulator vs production drift (same as the dropped Backtester path):
  After T1 fills, T2 stop is moved to entry × 0.98 in this simulator,
  but production (post-2026-05-21 fix) moves T2 stop to entry exactly.
  This makes the baseline ledger conservative about weekend downside.

See docs/planning/WEEKEND_FLATTEN_EQUITIES_v1.md for the study design.
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.analysis.strategy_registry import get_strategy
from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer
from bluehorseshoe.core.config import REPO_ROOT
from bluehorseshoe.data.historical_data import get_technical_indicators
from bluehorseshoe.data.duckdb_store import DuckDBStore
from bluehorseshoe.core.config import get_settings


logger = logging.getLogger(__name__)


LEDGER_COLUMNS = [
    "trade_id", "strategy", "symbol",
    "prediction_date", "entry_date", "entry_price",
    "stop_price", "t1_target", "t2_target",
    "t1_exit_price", "t1_status",
    "t2_exit_price", "t2_status",
    "t1_pnl_pct", "t2_pnl_pct", "blended_pnl_pct",
    "days_held", "exit_date",
    "spans_weekends", "regime", "status", "score",
]


# ---------------------------------------------------------------------------
# Universe + dates
# ---------------------------------------------------------------------------

def filtered_universe(store: DuckDBStore, min_price, max_price, min_avg_vol,
                      min_bars, start, end) -> list[str]:
    con = store._con
    rows = con.execute(f"""
        SELECT symbol
        FROM ohlcv
        WHERE date BETWEEN '{start}' AND '{end}'
        GROUP BY symbol
        HAVING AVG(close) BETWEEN {min_price} AND {max_price}
           AND AVG(volume) > {min_avg_vol}
           AND COUNT(*) >= {min_bars}
        ORDER BY symbol
    """).fetchall()
    return [r[0] for r in rows]


def trading_days(start: str, end: str, interval_days: int) -> list[str]:
    s = pd.to_datetime(start)
    e = pd.to_datetime(end)
    days = []
    cur = s
    while cur <= e:
        if cur.weekday() < 5:
            days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=interval_days)
    return days


def classify_regime(entry_date: str) -> str:
    yr = int(entry_date[:4])
    if 2015 <= yr <= 2017: return "trend_2015_2017"
    if yr == 2018:         return "vol_2018"
    if yr == 2019:         return "trend_2019"
    if yr == 2020:         return "covid_2020"
    if yr == 2021:         return "trend_2021"
    if yr == 2022:         return "bear_2022"
    if 2023 <= yr <= 2026: return "trend_2023_2026"
    return "other"


def count_weekends_spanned(entry_date: Optional[str], exit_date: Optional[str]) -> int:
    if entry_date is None or exit_date is None:
        return 0
    s = pd.to_datetime(entry_date)
    e = pd.to_datetime(exit_date)
    if e <= s:
        return 0
    return sum(1 for d in pd.date_range(s, e, freq="D") if d.weekday() == 5)


# ---------------------------------------------------------------------------
# Indicator preload (parallel worker)
# ---------------------------------------------------------------------------

def _load_and_compute_indicators(symbol: str, duckdb_path: str) -> Optional[tuple[str, pd.DataFrame]]:
    """Worker: open DuckDB read-only, fetch one symbol's full OHLCV, compute indicators.

    Read-only mode lets multiple worker processes share the file concurrently
    (DuckDB blocks write locks but allows N concurrent readers).
    """
    try:
        store = DuckDBStore(duckdb_path, read_only=True)
        try:
            data = store.load_symbol_dict(symbol)
        finally:
            store.close()
        if not data or not data.get("days"):
            return None
        df = pd.DataFrame(data["days"])
        if len(df) < 220:  # need EMA-200 + buffer
            return None
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        # get_technical_indicators returns list of dicts; round-trip via DataFrame.
        df = pd.DataFrame(get_technical_indicators(df))
        df["date"] = pd.to_datetime(df["date"])
        return symbol, df
    except Exception as e:  # noqa: BLE001
        logger.warning("indicator preload failed for %s: %s", symbol, e)
        return None


# ---------------------------------------------------------------------------
# Scoring + setup (uses pure parts of SwingTrader)
# ---------------------------------------------------------------------------

# One SwingTrader stub per process — built lazily via __new__ to skip __init__.
_trader_stub: Optional[SwingTrader] = None


def _get_trader_stub() -> SwingTrader:
    global _trader_stub
    if _trader_stub is None:
        _trader_stub = SwingTrader.__new__(SwingTrader)
    return _trader_stub


def score_and_setup(df_slice: pd.DataFrame, strategy_name: str) -> Optional[dict]:
    """Score df_slice and compute the setup. Returns dict or None if not qualifying."""
    if len(df_slice) < 200:
        return None
    strategy_obj = get_strategy(strategy_name)
    components = TechnicalAnalyzer.calculate_score_for_strategy(
        df_slice, strategy_obj,
    )
    score = components.get("total", 0.0)
    if score <= 0:
        return None

    trader = _get_trader_stub()
    if strategy_name == "baseline":
        setup = trader.calculate_baseline_setup(df_slice, technical_score=score)
        min_rr = strategy_obj.min_rr_ratio
    elif strategy_name == "mean_reversion":
        setup = trader.calculate_mean_reversion_setup(df_slice)
        min_rr = strategy_obj.min_rr_ratio
    else:
        raise ValueError(f"unknown strategy: {strategy_name}")

    if not setup.get("is_realistic"):
        return None
    if setup.get("rr_ratio", 0) < min_rr:
        return None
    entry = setup["entry_price"]
    # Production constants — see analysis/constants.py
    if not (5.0 < entry < 500.0):
        return None
    return {
        "score": float(score),
        "entry_price": float(entry),
        "stop_loss": float(setup["stop_loss"]),
        "take_profit": float(setup["take_profit"]),
        "rr_ratio": float(setup["rr_ratio"]),
    }


# ---------------------------------------------------------------------------
# Forward bracket simulation
# ---------------------------------------------------------------------------

def simulate_split_bracket(forward_df: pd.DataFrame, entry_price: float,
                           stop_loss: float, t1_target: float,
                           t2_target: float) -> dict:
    """Simulate a 50/50 split bracket against forward OHLCV bars.

    Mirrors backtest.py:_check_split_entry semantics. Entry triggers when a
    bar's low touches entry_price (BUY LMT fill); gap-open below entry uses
    the open as actual fill. After T1 fills, T2 stop tightens to entry*0.98.
    """
    state = {
        "phase": "pre_entry",
        "actual_entry": None,
        "entry_idx": -1,
        "t1_status": "pending", "t1_exit_price": None, "t1_exit_idx": -1,
        "t2_status": "pending", "t2_exit_price": None, "t2_exit_idx": -1,
        "t2_stop": stop_loss,
    }
    rows = list(forward_df.itertuples(index=False))
    for i, row in enumerate(rows):
        h, l, o = float(row.high), float(row.low), float(row.open)

        if state["phase"] == "pre_entry":
            if l <= entry_price:
                state["phase"] = "both_active"
                state["entry_idx"] = i
                state["actual_entry"] = o if o < entry_price else entry_price
                # Immediate stop check on entry bar
                if l <= stop_loss:
                    stop_px = stop_loss if o >= stop_loss else o
                    state["t1_status"] = "stopped"; state["t1_exit_price"] = stop_px; state["t1_exit_idx"] = i
                    state["t2_status"] = "stopped"; state["t2_exit_price"] = stop_px; state["t2_exit_idx"] = i
                    state["phase"] = "complete"
                    break
                # Intraday T1
                if h >= t1_target:
                    t1_px = t1_target if o <= t1_target else o
                    state["t1_status"] = "profit"; state["t1_exit_price"] = t1_px; state["t1_exit_idx"] = i
                    state["phase"] = "t1_exited"
                    state["t2_stop"] = state["actual_entry"] * 0.98
                    if h >= t2_target:
                        t2_px = t2_target if o <= t2_target else o
                        state["t2_status"] = "profit"; state["t2_exit_price"] = t2_px; state["t2_exit_idx"] = i
                        state["phase"] = "complete"
                        break
            continue

        if state["phase"] == "both_active":
            if l <= stop_loss:
                stop_px = stop_loss if o >= stop_loss else o
                state["t1_status"] = "stopped"; state["t1_exit_price"] = stop_px; state["t1_exit_idx"] = i
                state["t2_status"] = "stopped"; state["t2_exit_price"] = stop_px; state["t2_exit_idx"] = i
                state["phase"] = "complete"
                break
            if h >= t1_target:
                t1_px = t1_target if o <= t1_target else o
                state["t1_status"] = "profit"; state["t1_exit_price"] = t1_px; state["t1_exit_idx"] = i
                state["phase"] = "t1_exited"
                state["t2_stop"] = state["actual_entry"] * 0.98
                if h >= t2_target:
                    t2_px = t2_target if o <= t2_target else o
                    state["t2_status"] = "profit"; state["t2_exit_price"] = t2_px; state["t2_exit_idx"] = i
                    state["phase"] = "complete"
                    break
            continue

        if state["phase"] == "t1_exited":
            t2_stop = state["t2_stop"]
            if l <= t2_stop:
                stop_px = t2_stop if o >= t2_stop else o
                state["t2_status"] = "stopped"; state["t2_exit_price"] = stop_px; state["t2_exit_idx"] = i
                state["phase"] = "complete"
                break
            if h >= t2_target:
                t2_px = t2_target if o <= t2_target else o
                state["t2_status"] = "profit"; state["t2_exit_price"] = t2_px; state["t2_exit_idx"] = i
                state["phase"] = "complete"
                break
            continue

    # Time-exit at last bar if still open
    if state["phase"] != "complete" and state["actual_entry"] is not None:
        last_close = float(rows[-1].close)
        last_idx = len(rows) - 1
        if state["t1_status"] == "pending":
            state["t1_status"] = "time_exit"; state["t1_exit_price"] = last_close; state["t1_exit_idx"] = last_idx
        if state["t2_status"] == "pending":
            state["t2_status"] = "time_exit"; state["t2_exit_price"] = last_close; state["t2_exit_idx"] = last_idx

    if state["actual_entry"] is None:
        return {"status": "no_entry"}

    entry = state["actual_entry"]
    t1_pnl = ((state["t1_exit_price"] / entry) - 1) * 100 if state["t1_exit_price"] else 0
    t2_pnl = ((state["t2_exit_price"] / entry) - 1) * 100 if state["t2_exit_price"] else 0
    blended = 0.5 * t1_pnl + 0.5 * t2_pnl

    if state["t1_status"] == "profit" and state["t2_status"] == "profit":
        overall = "split_full_profit"
    elif state["t1_status"] == "profit" and state["t2_status"] in ("stopped", "time_exit"):
        overall = "split_partial_profit"
    elif state["t1_status"] == "stopped" and state["t2_status"] == "stopped":
        overall = "stopped_out"
    elif blended > 0:
        overall = "closed_profit"
    else:
        overall = "closed_loss"

    exit_idx = max(state["t1_exit_idx"], state["t2_exit_idx"])
    return {
        "status": overall,
        "actual_entry": entry,
        "t1_status": state["t1_status"], "t1_exit_price": state["t1_exit_price"], "t1_exit_idx": state["t1_exit_idx"],
        "t2_status": state["t2_status"], "t2_exit_price": state["t2_exit_price"], "t2_exit_idx": state["t2_exit_idx"],
        "t1_pnl_pct": t1_pnl, "t2_pnl_pct": t2_pnl, "blended_pnl_pct": blended,
        "exit_idx": exit_idx,
        "days_held": exit_idx - state["entry_idx"] if state["entry_idx"] >= 0 else 0,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2015-01-01",
                        help="Start of the prediction-date window.")
    parser.add_argument("--end", default="2026-05-01",
                        help="End of the prediction-date window.")
    parser.add_argument("--universe-start", default="2015-01-01",
                        help="Universe-selection window start. Decouples filter "
                             "from prediction window so smoke tests don't shrink "
                             "the universe.")
    parser.add_argument("--universe-end", default="2026-05-01",
                        help="Universe-selection window end.")
    parser.add_argument("--interval-days", type=int, default=1)
    parser.add_argument("--strategies", nargs="+",
                        default=["baseline", "mean_reversion"],
                        choices=["baseline", "mean_reversion"])
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--hold-days", type=int, default=30)
    parser.add_argument("--symbol-limit", type=int, default=None)
    parser.add_argument("--max-workers", type=int, default=os.cpu_count())
    parser.add_argument("--output", default=str(
        Path(REPO_ROOT) / "research" / "weekend_flatten_equities_v1"
        / "baseline_ledger.csv"))
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)sZ %(levelname)s %(name)s: %(message)s",
    )

    settings = get_settings()
    # Open RO so worker processes can share the file concurrently.
    store = DuckDBStore(settings.duckdb_path, read_only=True)
    try:
        universe = filtered_universe(
            store, min_price=5, max_price=500, min_avg_vol=1_000_000,
            min_bars=500,
            start=args.universe_start, end=args.universe_end,
        )
    finally:
        store.close()
    if args.symbol_limit:
        universe = universe[:args.symbol_limit]
    dates = trading_days(args.start, args.end, args.interval_days)

    print(f"Universe: {len(universe)} symbols  |  Dates: {len(dates)}  "
          f"|  Strategies: {args.strategies}  |  Workers: {args.max_workers}",
          flush=True)

    # ---- Phase A: preload + compute indicators per symbol (parallel) -------
    print("Phase A: preloading indicators...", flush=True)
    t0 = time.time()
    cache: dict[str, pd.DataFrame] = {}
    with ProcessPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {pool.submit(_load_and_compute_indicators, sym,
                               settings.duckdb_path): sym for sym in universe}
        done = 0
        for fut in as_completed(futures):
            done += 1
            result = fut.result()
            if result is not None:
                sym, df = result
                cache[sym] = df
            if done % 100 == 0 or done == len(universe):
                print(f"  [{done}/{len(universe)}] cached={len(cache)} "
                      f"elapsed={(time.time()-t0)/60:.1f}m", flush=True)
    print(f"Phase A done: {len(cache)} symbols cached in {(time.time()-t0)/60:.1f}m",
          flush=True)

    # ---- Phase B: per-date scoring + simulation (single process) -----------
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Phase B: writing ledger to {output_path}", flush=True)
    total_written = 0
    t_b = time.time()
    with output_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LEDGER_COLUMNS)
        writer.writeheader()

        for di, pred_date in enumerate(dates):
            pred_ts = pd.to_datetime(pred_date)
            for strategy in args.strategies:
                # Score every cached symbol for this date.
                candidates = []
                for sym, full_df in cache.items():
                    df_slice = full_df[full_df["date"] <= pred_ts]
                    setup = score_and_setup(df_slice, strategy)
                    if setup is None:
                        continue
                    setup["symbol"] = sym
                    candidates.append(setup)
                candidates.sort(key=lambda c: c["score"], reverse=True)
                top = candidates[:args.top_n]

                # Simulate forward for each top candidate.
                for idx, cand in enumerate(top):
                    full_df = cache[cand["symbol"]]
                    forward = full_df[full_df["date"] > pred_ts].head(args.hold_days)
                    if forward.empty:
                        continue
                    t1_target = round(cand["entry_price"] * 1.02, 4)
                    t2_target = cand["take_profit"]
                    result = simulate_split_bracket(
                        forward, cand["entry_price"], cand["stop_loss"],
                        t1_target, t2_target,
                    )
                    if result.get("status") == "no_entry":
                        continue

                    exit_idx = result["exit_idx"]
                    entry_idx_in_forward = 0  # by definition: forward starts after pred_date
                    forward_dates = forward["date"].tolist()
                    entry_date = forward_dates[0].strftime("%Y-%m-%d") if len(forward_dates) else None
                    exit_date = (forward_dates[exit_idx].strftime("%Y-%m-%d")
                                 if 0 <= exit_idx < len(forward_dates) else None)

                    writer.writerow({
                        "trade_id": f"{pred_date}-{strategy}-{cand['symbol']}-{idx}",
                        "strategy": strategy,
                        "symbol": cand["symbol"],
                        "prediction_date": pred_date,
                        "entry_date": entry_date,
                        "entry_price": result["actual_entry"],
                        "stop_price": cand["stop_loss"],
                        "t1_target": t1_target,
                        "t2_target": t2_target,
                        "t1_exit_price": result["t1_exit_price"],
                        "t1_status": result["t1_status"],
                        "t2_exit_price": result["t2_exit_price"],
                        "t2_status": result["t2_status"],
                        "t1_pnl_pct": result["t1_pnl_pct"],
                        "t2_pnl_pct": result["t2_pnl_pct"],
                        "blended_pnl_pct": result["blended_pnl_pct"],
                        "days_held": result["days_held"],
                        "exit_date": exit_date,
                        "spans_weekends": count_weekends_spanned(entry_date, exit_date),
                        "regime": classify_regime(pred_date),
                        "status": result["status"],
                        "score": cand["score"],
                    })
                    total_written += 1

            if (di + 1) % 25 == 0 or di == len(dates) - 1:
                elapsed = time.time() - t_b
                rate = (di + 1) / max(elapsed, 0.001)
                eta = (len(dates) - di - 1) / max(rate, 0.001)
                print(f"  [{di+1}/{len(dates)}] {pred_date}  "
                      f"elapsed {elapsed/60:.1f}m  rate {rate:.2f} dates/s  "
                      f"eta {eta/60:.1f}m  written {total_written}",
                      flush=True)

    print(f"\nDone. Wrote {total_written} trades to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
