#!/bin/bash

# Phase 3E Quarter 4: SuperTrend
# 1 indicator × 4 weights × 20 runs = 80 backtests
# Estimated runtime: 3-4 hours

set -e

echo "================================================================"
echo "Phase 3E Quarter 4: SuperTrend"
echo "Start Time: $(date)"
echo "================================================================"
echo ""

# Test SuperTrend at all weights
echo "Testing SUPERTREND (SuperTrend Indicator)..."
docker exec bluehorseshoe python src/run_phase3_testing.py --indicator SUPERTREND --runs 20
echo ""

echo "================================================================"
echo "Phase 3E Quarter 4 Complete!"
echo "End Time: $(date)"
echo "================================================================"
echo ""
echo "Phase 3E FULLY COMPLETE - All 7 indicators tested!"
echo ""
echo "Results saved to: src/logs/phase3a_backtest_log.csv"
echo ""
echo "Next Steps:"
echo "1. Analyze all results: python src/analyze_phase3e_full.py"
echo "2. Review top performers by Sharpe ratio"
echo "3. Deploy winners to weights.json"
echo "4. Update system from 14 to 17-21 indicators"
echo "5. Commit Phase 3E results to git"
