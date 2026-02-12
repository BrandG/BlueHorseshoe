#!/bin/bash

# Phase 3E Quarter 1: ADX, Stochastic
# 2 indicators × 4 weights × 20 runs = 160 backtests
# Estimated runtime: 6-7 hours

set -e

echo "================================================================"
echo "Phase 3E Quarter 1: ADX + Stochastic"
echo "Start Time: $(date)"
echo "================================================================"
echo ""

# Test ADX at all weights
echo "Testing ADX (Average Directional Index)..."
docker exec bluehorseshoe python src/run_phase3_testing.py --indicator ADX --runs 20
echo ""

# Test Stochastic at all weights
echo "Testing STOCHASTIC (Stochastic Oscillator)..."
docker exec bluehorseshoe python src/run_phase3_testing.py --indicator STOCHASTIC --runs 20
echo ""

echo "================================================================"
echo "Phase 3E Quarter 1 Complete!"
echo "End Time: $(date)"
echo "================================================================"
echo ""
echo "Results saved to: src/logs/phase3a_backtest_log.csv"
echo ""
echo "Next Steps:"
echo "1. Analyze: python src/analyze_phase3e_q1.py"
echo "2. Review results before proceeding to Quarter 2"
echo "3. If good, run: ./src/run_phase3e_q2.sh"
