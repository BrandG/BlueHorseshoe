#!/usr/bin/env python3
"""Grid-search tuner for intraday context weights.

Replays historical scored predictions from MongoDB, recalculates
intraday context scores with different weight combinations using
OHLCV data from DuckDB, re-ranks candidates, and grades outcomes
against actual next-day price action.

Usage:
    ./run.sh python src/tune_intraday_weights.py
    ./run.sh python src/tune_intraday_weights.py --top 10 --dates 20
    ./run.sh python src/tune_intraday_weights.py --strategy baseline
"""

import argparse
import csv
import itertools
import logging
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from bluehorseshoe.data.duckdb_store import DuckDBStore
from bluehorseshoe.analysis.intraday_context import (
    detect_failed_breakout,
    close_strength,
    range_expansion,
    LOOKBACK_DAYS,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Grid parameters
# ---------------------------------------------------------------------------
GRID = {
    "failed_breakout_penalty": [0.0, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0],
    "failed_breakdown_bonus": [0.0],   # Zero impact — keep at 0
    "close_strength_weight": [0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0],
    "wide_range_reversal_penalty": [0.0],  # Zero impact — keep at 0
    "integration_weight": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0],
}

# For MR strategy, integration weight uses a separate constant
# but the Tier 1 formula is shared. We'll test both.

# ---------------------------------------------------------------------------
# Trade grading
# ---------------------------------------------------------------------------
HOLD_DAYS = 3  # Max days to hold


@dataclass
class TradeOutcome:
    symbol: str
    date: str
    strategy: str
    score: float
    entry_price: float
    stop_loss: float
    take_profit: float
    exit_price: float
    status: str  # "win", "loss", "timeout"
    pnl_pct: float
    ctx_score: float
    ctx_bonus: float


def grade_trade(
    symbol: str,
    date: str,
    strategy: str,
    score: float,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    ctx_score: float,
    ctx_bonus: float,
    future_bars: pd.DataFrame,
) -> Optional[TradeOutcome]:
    """Grade a single trade against future OHLCV bars.

    Assumes entry at next day's open. Checks if stop or target hit
    within HOLD_DAYS bars.
    """
    if future_bars is None or len(future_bars) < 1:
        return None

    # Entry at first future bar's open
    entry = float(future_bars.iloc[0]["open"])
    if entry <= 0 or math.isnan(entry):
        return None

    # Scale stop/target relative to actual entry vs predicted entry
    if entry_price > 0:
        ratio = entry / entry_price
        adj_stop = stop_loss * ratio
        adj_target = take_profit * ratio
    else:
        adj_stop = stop_loss
        adj_target = take_profit

    bars_to_check = min(HOLD_DAYS, len(future_bars))
    exit_price = entry

    for i in range(bars_to_check):
        bar = future_bars.iloc[i]
        low = float(bar["low"])
        high = float(bar["high"])

        # Check stop loss first (conservative)
        if low <= adj_stop:
            return TradeOutcome(
                symbol=symbol, date=date, strategy=strategy, score=score,
                entry_price=entry, stop_loss=adj_stop, take_profit=adj_target,
                exit_price=adj_stop, status="loss",
                pnl_pct=((adj_stop / entry) - 1) * 100,
                ctx_score=ctx_score, ctx_bonus=ctx_bonus,
            )
        # Check take profit
        if high >= adj_target:
            return TradeOutcome(
                symbol=symbol, date=date, strategy=strategy, score=score,
                entry_price=entry, stop_loss=adj_stop, take_profit=adj_target,
                exit_price=adj_target, status="win",
                pnl_pct=((adj_target / entry) - 1) * 100,
                ctx_score=ctx_score, ctx_bonus=ctx_bonus,
            )
        exit_price = float(bar["close"])

    # Timeout — exit at last bar's close
    pnl = ((exit_price / entry) - 1) * 100
    return TradeOutcome(
        symbol=symbol, date=date, strategy=strategy, score=score,
        entry_price=entry, stop_loss=adj_stop, take_profit=adj_target,
        exit_price=exit_price, status="timeout",
        pnl_pct=pnl, ctx_score=ctx_score, ctx_bonus=ctx_bonus,
    )


# ---------------------------------------------------------------------------
# Context score calculation with tunable params
# ---------------------------------------------------------------------------
def calc_context_score(
    failed_bo: bool,
    failed_bd: bool,
    close_str: float,
    range_exp: float,
    *,
    fbp: float,  # failed_breakout_penalty
    fbb: float,  # failed_breakdown_bonus
    csw: float,  # close_strength_weight
    wrt: float = 1.5,  # wide_range_threshold (fixed)
    wrp: float,  # wide_range_reversal_penalty
) -> float:
    """Compute context score with custom weights."""
    score = 0.0
    if failed_bo:
        score -= fbp
    if failed_bd:
        score += fbb
    score += (close_str - 0.5) * csw
    if range_exp > wrt and close_str < 0.3:
        score -= wrp
    return score  # No clamp — individual weights control magnitude


