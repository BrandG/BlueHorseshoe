"""
compare_clean_backtests.py

3-way comparison of clean backtest results for V2, V3, and V3.1 weights.
Reads from dedicated versioned CSV files and prints:
- Per-version summary (trades, win rate, avg P&L, total P&L, best/worst)
- Per-date breakdown for each version
- Side-by-side summary table
- Pick overlap analysis (V2<>V3, V2<>V3.1, V3<>V3.1)

Usage:
    docker exec bluehorseshoe python src/compare_clean_backtests.py
"""

import csv
import json
import sys
from pathlib import Path

LOG_DIR = Path("/workspaces/BlueHorseshoe/src/logs")
TEST_DATES_PATH = Path("/workspaces/BlueHorseshoe/src/test_dates.json")

FILES = {
    "V2":   LOG_DIR / "clean_backtest_v2.csv",
    "V3":   LOG_DIR / "clean_backtest_v3.csv",
    "V3.1": LOG_DIR / "clean_backtest_v31.csv",
}


def load_target_dates() -> list:
    """Load stratified test dates from test_dates.json."""
    if not TEST_DATES_PATH.exists():
        print(f"ERROR: {TEST_DATES_PATH} not found. Run build_test_dates.py first.")
        sys.exit(1)
    with open(TEST_DATES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return sorted(data["all_dates"])

WIN_STATUSES = {"WIN"}
LOSS_STATUSES = {"LOSS"}


def load_rows(path: Path) -> list:
    """Load CSV rows, return list of dicts."""
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def get_trades(rows: list) -> list:
    """Filter to actual trades (exclude no-entry, no-signals)."""
    return [
        r for r in rows
        if r.get("outcome") not in ("NO_ENTRY", "") and r.get("status") != "no_signals"
    ]


def analyze_version(label: str, rows: list, target_dates: list) -> list:
    """Print detailed analysis for one version. Returns trades list."""
    trades = get_trades(rows)
    wins = [r for r in trades if r["outcome"] == "WIN"]
    losses = [r for r in trades if r["outcome"] == "LOSS"]
    no_entry = [r for r in rows if r.get("outcome") == "NO_ENTRY"]

    pnls = [float(r["profit_loss"]) for r in trades]
    total_pnl = sum(pnls)
    avg_pnl = total_pnl / len(pnls) if pnls else 0
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    best = max(trades, key=lambda r: float(r["profit_loss"])) if trades else None
    worst = min(trades, key=lambda r: float(r["profit_loss"])) if trades else None

    dates = sorted(set(r["date"] for r in rows))

    print(f"\n{'='*65}")
    print(f"  {label}")
    print(f"{'='*65}")
    print(f"  Total rows: {len(rows)}  |  Trades: {len(trades)}  |  No-entry: {len(no_entry)}")
    print(f"  Wins: {len(wins)}  |  Losses: {len(losses)}")
    print(f"  Win Rate: {win_rate:.1f}%")
    print(f"  Avg P&L per trade: {avg_pnl:+.2f}%")
    print(f"  Total P&L: {total_pnl:+.2f}%")
    print(f"  Dates covered: {len(dates)}/{len(target_dates)}")
    if best:
        print(f"  Best trade:  {best['symbol']} on {best['date']} = +{float(best['profit_loss']):.2f}%")
    if worst:
        print(f"  Worst trade: {worst['symbol']} on {worst['date']} = {float(worst['profit_loss']):.2f}%")

    # Per-date breakdown
    print(f"\n  {'Date':<12} {'Trades':>6} {'Wins':>5} {'WinRate':>8} {'AvgPnL':>8} {'TotalPnL':>9}")
    print(f"  {'-'*50}")
    for d in target_dates:
        dt = [r for r in trades if r["date"] == d]
        dw = [r for r in dt if r["outcome"] == "WIN"]
        dp = [float(r["profit_loss"]) for r in dt]
        wr = len(dw) / len(dt) * 100 if dt else 0
        ap = sum(dp) / len(dp) if dp else 0
        tp = sum(dp)
        if dt:
            print(f"  {d:<12} {len(dt):>6} {len(dw):>5} {wr:>7.1f}% {ap:>+7.2f}% {tp:>+8.2f}%")
        else:
            print(f"  {d:<12}      -     -        -        -         -")

    return trades


def overlap_report(label_a: str, trades_a: list, label_b: str, trades_b: list) -> None:
    """Report pick overlap between two versions."""
    picks_a = {(t["date"], t["symbol"]) for t in trades_a}
    picks_b = {(t["date"], t["symbol"]) for t in trades_b}
    shared = picks_a & picks_b
    only_a = picks_a - picks_b
    only_b = picks_b - picks_a
    union = picks_a | picks_b
    jaccard = len(shared) / max(len(union), 1) * 100

    # P&L of shared picks in each version
    shared_pnl_a = sum(
        float(t["profit_loss"]) for t in trades_a
        if (t["date"], t["symbol"]) in shared
    )
    shared_pnl_b = sum(
        float(t["profit_loss"]) for t in trades_b
        if (t["date"], t["symbol"]) in shared
    )

    print(f"\n  {label_a} vs {label_b}:")
    print(f"    Shared picks: {len(shared)}/{len(union)} ({jaccard:.1f}% Jaccard)")
    print(f"    {label_a}-only: {len(only_a)}")
    print(f"    {label_b}-only: {len(only_b)}")
    print(f"    Shared picks P&L: {label_a}={shared_pnl_a:+.2f}%, {label_b}={shared_pnl_b:+.2f}%")


def main():
    target_dates = load_target_dates()

    # Load all versions
    data = {}
    for label, path in FILES.items():
        rows = load_rows(path)
        if not rows:
            print(f"WARNING: No data for {label} at {path}")
        data[label] = rows

    available = {k: v for k, v in data.items() if v}
    if not available:
        print("ERROR: No backtest data found. Run backtest first.")
        sys.exit(1)

    print(f"\nLoaded: ", end="")
    print(" | ".join(f"{k}={len(v)} rows" for k, v in data.items()))

    # Validation
    for label, rows in available.items():
        dates = sorted(set(r["date"] for r in rows))
        missing = set(target_dates) - set(dates)
        if missing:
            print(f"  WARNING: {label} missing dates: {sorted(missing)}")

    # Per-version analysis
    trades = {}
    for label, rows in data.items():
        if rows:
            trades[label] = analyze_version(label, rows, target_dates)
        else:
            trades[label] = []

    # Side-by-side comparison
    print(f"\n\n{'='*70}")
    print("SIDE-BY-SIDE COMPARISON")
    print(f"{'='*70}")
    print(f"  {'Version':<8} {'Trades':>7} {'Wins':>6} {'WinRate':>8} {'AvgPnL':>9} {'TotalPnL':>10}")
    print(f"  {'-'*50}")

    for label, t_list in trades.items():
        if not t_list:
            print(f"  {label:<8}       -      -        -         -          -")
            continue
        pnls = [float(t["profit_loss"]) for t in t_list]
        wins = [t for t in t_list if t["outcome"] == "WIN"]
        total = sum(pnls)
        avg = total / len(pnls) if pnls else 0
        wr = len(wins) / len(t_list) * 100 if t_list else 0
        print(f"  {label:<8} {len(t_list):>7} {len(wins):>6} {wr:>7.1f}% {avg:>+8.2f}% {total:>+9.2f}%")

    # Overlap analysis
    labels = list(trades.keys())
    if len(labels) >= 2:
        print(f"\n{'='*70}")
        print("PICK OVERLAP ANALYSIS")
        print(f"{'='*70}")
        for i in range(len(labels)):
            for j in range(i + 1, len(labels)):
                a, b = labels[i], labels[j]
                if trades[a] and trades[b]:
                    overlap_report(a, trades[a], b, trades[b])

    # Per-date head-to-head
    if all(trades.get(k) for k in ["V2", "V3", "V3.1"]):
        print(f"\n\n{'='*70}")
        print("PER-DATE HEAD-TO-HEAD")
        print(f"{'='*70}")
        print(f"  {'Date':<12} {'V2 PnL':>9} {'V3 PnL':>9} {'V3.1 PnL':>9} {'Best':>6}")
        print(f"  {'-'*50}")

        for d in target_dates:
            pnl = {}
            for label in ["V2", "V3", "V3.1"]:
                dt = [t for t in trades[label] if t["date"] == d]
                dp = sum(float(t["profit_loss"]) for t in dt)
                pnl[label] = dp

            best_label = max(pnl, key=pnl.get) if any(pnl.values()) else "-"
            print(
                f"  {d:<12} {pnl.get('V2', 0):>+8.2f}% {pnl.get('V3', 0):>+8.2f}% "
                f"{pnl.get('V3.1', 0):>+8.2f}% {best_label:>6}"
            )

        # Tally best days
        best_counts = {"V2": 0, "V3": 0, "V3.1": 0}
        for d in target_dates:
            pnl = {}
            for label in ["V2", "V3", "V3.1"]:
                dt = [t for t in trades[label] if t["date"] == d]
                pnl[label] = sum(float(t["profit_loss"]) for t in dt)
            best_label = max(pnl, key=pnl.get)
            best_counts[best_label] += 1

        print(f"\n  Best-day wins: ", end="")
        print(" | ".join(f"{k}={v}" for k, v in best_counts.items()))

    print()


if __name__ == "__main__":
    main()
