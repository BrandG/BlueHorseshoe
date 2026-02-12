#!/bin/bash

# Phase 3E Quarter 3: Ichimoku, PSAR
# 2 indicators × 4 weights × 20 runs = 160 backtests
# Estimated runtime: 6-7 hours

set -e

echo "================================================================"
echo "Phase 3E Quarter 3: Ichimoku + PSAR"
echo "Start Time: $(date)"
echo "================================================================"
echo ""

# Test Ichimoku at all weights
echo "Testing ICHIMOKU (Ichimoku Cloud)..."
docker exec bluehorseshoe python src/run_phase3_testing.py --indicator ICHIMOKU --runs 20
echo ""

# Test PSAR at all weights
echo "Testing PSAR (Parabolic SAR)..."
docker exec bluehorseshoe python src/run_phase3_testing.py --indicator PSAR --runs 20
echo ""

echo "================================================================"
echo "Phase 3E Quarter 3 Complete!"
echo "End Time: $(date)"
echo "================================================================"
echo ""
echo "Results saved to: src/logs/phase3a_backtest_log.csv"
echo ""
echo "Next Steps:"
echo "1. Analyze: python src/analyze_phase3e_q3.py"
echo "2. Review results before proceeding to Quarter 4"
echo "3. If good, run: ./src/run_phase3e_q4.sh"
