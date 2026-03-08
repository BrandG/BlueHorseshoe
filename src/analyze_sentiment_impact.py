"""
analyze_sentiment_impact.py

Correlate news-sentiment scores with trade outcomes.

Loads journal_signals from MongoDB (which already contain sentiment, entry_price,
stop_loss, take_profit_t2), simulates forward trades using DuckDB OHLCV data,
and reports win-rate / P&L broken down by sentiment bucket and strategy.

Usage:
    docker exec bluehorseshoe python src/analyze_sentiment_impact.py
"""

import csv
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

from bluehorseshoe.core.container import create_app_container

logging.basicConfig(level=logging.WARNING)

# ── Constants ─────────────────────────────────────────────────────────────

HOLD_DAYS = 3  # matches BacktestConfig default

SENTIMENT_BUCKETS = [
    ("Strongly Bearish", -999, -0.15),
    ("Mildly Bearish",   -0.15, 0.0),
    ("Neutral (N/A)",     0.0,  0.0),   # exact zero = no data
    ("Mildly Bullish",    0.0,  0.15),
    ("Strongly Bullish",  0.15, 999),
]


# ── Trade simulation ─────────────────────────────────────────────────────

def simulate_trade(
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    ohlcv_df: pd.DataFrame,
    entry_date: str,
    hold_days: int = HOLD_DAYS,
) -> Tuple[str, float, int]:
    """
    Simulate a single limit-entry trade using OHLCV data.

    Returns (outcome, pnl_pct, days_held).
    outcome: 'WIN', 'LOSS', 'TIMEOUT', 'NO_ENTRY', 'NO_DATA'
    """
    start = pd.to_datetime(entry_date)
    future = ohlcv_df[ohlcv_df["date"] > start].sort_values("date").reset_index(drop=True)

    if future.empty:
        return ("NO_DATA", 0.0, 0)

    entered = False
    actual_entry = None
    entry_idx = -1

    for i, row in future.iterrows():
        if not entered:
            # Check if price dips to entry (limit buy)
            if row["low"] <= entry_price:
                actual_entry = min(entry_price, row["open"]) if row["open"] <= entry_price else entry_price
                entered = True
                entry_idx = i

                # Same-bar stop check
                if row["low"] <= stop_loss:
                    px = min(actual_entry, stop_loss)
                    if row["open"] < stop_loss:
                        px = row["open"]
                    pnl = ((px / actual_entry) - 1) * 100
                    return ("LOSS", pnl, 0)

                # Same-bar target check
                if row["high"] >= take_profit:
                    pnl = ((take_profit / actual_entry) - 1) * 100
                    return ("WIN", pnl, 0)
        else:
            days = i - entry_idx

            # Stop hit
            if row["low"] <= stop_loss:
                px = stop_loss
                if row["open"] < stop_loss:
                    px = row["open"]
                pnl = ((px / actual_entry) - 1) * 100
                return ("LOSS", pnl, days)

            # Target hit
            if row["high"] >= take_profit:
                pnl = ((take_profit / actual_entry) - 1) * 100
                return ("WIN", pnl, days)

            # Hold-days expired
            if days >= hold_days:
                pnl = ((row["close"] / actual_entry) - 1) * 100
                outcome = "WIN" if pnl > 0 else "TIMEOUT"
                return (outcome, pnl, days)

    if not entered:
        return ("NO_ENTRY", 0.0, 0)

    # Ran out of data while in trade — mark to market
    last_row = future.iloc[-1]
    days = len(future) - 1 - entry_idx
    pnl = ((last_row["close"] / actual_entry) - 1) * 100
    outcome = "WIN" if pnl > 0 else "TIMEOUT"
    return (outcome, pnl, days)


# ── Bucketing ─────────────────────────────────────────────────────────────

def bucket_sentiment(value: float) -> str:
    """Assign a sentiment value to a named bucket."""
    if value == 0.0:
        return "Neutral (N/A)"
    for name, lo, hi in SENTIMENT_BUCKETS:
        if name == "Neutral (N/A)":
            continue
        if lo <= value < hi:
            return name
        # Include upper boundary for the last bucket
        if hi == 999 and value >= lo:
            return name
    return "Neutral (N/A)"


# ── Statistics ────────────────────────────────────────────────────────────

def compute_bucket_stats(records: List[Dict]) -> Dict:
    """Compute win rate / P&L stats for a list of trade records."""
    if not records:
        return {"n": 0, "win_rate": 0.0, "avg_pnl": 0.0, "median_pnl": 0.0}
    pnls = [r["pnl"] for r in records]
    wins = sum(1 for r in records if r["outcome"] == "WIN")
    return {
        "n": len(records),
        "win_rate": (wins / len(records)) * 100,
        "avg_pnl": float(np.mean(pnls)),
        "median_pnl": float(np.median(pnls)),
    }


# ── Main ──────────────────────────────────────────────────────────────────

