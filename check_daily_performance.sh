#!/bin/bash
##############################################################################
# Daily Performance Check - Dynamic Entry Strategy
#
# This script analyzes the previous day's prediction results to monitor
# the dynamic entry strategy's performance and signal distribution.
#
# Usage:
#   ./check_daily_performance.sh           # Check yesterday
#   ./check_daily_performance.sh 2026-02-02  # Check specific date
##############################################################################

set -e

# Determine date to check
if [ -z "$1" ]; then
    # Default to yesterday if no argument provided
    CHECK_DATE=$(date +%Y-%m-%d -d "yesterday")
else
    CHECK_DATE=$1
fi

echo "========================================================================"
echo "DYNAMIC ENTRY STRATEGY - DAILY PERFORMANCE CHECK"
echo "========================================================================"
echo "Date: $CHECK_DATE"
echo "Report Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Check if Docker container is running
if ! docker ps | grep -q bluehorseshoe; then
    echo "❌ ERROR: BlueHorseshoe container is not running"
    echo "   Start with: cd docker && docker compose up -d"
    exit 1
fi

echo "--- Signal Strength Distribution ---"
docker exec bluehorseshoe python -c "
from bluehorseshoe.core.container import create_app_container
from bluehorseshoe.core.scores import ScoreManager
from collections import Counter

container = create_app_container()
try:
    db = container.get_database()
    score_manager = ScoreManager(database=db)

    # Get scores for target date
    scores = score_manager.get_scores('$CHECK_DATE', strategy='baseline')

    if not scores:
        print('⚠️  No scores found for $CHECK_DATE')
        print('   Run prediction with: docker exec bluehorseshoe python src/main.py -p')
        exit(0)

    print(f'Total Candidates: {len(scores)}')
    print()

    # Extract signal strengths and scores
    signal_strengths = []
    atr_discounts = []
    score_values = []

    for s in scores:
        metadata = s.get('metadata', {})
        strength = metadata.get('signal_strength', 'UNKNOWN')
        if strength != 'UNKNOWN':  # Only count candidates with valid strength
            signal_strengths.append(strength)
            atr_discounts.append(metadata.get('atr_discount_used', 0.20))
            score_values.append(s.get('score', 0))

    if not signal_strengths:
        print('⚠️  No candidates with valid signal strength')
        exit(0)

    # Count distribution
    strength_dist = Counter(signal_strengths)

    print('Signal Tier       Count    %      ATR Discount   Notes')
    print('─────────────────────────────────────────────────────────────')

    tiers = [
        ('EXTREME', '≥20', 0.05, '🔥 Best opportunities - most aggressive'),
        ('HIGH', '≥14.5', 0.10, '⭐ Strong signals - aggressive entry'),
        ('MEDIUM', '≥7', 0.20, '✓ Good signals - baseline entry'),
        ('LOW', '≥2', 0.35, '⚠️  Weak signals - conservative entry'),
        ('WEAK', '<2', 0.50, '❌ Poor signals - very conservative')
    ]

    for tier_name, threshold, discount, note in tiers:
        count = strength_dist.get(tier_name, 0)
        pct = (count / len(signal_strengths) * 100) if signal_strengths else 0
        print(f'{tier_name:10} {threshold:>6}   {count:4}   {pct:5.1f}%   {discount:.2f}x ATR      {note}')

    print()
    print('─────────────────────────────────────────────────────────────')
    print(f'Valid Candidates: {len(signal_strengths):,}')
    print()

    # Score statistics
    if score_values:
        print('--- Score Statistics ---')
        print(f'Min Score:  {min(score_values):6.2f}')
        print(f'Max Score:  {max(score_values):6.2f}')
        print(f'Avg Score:  {sum(score_values)/len(score_values):6.2f}')
        print(f'Median:     {sorted(score_values)[len(score_values)//2]:6.2f}')
        print()

    # Top candidates
    print('--- Top 10 Candidates ---')
    sorted_scores = sorted(scores, key=lambda x: x.get('score', 0), reverse=True)[:10]
    print(f'{\"Symbol\":8} {\"Score\":>6} {\"Tier\":10} {\"Discount\":>8} {\"ML Win%\":>8}')
    print('─' * 50)
    for s in sorted_scores:
        symbol = s.get('symbol', 'N/A')[:8]
        score = s.get('score', 0)
        strength = s.get('metadata', {}).get('signal_strength', 'N/A')
        discount = s.get('metadata', {}).get('atr_discount_used', 0.20)
        ml_prob = s.get('metadata', {}).get('ml_win_prob', 0) * 100
        print(f'{symbol:8} {score:6.2f} {strength:10} {discount:8.2f} {ml_prob:7.1f}%')

    print()

    # Market quality assessment
    extreme_high = strength_dist.get('EXTREME', 0) + strength_dist.get('HIGH', 0)
    medium = strength_dist.get('MEDIUM', 0)
    low_weak = strength_dist.get('LOW', 0) + strength_dist.get('WEAK', 0)

    print('--- Market Quality Assessment ---')
    if extreme_high > 0:
        print('🔥 EXCELLENT: Strong signals detected! Dynamic entry providing maximum benefit.')
    elif medium > len(signal_strengths) * 0.20:
        print('⭐ GOOD: Healthy number of medium-quality signals.')
    elif low_weak > len(signal_strengths) * 0.50:
        print('⚠️  WEAK: Market dominated by low-quality signals. Strategy being appropriately conservative.')
    else:
        print('✓ NORMAL: Mixed signal quality. Strategy adapting appropriately.')

finally:
    container.close()
" 2>&1

echo ""
echo "========================================================================"
echo "Next Steps:"
echo "  • View full report: docker exec bluehorseshoe ls -lh src/logs/report_$CHECK_DATE.html"
echo "  • Run prediction: docker exec bluehorseshoe python src/main.py -p"
echo "  • Analyze specific symbol: docker exec bluehorseshoe python src/main.py -p [SYMBOL]"
echo "========================================================================"
