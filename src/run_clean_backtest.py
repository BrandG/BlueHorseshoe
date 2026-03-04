"""
run_clean_backtest.py

Resilient per-version backtest runner with per-date checkpointing.

Runs backtests for V2, V3, or V3.1 weights over stratified test dates
(loaded from test_dates.json) with identical parameters. Results go to
dedicated versioned CSV files so runs never pollute each other or the
shared backtest_log.csv.

On restart, skips already-completed dates (resume logic).

Usage:
    docker exec -e PYTHONUNBUFFERED=1 bluehorseshoe python src/run_clean_backtest.py --version v2
    docker exec -e PYTHONUNBUFFERED=1 bluehorseshoe python src/run_clean_backtest.py --version v3
    docker exec -e PYTHONUNBUFFERED=1 bluehorseshoe python src/run_clean_backtest.py --version v31
"""

import argparse
import csv
import gc
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

# ── Fixed Parameters ──────────────────────────────────────────────────────
TEST_DATES_PATH = Path("/workspaces/BlueHorseshoe/src/test_dates.json")


def load_target_dates() -> list:
    """Load stratified test dates from test_dates.json."""
    if not TEST_DATES_PATH.exists():
        print(f"ERROR: {TEST_DATES_PATH} not found. Run build_test_dates.py first.")
        sys.exit(1)
    with open(TEST_DATES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    dates = sorted(data["all_dates"])
    print(f"  Loaded {len(dates)} stratified test dates from {TEST_DATES_PATH.name}")
    return dates


def load_regime_scores() -> dict:
    """Build date -> regime_score mapping from test_dates.json buckets."""
    with open(TEST_DATES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    scores = {}
    for entries in data["buckets"].values():
        for entry in entries:
            scores[entry["date"]] = entry["score"]
    return scores


def select_adaptive_version(regime_score: int) -> str:
    """Pick V2 or V3 based on regime score. V3 for extremes (<=2 or >=9), V2 for favorable (3-8)."""
    if regime_score <= 2 or regime_score >= 9:
        return "v3"
    return "v2"


STRATEGY = "baseline"
TOP_N = 10
HOLD_DAYS = 3
SPLIT_T1_PCT = 0.02

WEIGHT_FILES = {
    "v2":  "/workspaces/BlueHorseshoe/src/weights_v2.json",
    "v3":  "/workspaces/BlueHorseshoe/src/weights_v3.json",
    "v31": "/workspaces/BlueHorseshoe/src/weights_v31.json",
    "adaptive": None,  # Uses V2 or V3 per-date based on regime score
}

ADAPTIVE_WEIGHT_FILES = {
    "v2": "/workspaces/BlueHorseshoe/src/weights_v2_full.json",
    "v3": "/workspaces/BlueHorseshoe/src/weights_v3.json",
}

OUTPUT_DIR = Path("/workspaces/BlueHorseshoe/src/logs")

CSV_FIELDS = [
    "date", "symbol", "strategy", "score", "ml_prob",
    "entry", "stop_loss", "take_profit", "exit_price",
    "exit_date", "days_held", "status", "outcome", "profit_loss",
    "t1_status", "t1_pnl", "t2_status", "t2_pnl",
]


# ── Helpers ───────────────────────────────────────────────────────────────

def output_path(version: str) -> Path:
    return OUTPUT_DIR / f"clean_backtest_{version}.csv"


def load_completed_dates(csv_path: Path) -> set:
    """Read the output CSV and return the set of dates already completed."""
    if not csv_path.exists():
        return set()
    completed = set()
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            completed.add(row["date"])
    return completed


def write_header_if_needed(csv_path: Path) -> None:
    """Write CSV header if the file doesn't exist yet."""
    if not csv_path.exists():
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()


def append_results(csv_path: Path, results: list, target_date: str,
                   score_key: str, ml_prob_key: str) -> None:
    """Append one date's results to the versioned CSV, flush immediately."""
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        for result in results:
            if result.get("entry") and result.get("exit_price"):
                pnl = ((result["exit_price"] / result["entry"]) - 1) * 100
                win_statuses = [
                    "success", "closed_profit",
                    "split_full_profit", "split_partial_profit",
                ]
                loss_statuses = ["stopped_out", "closed_loss"]
                if result["status"] in win_statuses:
                    outcome = "WIN"
                elif result["status"] in loss_statuses:
                    outcome = "LOSS"
                else:
                    outcome = "TIMEOUT"
            else:
                pnl = 0.0
                outcome = "NO_ENTRY"

            row = {
                "date": target_date,
                "symbol": result.get("symbol", ""),
                "strategy": STRATEGY,
                "score": result.get(score_key, 0.0),
                "ml_prob": result.get(ml_prob_key, 0.0),
                "entry": result.get("entry", ""),
                "stop_loss": result.get("stop_loss", ""),
                "take_profit": result.get("take_profit", ""),
                "exit_price": result.get("exit_price", ""),
                "exit_date": result.get("exit_date", ""),
                "days_held": result.get("days_held", 0),
                "status": result.get("status", ""),
                "outcome": outcome,
                "profit_loss": round(pnl, 2),
            }

            if result.get("exit_mode") == "split_exit":
                row["t1_status"] = result.get("tranche1_status", "")
                row["t1_pnl"] = round(result.get("tranche1_pnl_pct", 0.0), 2)
                row["t2_status"] = result.get("tranche2_status", "")
                row["t2_pnl"] = round(result.get("tranche2_pnl_pct", 0.0), 2)

            writer.writerow(row)
        f.flush()
        os.fsync(f.fileno())


def print_date_summary(results: list, target_date: str) -> None:
    """Print a one-line summary for a single date."""
    valid = [r for r in results
             if r.get("entry") is not None and r.get("exit_price") is not None]
    if not valid:
        print(f"  {target_date}: no valid trades")
        return

    win_statuses = [
        "success", "closed_profit",
        "split_full_profit", "split_partial_profit",
    ]
    wins = sum(1 for r in valid if r["status"] in win_statuses)
    pnls = [((r["exit_price"] / r["entry"]) - 1) * 100 for r in valid]
    total_pnl = sum(pnls)
    avg_pnl = total_pnl / len(pnls)
    print(
        f"  {target_date}: {wins}/{len(valid)} wins "
        f"| avg {avg_pnl:+.2f}% | total {total_pnl:+.2f}%",
        flush=True,
    )


def print_overall_summary(csv_path: Path) -> None:
    """Print a final summary from the completed CSV."""
    if not csv_path.exists():
        print("\nNo results file found.")
        return

    with open(csv_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    trades = [r for r in rows if r["status"] != "no_entry" and r["outcome"] != "NO_ENTRY"]
    if not trades:
        print("\nNo trades found in results.")
        return

    wins = [r for r in trades if r["outcome"] == "WIN"]
    pnls = [float(r["profit_loss"]) for r in trades]
    total_pnl = sum(pnls)
    avg_pnl = total_pnl / len(pnls)
    win_rate = len(wins) / len(trades) * 100
    dates = sorted(set(r["date"] for r in rows))

    best = max(trades, key=lambda r: float(r["profit_loss"]))
    worst = min(trades, key=lambda r: float(r["profit_loss"]))

    print(f"\n{'='*60}")
    print(f"FINAL SUMMARY — {csv_path.name}")
    print(f"{'='*60}")
    print(f"Dates:       {len(dates)}")
    print(f"Total rows:  {len(rows)}")
    print(f"Trades:      {len(trades)} (excl no-entry)")
    print(f"Wins:        {len(wins)}")
    print(f"Win Rate:    {win_rate:.1f}%")
    print(f"Avg P&L:     {avg_pnl:.2f}%")
    print(f"Total P&L:   {total_pnl:.2f}%")
    print(f"Best trade:  {best['symbol']} on {best['date']} = +{float(best['profit_loss']):.2f}%")
    print(f"Worst trade: {worst['symbol']} on {worst['date']} = {float(worst['profit_loss']):.2f}%")
    print(f"{'='*60}")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Resilient clean backtest runner")
    parser.add_argument(
        "--version", required=True, choices=["v2", "v3", "v31", "adaptive"],
        help="Weight version to backtest (v2, v3, v31, adaptive)",
    )
    args = parser.parse_args()

    version = args.version
    is_adaptive = version == "adaptive"
    csv_path = output_path(version)
    target_dates = load_target_dates()

    from bluehorseshoe.core.config import weights_config

    if is_adaptive:
        regime_scores = load_regime_scores()
        # Pre-load both weight sets
        adaptive_weights = {}
        for label, path in ADAPTIVE_WEIGHT_FILES.items():
            if not os.path.exists(path):
                print(f"ERROR: Adaptive weights file not found: {path}")
                sys.exit(1)
            with open(path, "r", encoding="utf-8") as f:
                adaptive_weights[label] = json.load(f)
        print(f"Clean Backtest Runner — version ADAPTIVE")
        print(f"  V2 weights:    {ADAPTIVE_WEIGHT_FILES['v2']}")
        print(f"  V3 weights:    {ADAPTIVE_WEIGHT_FILES['v3']}")
        print(f"  Rule:          V3 for score<=2 or >=9, V2 for 3-8")
    else:
        weights_path = WEIGHT_FILES[version]
        if not os.path.exists(weights_path):
            print(f"ERROR: Weights file not found: {weights_path}")
            sys.exit(1)
        with open(weights_path, "r", encoding="utf-8") as f:
            new_weights = json.load(f)
        weights_config._weights = new_weights
        print(f"Clean Backtest Runner — version {version.upper()}")
        print(f"  Weights file:  {weights_path}")

    print(f"  Output CSV:    {csv_path}")
    print(f"  Strategy:      {STRATEGY}")
    print(f"  Top N:         {TOP_N}")
    print(f"  Hold days:     {HOLD_DAYS}")
    print(f"  Split-exit:    t1_pct={SPLIT_T1_PCT}")
    print(f"  Dates:         {len(target_dates)}")
    print(flush=True)

    # 2. Initialize backtester
    from bluehorseshoe.analysis.backtest import (
        Backtester, BacktestConfig, BacktestOptions, SplitExitConfig,
    )
    from bluehorseshoe.core.container import create_app_container
    from bluehorseshoe.core.symbols import get_symbol_name_list

    container = create_app_container()
    database = container.get_database()

    config = BacktestConfig(
        hold_days=HOLD_DAYS,
        target_profit_factor=1.01,
        stop_loss_factor=0.98,
    )
    backtester = Backtester(config=config, database=database)

    options = BacktestOptions(
        strategy=STRATEGY,
        top_n=TOP_N,
        max_workers=4,  # Conservative for 4GB container
    )

    split_config = SplitExitConfig(
        mode="fixed_pct",
        t1_profit_pct=SPLIT_T1_PCT,
    )

    score_key = "baseline_score"
    ml_prob_key = "baseline_ml_prob"

    # 3. Load symbols once
    print("  Loading symbols...", end="", flush=True)
    symbols = get_symbol_name_list(database=backtester.database, active_only=True)
    print(f" {len(symbols)} symbols.", flush=True)
    options.symbols = symbols

    # 4. Resume logic — find completed dates
    completed_dates = load_completed_dates(csv_path)
    remaining_dates = [d for d in target_dates if d not in completed_dates]

    if completed_dates:
        print(f"\n  Resume: {len(completed_dates)}/{len(target_dates)} dates already done, "
              f"{len(remaining_dates)} remaining.", flush=True)
    if not remaining_dates:
        print("\n  All dates already completed!", flush=True)
        print_overall_summary(csv_path)
        return

    # 5. Ensure CSV header exists
    write_header_if_needed(csv_path)

    # 6. Run each date
    print(f"\n  Starting backtest ({len(remaining_dates)} dates)...\n", flush=True)
    start_time = time.time()

    for i, target_date in enumerate(remaining_dates):
        date_start = time.time()
        step = len(completed_dates) + i + 1
        print(
            f"[{step}/{len(target_dates)}] {target_date} ...",
            flush=True,
        )

        # Re-patch weights (safety: in case anything reloads them)
        if is_adaptive:
            score = regime_scores.get(target_date, 5)
            chosen = select_adaptive_version(score)
            weights_config._weights = adaptive_weights[chosen]
            print(f"  regime={score} -> {chosen.upper()} weights", flush=True)
        else:
            weights_config._weights = new_weights

        # Generate predictions
        predictions = backtester._generate_predictions(symbols, target_date, options)

        # Filter and sort
        top_predictions = backtester._filter_and_sort_predictions(predictions, options)

        if not top_predictions:
            print(f"  {target_date}: no valid signals", flush=True)
            # Write empty rows so resume logic knows this date was processed
            # (append a sentinel row)
            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                writer.writerow({
                    "date": target_date, "symbol": "", "strategy": STRATEGY,
                    "score": 0, "ml_prob": 0, "entry": "", "stop_loss": "",
                    "take_profit": "", "exit_price": "", "exit_date": "",
                    "days_held": 0, "status": "no_signals", "outcome": "NO_ENTRY",
                    "profit_loss": 0,
                })
                f.flush()
                os.fsync(f.fileno())
        else:
            # Evaluate candidates
            results = backtester._evaluate_candidates(
                top_predictions, target_date, options, split_config=split_config,
            )

            # Append to versioned CSV
            append_results(csv_path, results, target_date, score_key, ml_prob_key)

            # Print date summary
            print_date_summary(results, target_date)

        date_elapsed = time.time() - date_start
        print(f"  ({date_elapsed:.0f}s)\n", flush=True)

        # Free memory between dates
        gc.collect()

    total_elapsed = time.time() - start_time
    print(f"\nAll dates complete. Total time: {total_elapsed/60:.1f} min", flush=True)

    # 7. Print overall summary
    print_overall_summary(csv_path)

    # 8. Restore production weights
    prod_weights_path = "/workspaces/BlueHorseshoe/src/weights.json"
    if os.path.exists(prod_weights_path):
        with open(prod_weights_path, "r", encoding="utf-8") as f:
            weights_config._weights = json.load(f)
        print("\n  Production weights restored.", flush=True)


if __name__ == "__main__":
    main()