def run_analysis():
    print("=" * 90)
    print("SENTIMENT IMPACT ANALYSIS")
    print("=" * 90)

    container = create_app_container()
    database = container.get_database()
    store = container.get_historical_store()

    # Load journal signals with non-zero sentiment
    signals_coll = database["journal_signals"]
    all_signals = list(signals_coll.find({}))
    print(f"Total journal signals: {len(all_signals)}")

    signals_with_sentiment = [s for s in all_signals if s.get("sentiment", 0.0) != 0.0]
    signals_without_sentiment = [s for s in all_signals if s.get("sentiment", 0.0) == 0.0]
    print(f"Signals with non-zero sentiment: {len(signals_with_sentiment)}")
    print(f"Signals with zero/missing sentiment: {len(signals_without_sentiment)}")

    batch_dates = sorted(set(s["batch_date"] for s in all_signals))
    print(f"Batch dates: {batch_dates}")

    # Simulate trades for all signals (including zero-sentiment for comparison)
    print("\nSimulating trades...", flush=True)

    # Bulk-load symbols for efficiency
    symbols_needed = list(set(s["symbol"] for s in all_signals))
    # Find earliest batch date to set start_date for bulk load
    earliest_date = min(batch_dates) if batch_dates else None
    price_cache: Dict[str, pd.DataFrame] = {}

    # Load in chunks to avoid memory issues
    chunk_size = 500
    for ci in range(0, len(symbols_needed), chunk_size):
        chunk = symbols_needed[ci:ci + chunk_size]
        bulk = store.load_symbols_bulk(chunk, start_date=earliest_date)
        for sym, df in bulk.items():
            df["date"] = pd.to_datetime(df["date"])
            price_cache[sym] = df
        if (ci + chunk_size) % 1000 == 0 or ci + chunk_size >= len(symbols_needed):
            print(f"  Loaded {min(ci + chunk_size, len(symbols_needed))}/{len(symbols_needed)} symbols", flush=True)

    trade_results: List[Dict] = []
    skipped = 0

    for sig in all_signals:
        symbol = sig["symbol"]
        sentiment = sig.get("sentiment", 0.0)
        entry_price = sig.get("entry_price", 0)
        stop_loss = sig.get("stop_loss", 0)
        take_profit = sig.get("take_profit_t2", 0)
        batch_date = sig["batch_date"]
        strategy = sig.get("strategy", "unknown")

        if not entry_price or not stop_loss or not take_profit:
            skipped += 1
            continue

        df = price_cache.get(symbol)
        if df is None or df.empty:
            skipped += 1
            continue

        outcome, pnl, days_held = simulate_trade(
            entry_price, stop_loss, take_profit, df, batch_date, HOLD_DAYS
        )

        if outcome in ("NO_DATA", "NO_ENTRY"):
            skipped += 1
            continue

        trade_results.append({
            "symbol": symbol,
            "batch_date": batch_date,
            "strategy": strategy,
            "sentiment": sentiment,
            "bucket": bucket_sentiment(sentiment),
            "outcome": outcome,
            "pnl": pnl,
            "days_held": days_held,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "composite_score": sig.get("composite_score", 0.0),
        })

    print(f"\nTrades simulated: {len(trade_results)} (skipped {skipped})")

    if not trade_results:
        print("No trade results to analyze.")
        return

    # ── Overall stats ─────────────────────────────────────────────────
    print("\n" + "=" * 90)
    print("OVERALL RESULTS")
    print("=" * 90)

    overall = compute_bucket_stats(trade_results)
    print(f"Total trades: {overall['n']}")
    print(f"Win rate: {overall['win_rate']:.1f}%")
    print(f"Avg P&L: {overall['avg_pnl']:.2f}%")
    print(f"Median P&L: {overall['median_pnl']:.2f}%")

    # ── By sentiment bucket ──────────────────────────────────────────
    print("\n" + "=" * 90)
    print("BY SENTIMENT BUCKET")
    print("=" * 90)

    bucket_order = [b[0] for b in SENTIMENT_BUCKETS]
    header = f"{'Bucket':<22} {'N':>6} {'Win%':>8} {'AvgPnL':>9} {'MedPnL':>9}"
    print(header)
    print("-" * 60)

    for bucket_name in bucket_order:
        recs = [r for r in trade_results if r["bucket"] == bucket_name]
        s = compute_bucket_stats(recs)
        if s["n"] > 0:
            print(f"{bucket_name:<22} {s['n']:>6} {s['win_rate']:>7.1f}% {s['avg_pnl']:>+8.2f}% {s['median_pnl']:>+8.2f}%")
        else:
            print(f"{bucket_name:<22} {0:>6}       -         -         -")

    # ── By strategy ──────────────────────────────────────────────────
    strategies = sorted(set(r["strategy"] for r in trade_results))
    for strat in strategies:
        print(f"\n{'=' * 90}")
        print(f"BY SENTIMENT BUCKET — {strat.upper()}")
        print("=" * 90)

        strat_records = [r for r in trade_results if r["strategy"] == strat]
        strat_overall = compute_bucket_stats(strat_records)
        print(f"Total: {strat_overall['n']} trades | Win: {strat_overall['win_rate']:.1f}% | Avg PnL: {strat_overall['avg_pnl']:.2f}%")
        print()
        print(header)
        print("-" * 60)

        for bucket_name in bucket_order:
            recs = [r for r in strat_records if r["bucket"] == bucket_name]
            s = compute_bucket_stats(recs)
            if s["n"] > 0:
                print(f"{bucket_name:<22} {s['n']:>6} {s['win_rate']:>7.1f}% {s['avg_pnl']:>+8.2f}% {s['median_pnl']:>+8.2f}%")
            else:
                print(f"{bucket_name:<22} {0:>6}       -         -         -")

    # ── Correlation analysis ─────────────────────────────────────────
    print(f"\n{'=' * 90}")
    print("CORRELATION: SENTIMENT vs P&L")
    print("=" * 90)

    # All trades
    sentiments = np.array([r["sentiment"] for r in trade_results])
    pnls = np.array([r["pnl"] for r in trade_results])

    # Only non-zero sentiment for correlation (zero = no data, not neutral)
    mask = sentiments != 0.0
    if mask.sum() >= 5:
        s_nz = sentiments[mask]
        p_nz = pnls[mask]

        pearson_r, pearson_p = stats.pearsonr(s_nz, p_nz)
        spearman_r, spearman_p = stats.spearmanr(s_nz, p_nz)

        print(f"\nNon-zero sentiment trades: {mask.sum()}")
        print(f"Pearson  r = {pearson_r:+.4f}  (p = {pearson_p:.4f})")
        print(f"Spearman r = {spearman_r:+.4f}  (p = {spearman_p:.4f})")

        if pearson_p < 0.05:
            print("  → Pearson correlation is statistically significant (p < 0.05)")
        else:
            print("  → Pearson correlation is NOT statistically significant")

        if spearman_p < 0.05:
            print("  → Spearman correlation is statistically significant (p < 0.05)")
        else:
            print("  → Spearman correlation is NOT statistically significant")

        # Per-strategy correlation
        for strat in strategies:
            strat_mask = np.array([r["strategy"] == strat for r in trade_results])
            combined = mask & strat_mask
            if combined.sum() >= 5:
                s_s = sentiments[combined]
                p_s = pnls[combined]
                pr, pp = stats.pearsonr(s_s, p_s)
                sr, sp = stats.spearmanr(s_s, p_s)
                print(f"\n  {strat}: n={combined.sum()}")
                print(f"    Pearson  r = {pr:+.4f}  (p = {pp:.4f})")
                print(f"    Spearman r = {sr:+.4f}  (p = {sp:.4f})")
    else:
        print(f"\nInsufficient non-zero sentiment trades ({mask.sum()}) for correlation analysis.")
        print("Need at least 5 trades with non-zero sentiment.")

    # ── Sentiment as win-rate predictor ───────────────────────────────
    print(f"\n{'=' * 90}")
    print("SENTIMENT AS WIN-RATE PREDICTOR")
    print("=" * 90)

    # Compare trades with sentiment vs without
    with_sent = [r for r in trade_results if r["sentiment"] != 0.0]
    without_sent = [r for r in trade_results if r["sentiment"] == 0.0]

    ws = compute_bucket_stats(with_sent)
    wos = compute_bucket_stats(without_sent)

    print(f"{'Group':<30} {'N':>6} {'Win%':>8} {'AvgPnL':>9} {'MedPnL':>9}")
    print("-" * 68)
    print(f"{'With sentiment data':<30} {ws['n']:>6} {ws['win_rate']:>7.1f}% {ws['avg_pnl']:>+8.2f}% {ws['median_pnl']:>+8.2f}%")
    if wos["n"] > 0:
        print(f"{'Without sentiment data':<30} {wos['n']:>6} {wos['win_rate']:>7.1f}% {wos['avg_pnl']:>+8.2f}% {wos['median_pnl']:>+8.2f}%")

    # Bullish vs bearish
    bullish = [r for r in trade_results if r["sentiment"] > 0]
    bearish = [r for r in trade_results if r["sentiment"] < 0]
    bs = compute_bucket_stats(bullish)
    brs = compute_bucket_stats(bearish)

    print()
    if bs["n"] > 0:
        print(f"{'Bullish sentiment (>0)':<30} {bs['n']:>6} {bs['win_rate']:>7.1f}% {bs['avg_pnl']:>+8.2f}% {bs['median_pnl']:>+8.2f}%")
    if brs["n"] > 0:
        print(f"{'Bearish sentiment (<0)':<30} {brs['n']:>6} {brs['win_rate']:>7.1f}% {brs['avg_pnl']:>+8.2f}% {brs['median_pnl']:>+8.2f}%")

    # ── Export CSV ────────────────────────────────────────────────────
    csv_path = Path("src/logs/sentiment_impact.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "batch_date", "symbol", "strategy", "sentiment", "bucket",
            "outcome", "pnl", "days_held", "entry_price", "stop_loss",
            "take_profit", "composite_score",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in trade_results:
            writer.writerow(r)

    print(f"\nResults exported to {csv_path}")
    print("=" * 90)


if __name__ == "__main__":
    run_analysis()
