#!/usr/bin/env python
"""
Analyze dynamic entry discount distribution and performance.

This script examines saved scores to verify that the dynamic entry strategy
is working correctly and distributing discounts across signal strength tiers.

Usage:
    python src/analyze_entry_discounts.py [DATE]

    If DATE is not provided, uses the most recent date with saved scores.
"""
import sys
from collections import Counter
from typing import Dict, List, Any
from bluehorseshoe.core.scores import ScoreManager
from bluehorseshoe.core.container import create_app_container


def analyze_discount_distribution(scores: List[Dict[str, Any]], strategy: str) -> None:
    """
    Analyze and display discount distribution for a strategy.

    Args:
        scores: List of score dictionaries
        strategy: Strategy name (baseline or mean_reversion)
    """
    if not scores:
        print(f"\nNo {strategy} scores found.")
        return

    print(f"\n{'='*70}")
    print(f"{strategy.upper()} STRATEGY ANALYSIS")
    print(f"{'='*70}")

    # Count signal strength distribution
    strength_counter = Counter()
    discount_counter = Counter()

    for score in scores:
        metadata = score.get('metadata', {})
        strength = metadata.get('signal_strength', 'UNKNOWN')
        discount = metadata.get('atr_discount_used', 0.20)

        strength_counter[strength] += 1
        discount_counter[discount] += 1

    # Display signal strength distribution
    print("\n--- Signal Strength Distribution ---")
    print(f"{'Strength':<12} {'Count':<8} {'Percentage':<12}")
    print("-" * 35)

    total = len(scores)
    for strength in ['EXTREME', 'HIGH', 'MEDIUM', 'LOW', 'WEAK', 'UNKNOWN']:
        count = strength_counter.get(strength, 0)
        pct = (count / total * 100) if total > 0 else 0
        print(f"{strength:<12} {count:<8} {pct:>6.1f}%")

    print(f"\nTotal Trades: {total}")

    # Display discount distribution
    print("\n--- ATR Discount Distribution ---")
    print(f"{'Discount':<12} {'Count':<8} {'Percentage':<12}")
    print("-" * 35)

    for discount in sorted(discount_counter.keys()):
        count = discount_counter[discount]
        pct = (count / total * 100) if total > 0 else 0
        print(f"{discount:<12.2f} {count:<8} {pct:>6.1f}%")

    # Display sample trades
    print("\n--- Sample Trades (First 10) ---")
    print(f"{'Symbol':<8} {'Score':<8} {'Strength':<12} {'Discount':<10} {'Entry':<10}")
    print("-" * 60)

    for score in scores[:10]:
        symbol = score.get('symbol', 'N/A')
        trade_score = score.get('score', 0)
        metadata = score.get('metadata', {})
        strength = metadata.get('signal_strength', 'UNKNOWN')
        discount = metadata.get('atr_discount_used', 0.20)
        entry = metadata.get('entry_price', 0)

        print(f"{symbol:<8} {trade_score:<8.1f} {strength:<12} {discount:<10.2f} ${entry:<9.2f}")

    # Verify discount correctness
    print("\n--- Discount Verification ---")
    expected_discounts = {
        'EXTREME': 0.05,
        'HIGH': 0.10,
        'MEDIUM': 0.20,
        'LOW': 0.35,
        'WEAK': 0.50
    }

    mismatches = 0
    for score in scores:
        metadata = score.get('metadata', {})
        strength = metadata.get('signal_strength', 'UNKNOWN')
        actual_discount = metadata.get('atr_discount_used', 0.20)
        expected_discount = expected_discounts.get(strength, 0.20)

        if abs(actual_discount - expected_discount) > 0.001:
            mismatches += 1
            if mismatches <= 5:  # Show first 5 mismatches
                symbol = score.get('symbol', 'N/A')
                print(f"MISMATCH: {symbol} - Strength: {strength}, "
                      f"Expected: {expected_discount:.2f}, Actual: {actual_discount:.2f}")

    if mismatches == 0:
        print("✓ All discounts match expected values")
    else:
        print(f"\n⚠ Found {mismatches} discount mismatches")


def analyze_score_distribution(scores: List[Dict[str, Any]], strategy: str) -> None:
    """
    Analyze score distribution to understand signal quality.

    Args:
        scores: List of score dictionaries
        strategy: Strategy name
    """
    if not scores:
        return

    print(f"\n--- Score Distribution ({strategy}) ---")

    score_values = [s.get('score', 0) for s in scores]

    # Calculate statistics
    min_score = min(score_values)
    max_score = max(score_values)
    avg_score = sum(score_values) / len(score_values)

    # Count by ranges
    ranges = {
        '80+': sum(1 for s in score_values if s >= 80),
        '60-79': sum(1 for s in score_values if 60 <= s < 80),
        '40-59': sum(1 for s in score_values if 40 <= s < 60),
        '20-39': sum(1 for s in score_values if 20 <= s < 40),
        '<20': sum(1 for s in score_values if s < 20),
    }

    print(f"Min Score:  {min_score:.1f}")
    print(f"Max Score:  {max_score:.1f}")
    print(f"Avg Score:  {avg_score:.1f}")
    print(f"\nScore Ranges:")
    for range_name, count in ranges.items():
        pct = (count / len(scores) * 100) if scores else 0
        print(f"  {range_name:<10} {count:>4} ({pct:>5.1f}%)")


def main():
    """Main analysis function."""
    # Get target date from command line or use None for latest
    target_date = sys.argv[1] if len(sys.argv) > 1 else None

    print("="*70)
    print("DYNAMIC ENTRY DISCOUNT ANALYSIS")
    print("="*70)

    container = create_app_container()
    try:
        score_manager = ScoreManager(database=container.get_database())

        # If no date specified, find the latest date
        if target_date is None:
            # Try to get any scores and extract date
            all_scores = list(container.get_database().scores.find().sort('date', -1).limit(1))
            if all_scores:
                target_date = all_scores[0].get('date')
                print(f"\nUsing latest date: {target_date}")
            else:
                print("\nERROR: No scores found in database.")
                return 1
        else:
            print(f"\nAnalyzing date: {target_date}")

        # Fetch scores
        baseline_scores = score_manager.get_scores(target_date, strategy='baseline')
        mr_scores = score_manager.get_scores(target_date, strategy='mean_reversion')

        # Analyze baseline strategy
        if baseline_scores:
            analyze_discount_distribution(baseline_scores, 'baseline')
            analyze_score_distribution(baseline_scores, 'baseline')
        else:
            print("\nNo baseline scores found for this date.")

        # Analyze mean reversion strategy
        if mr_scores:
            analyze_discount_distribution(mr_scores, 'mean_reversion')
            analyze_score_distribution(mr_scores, 'mean_reversion')
        else:
            print("\nNo mean reversion scores found for this date.")

        # Summary
        print("\n" + "="*70)
        print("SUMMARY")
        print("="*70)
        print(f"Date:                 {target_date}")
        print(f"Baseline Trades:      {len(baseline_scores)}")
        print(f"Mean Reversion Trades: {len(mr_scores)}")
        print(f"Total Trades:         {len(baseline_scores) + len(mr_scores)}")

        if baseline_scores:
            extreme_count = sum(
                1 for s in baseline_scores
                if s.get('metadata', {}).get('signal_strength') == 'EXTREME'
            )
            print(f"\nExtreme Signals (80+): {extreme_count} "
                  f"({extreme_count/len(baseline_scores)*100:.1f}% of baseline)")

        print("\n" + "="*70)

        return 0
    finally:
        container.close()


if __name__ == '__main__':
    sys.exit(main())
