#!/bin/bash

# Phase 3E Quarter 2: CCI, Williams %R
# 2 indicators × 4 weights × 20 runs = 160 backtests
# Estimated runtime: 6-7 hours

set -e

echo "================================================================"
echo "Phase 3E Quarter 2: CCI + Williams %R"
echo "Start Time: $(date)"
echo "================================================================"
echo ""

# Test CCI at all weights
echo "Testing CCI (Commodity Channel Index)..."
docker exec bluehorseshoe python src/run_phase3_testing.py --indicator CCI --runs 20
echo ""

# Test Williams %R at all weights
echo "Testing WILLIAMS_R (Williams %R)..."
docker exec bluehorseshoe python src/run_phase3_testing.py --indicator WILLIAMS_R --runs 20
echo ""

echo "================================================================"
echo "Phase 3E Quarter 2 Complete!"
echo "End Time: $(date)"
echo "================================================================"
echo ""
echo "Results saved to: src/logs/phase3a_backtest_log.csv"
echo ""
echo "Next Steps:"
echo "1. Analyze: python src/analyze_phase3e_q2.py"
echo "2. Review results before proceeding to Quarter 3"
echo "3. If good, run: ./src/run_phase3e_q3.sh"