# ---------------------------------------------------------------------------
# Main tuning logic
# ---------------------------------------------------------------------------
def load_scores_for_dates(
    db, dates: List[str], strategy: Optional[str] = None,
) -> Dict[str, List[dict]]:
    """Load trade_scores from MongoDB grouped by date."""
    query = {"date": {"$in": dates}}
    if strategy:
        query["strategy"] = strategy

    cursor = db["trade_scores"].find(query)
    by_date: Dict[str, List[dict]] = {}
    for doc in cursor:
        d = doc["date"]
        by_date.setdefault(d, []).append(doc)
    return by_date


def get_market_dates_after(store: DuckDBStore, date: str, n: int = 5) -> List[str]:
    """Get the next N trading dates after `date` from DuckDB (using SPY)."""
    df = store.load_symbol("SPY", start_date=date)
    if df is None or df.empty:
        return []
    dates = sorted(df["date"].unique())
    # Find dates strictly after the given date
    future = [d for d in dates if d > date]
    return future[:n]


def run_tuning(args):
    # Connect to MongoDB
    mongo_uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    mongo_db = os.getenv("MONGO_DB", "bluehorseshoe")
    client = MongoClient(mongo_uri)
    db = client[mongo_db]

    # Connect to DuckDB (read-only)
    duckdb_path = os.getenv("DUCKDB_PATH", os.path.join(
        os.path.dirname(__file__), "..", "data", "ohlcv.duckdb"
    ))
    store = DuckDBStore(duckdb_path, read_only=True)

    # Get available dates
    all_dates = sorted(db["trade_scores"].distinct("date"))
    # Use the most recent N dates (skip the very last one since we need future bars)
    use_dates = all_dates[-(args.dates + 1):-1]  # Last N+1, skip final
    log.info(f"Tuning over {len(use_dates)} dates: {use_dates[0]} to {use_dates[-1]}")

    # Load scores
    scores_by_date = load_scores_for_dates(db, use_dates, args.strategy)
    log.info(f"Loaded scores for {len(scores_by_date)} dates")

    # Pre-compute OHLCV context data for all (date, symbol) pairs
    log.info("Pre-computing context signals from OHLCV...")
    # context_cache[date][symbol] = (failed_bo, failed_bd, close_str, range_exp)
    context_cache: Dict[str, Dict[str, Tuple[bool, bool, float, float]]] = {}
    # future_bars_cache[date][symbol] = DataFrame of next HOLD_DAYS+1 bars
    future_cache: Dict[str, Dict[str, pd.DataFrame]] = {}

    for di, date in enumerate(use_dates):
        if date not in scores_by_date:
            continue
        symbols_for_date = list({doc["symbol"] for doc in scores_by_date[date]})
        log.info(f"  [{di+1}/{len(use_dates)}] {date}: {len(symbols_for_date)} symbols")

        # Get future dates for grading
        future_dates = get_market_dates_after(store, date, HOLD_DAYS + 1)
        if not future_dates:
            log.warning(f"    No future bars for {date}, skipping")
            continue

        end_date = future_dates[-1] if future_dates else date

        # Bulk load OHLCV — need lookback before date + future bars
        # We load a generous window: 60 days before date through end_date
        # Compute a rough start date
        from datetime import datetime, timedelta
        dt = datetime.strptime(date, "%Y-%m-%d")
        lookback_start = (dt - timedelta(days=60)).strftime("%Y-%m-%d")

        bulk_data = store.load_symbols_bulk(symbols_for_date, start_date=lookback_start)

        context_cache[date] = {}
        future_cache[date] = {}

        for sym in symbols_for_date:
            df = bulk_data.get(sym)
            if df is None or df.empty:
                continue

            # Sort by date
            df = df.sort_values("date").reset_index(drop=True)

            # Split into history (up to and including date) and future
            hist = df[df["date"] <= date]
            future = df[df["date"] > date]

            if len(hist) < 3:
                continue

            # Compute context signals from historical bars
            failed_bo, failed_bd, _res, _sup = detect_failed_breakout(hist, LOOKBACK_DAYS)
            cs = close_strength(hist.iloc[-1])

            # ATR approximation: average true range over last 14 bars
            atr_window = min(14, len(hist) - 1)
            if atr_window > 0:
                recent = hist.tail(atr_window + 1)
                tr_vals = []
                for i in range(1, len(recent)):
                    h = float(recent.iloc[i]["high"])
                    l = float(recent.iloc[i]["low"])
                    pc = float(recent.iloc[i - 1]["close"])
                    tr = max(h - l, abs(h - pc), abs(l - pc))
                    tr_vals.append(tr)
                atr = sum(tr_vals) / len(tr_vals) if tr_vals else (
                    float(hist.iloc[-1]["high"]) - float(hist.iloc[-1]["low"])
                )
            else:
                atr = float(hist.iloc[-1]["high"]) - float(hist.iloc[-1]["low"])

            re = range_expansion(
                float(hist.iloc[-1]["high"]),
                float(hist.iloc[-1]["low"]),
                atr,
            )

            context_cache[date][sym] = (failed_bo, failed_bd, cs, re)

            # Future bars for grading
            if not future.empty:
                future_cache[date][sym] = future.head(HOLD_DAYS + 1)

    # Generate grid combos
    # Full grid is huge (5*4*5*4*7 = 2800 combos). Use reduced grid if --fast
    if args.fast:
        grid = {
            "failed_breakout_penalty": [0.0, 0.5, 1.0, 2.0],
            "failed_breakdown_bonus": [0.0],
            "close_strength_weight": [0.6, 1.0, 1.5, 2.0, 3.0],
            "wide_range_reversal_penalty": [0.0],
            "integration_weight": [0.0, 3.0, 4.0, 6.0, 8.0, 10.0],
        }
    else:
        grid = GRID

    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    log.info(f"Grid: {len(combos)} weight combinations")

    # Run grid search
    results = []
    for ci, combo in enumerate(combos):
        params = dict(zip(keys, combo))
        fbp = params["failed_breakout_penalty"]
        fbb = params["failed_breakdown_bonus"]
        csw = params["close_strength_weight"]
        wrp = params["wide_range_reversal_penalty"]
        iw = params["integration_weight"]

        all_outcomes: List[TradeOutcome] = []

        for date in use_dates:
            if date not in scores_by_date or date not in context_cache:
                continue

            # Recalculate adjusted scores
            adjusted = []
            for doc in scores_by_date[date]:
                sym = doc["symbol"]
                if sym not in context_cache[date]:
                    continue

                base_score = doc["score"]
                meta = doc.get("metadata", {})
                components = meta.get("components", {})

                # Subtract old intraday_context bonus if present
                old_ctx_bonus = components.get("intraday_context", 0.0) or 0.0
                score_without_ctx = base_score - old_ctx_bonus

                # Calculate new context score
                failed_bo, failed_bd, cs, re = context_cache[date][sym]
                new_ctx_score = calc_context_score(
                    failed_bo, failed_bd, cs, re,
                    fbp=fbp, fbb=fbb, csw=csw, wrp=wrp,
                )
                new_ctx_bonus = new_ctx_score * iw
                new_score = score_without_ctx + new_ctx_bonus

                adjusted.append({
                    "symbol": sym,
                    "date": date,
                    "strategy": doc["strategy"],
                    "score": new_score,
                    "entry_price": meta.get("entry_price", 0),
                    "stop_loss": meta.get("stop_loss", 0),
                    "take_profit": meta.get("take_profit", 0),
                    "ctx_score": new_ctx_score,
                    "ctx_bonus": new_ctx_bonus,
                })

            # Sort by score descending and take top N
            adjusted.sort(key=lambda x: x["score"], reverse=True)
            top_n = adjusted[:args.top]

            # Grade each
            for cand in top_n:
                sym = cand["symbol"]
                if sym not in future_cache.get(date, {}):
                    continue
                if cand["entry_price"] <= 0 or cand["stop_loss"] <= 0:
                    continue

                outcome = grade_trade(
                    symbol=sym,
                    date=date,
                    strategy=cand["strategy"],
                    score=cand["score"],
                    entry_price=cand["entry_price"],
                    stop_loss=cand["stop_loss"],
                    take_profit=cand["take_profit"],
                    ctx_score=cand["ctx_score"],
                    ctx_bonus=cand["ctx_bonus"],
                    future_bars=future_cache[date][sym],
                )
                if outcome:
                    all_outcomes.append(outcome)

        # Compute aggregate metrics
        if not all_outcomes:
            continue

        total = len(all_outcomes)
        wins = sum(1 for o in all_outcomes if o.status == "win")
        losses = sum(1 for o in all_outcomes if o.status == "loss")
        timeouts = sum(1 for o in all_outcomes if o.status == "timeout")
        win_rate = (wins / total) * 100 if total > 0 else 0
        avg_pnl = sum(o.pnl_pct for o in all_outcomes) / total if total > 0 else 0
        total_pnl = sum(o.pnl_pct for o in all_outcomes)

        # Profit factor: gross wins / gross losses
        gross_wins = sum(o.pnl_pct for o in all_outcomes if o.pnl_pct > 0)
        gross_losses = abs(sum(o.pnl_pct for o in all_outcomes if o.pnl_pct < 0))
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else float("inf")

        result = {
            **params,
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "timeouts": timeouts,
            "win_rate": round(win_rate, 2),
            "avg_pnl": round(avg_pnl, 4),
            "total_pnl": round(total_pnl, 2),
            "profit_factor": round(profit_factor, 3),
        }
        results.append(result)

        if (ci + 1) % 100 == 0 or ci == 0:
            log.info(
                f"  [{ci+1}/{len(combos)}] "
                f"fbp={fbp} fbb={fbb} csw={csw} wrp={wrp} iw={iw} → "
                f"WR={win_rate:.1f}% avg={avg_pnl:.3f}% trades={total}"
            )

    # Sort by composite metric: win_rate * 0.4 + avg_pnl_normalized * 0.3 + profit_factor_normalized * 0.3
    # Simple: sort by avg_pnl first, then win_rate as tiebreaker
    results.sort(key=lambda r: (r["avg_pnl"], r["win_rate"]), reverse=True)

    # Write results
    out_path = os.path.join(
        os.path.dirname(__file__), "logs", "intraday_weight_tuning.csv"
    )
    if results:
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        log.info(f"\nResults written to {out_path}")

    # Print top 20
    print("\n" + "=" * 100)
    print("TOP 20 WEIGHT COMBINATIONS")
    print("=" * 100)
    header = (
        f"{'FBP':>5} {'FBB':>5} {'CSW':>5} {'WRP':>5} {'IW':>5} | "
        f"{'WR%':>6} {'AvgPnL':>8} {'TotPnL':>8} {'PF':>6} | "
        f"{'Trades':>6} {'W':>4} {'L':>4} {'T':>4}"
    )
    print(header)
    print("-" * 100)
    for r in results[:20]:
        print(
            f"{r['failed_breakout_penalty']:>5.1f} "
            f"{r['failed_breakdown_bonus']:>5.1f} "
            f"{r['close_strength_weight']:>5.1f} "
            f"{r['wide_range_reversal_penalty']:>5.1f} "
            f"{r['integration_weight']:>5.1f} | "
            f"{r['win_rate']:>6.1f} {r['avg_pnl']:>8.4f} {r['total_pnl']:>8.2f} "
            f"{r['profit_factor']:>6.2f} | "
            f"{r['total_trades']:>6} {r['wins']:>4} {r['losses']:>4} {r['timeouts']:>4}"
        )

    # Also print baseline (iw=0, which means no context influence)
    baseline = [r for r in results if r["integration_weight"] == 0.0]
    if baseline:
        b = baseline[0]
        print(f"\nBASELINE (no context): WR={b['win_rate']:.1f}% "
              f"AvgPnL={b['avg_pnl']:.4f}% PF={b['profit_factor']:.2f} "
              f"Trades={b['total_trades']}")

    # Print current production weights for comparison
    current = [
        r for r in results
        if (r["failed_breakout_penalty"] == 0.5
            and r["failed_breakdown_bonus"] == 0.4
            and r["close_strength_weight"] == 0.6
            and r["wide_range_reversal_penalty"] == 0.2
            and r["integration_weight"] == 3.0)
    ]
    if current:
        c = current[0]
        print(f"CURRENT PROD:         WR={c['win_rate']:.1f}% "
              f"AvgPnL={c['avg_pnl']:.4f}% PF={c['profit_factor']:.2f} "
              f"Trades={c['total_trades']}")

    store.close()
    client.close()

    return results


def main():
    parser = argparse.ArgumentParser(description="Tune intraday context weights")
    parser.add_argument("--top", type=int, default=10,
                        help="Top N candidates to grade per date (default: 10)")
    parser.add_argument("--dates", type=int, default=25,
                        help="Number of recent dates to use (default: 25)")
    parser.add_argument("--strategy", type=str, default=None,
                        choices=["baseline", "mean_reversion"],
                        help="Strategy to tune (default: both)")
    parser.add_argument("--fast", action="store_true",
                        help="Use reduced grid (faster, fewer combos)")
    args = parser.parse_args()
    run_tuning(args)


if __name__ == "__main__":
    main()
