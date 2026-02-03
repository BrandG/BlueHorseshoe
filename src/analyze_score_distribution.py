#!/usr/bin/env python
"""Analyze score distribution to determine optimal thresholds."""
from bluehorseshoe.core.container import create_app_container
import pandas as pd

container = create_app_container()
db = container.get_database()

# Get all baseline scores
scores = list(db.trade_scores.find(
    {'strategy': 'baseline'},
    {'score': 1}
))

score_values = [s['score'] for s in scores if s.get('score') is not None]

print("="*70)
print("BASELINE SCORE DISTRIBUTION ANALYSIS")
print("="*70)

print(f"\nTotal Baseline Signals: {len(score_values)}")

# Calculate percentiles
percentiles = [50, 60, 70, 75, 80, 85, 90, 95, 97, 98, 99, 99.5, 100]
print(f"\n{'Percentile':<12} {'Score':<10} {'Interpretation'}")
print("-" * 50)

for p in percentiles:
    if p == 100:
        score = max(score_values)
    else:
        score = pd.Series(score_values).quantile(p/100)

    if p >= 99:
        tier = "Top 1% - EXTREME"
    elif p >= 95:
        tier = "Top 5% - HIGH"
    elif p >= 80:
        tier = "Top 20% - MEDIUM"
    elif p >= 60:
        tier = "Top 40% - LOW"
    else:
        tier = "Bottom 50% - WEAK"

    print(f"{p:<12.1f} {score:<10.1f} {tier}")

# Score range distribution
print("\n" + "="*70)
print("RECOMMENDED THRESHOLD ADJUSTMENTS")
print("="*70)

p99 = pd.Series(score_values).quantile(0.99)
p95 = pd.Series(score_values).quantile(0.95)
p80 = pd.Series(score_values).quantile(0.80)
p60 = pd.Series(score_values).quantile(0.60)

print(f"\nCurrent Thresholds:")
print("  EXTREME: 80+  (NEVER REACHED)")
print("  HIGH:    60+  (NEVER REACHED)")
print("  MEDIUM:  40+  (NEVER REACHED)")
print("  LOW:     20+  (Most high-quality signals)")
print("  WEAK:    <20  (Majority of signals)")

print(f"\nSuggested Thresholds (based on actual distribution):")
print(f"  EXTREME: {p99:.1f}+  (Top 1% - best setups)")
print(f"  HIGH:    {p95:.1f}+  (Top 5% - strong setups)")
print(f"  MEDIUM:  {p80:.1f}+  (Top 20% - good setups)")
print(f"  LOW:     {p60:.1f}+  (Top 40% - weak setups)")
print(f"  WEAK:    <{p60:.1f}  (Bottom 60% - very weak)")

# Suggested discount mapping
print(f"\nSuggested ATR Discount Mapping:")
print(f"  EXTREME ({p99:.1f}+):  0.05 (very aggressive - top 1%)")
print(f"  HIGH ({p95:.1f}-{p99:.1f}):     0.10 (aggressive - top 5%)")
print(f"  MEDIUM ({p80:.1f}-{p95:.1f}):   0.20 (current default)")
print(f"  LOW ({p60:.1f}-{p80:.1f}):      0.35 (conservative)")
print(f"  WEAK (<{p60:.1f}):     0.50 (very conservative)")

# Count in each proposed tier
print(f"\n" + "="*70)
print("SIGNAL DISTRIBUTION WITH SUGGESTED THRESHOLDS")
print("="*70)

tiers = {
    'EXTREME': [s for s in score_values if s >= p99],
    'HIGH': [s for s in score_values if p95 <= s < p99],
    'MEDIUM': [s for s in score_values if p80 <= s < p95],
    'LOW': [s for s in score_values if p60 <= s < p80],
    'WEAK': [s for s in score_values if s < p60]
}

total = len(score_values)
print(f"\n{'Tier':<12} {'Count':<10} {'Percentage':<12} {'Score Range'}")
print("-" * 55)
for tier_name in ['EXTREME', 'HIGH', 'MEDIUM', 'LOW', 'WEAK']:
    count = len(tiers[tier_name])
    pct = (count / total * 100) if total > 0 else 0
    if count > 0:
        min_score = min(tiers[tier_name])
        max_score = max(tiers[tier_name])
        score_range = f"{min_score:.1f} - {max_score:.1f}"
    else:
        score_range = "N/A"
    print(f"{tier_name:<12} {count:<10} {pct:>6.1f}%      {score_range}")

container.close()
