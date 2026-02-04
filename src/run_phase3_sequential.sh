#!/bin/bash
# Run Phase 3A testing sequentially to avoid resource contention
# Tests all 8 indicators one at a time

RUNS=20
SAMPLE_SIZE=500

INDICATORS=("RS" "GAP" "VWAP" "TTM" "AROON" "KELTNER" "FORCE" "AD")

echo "=================================="
echo "Phase 3A Sequential Testing"
echo "=================================="
echo "Indicators: 8"
echo "Runs per indicator: $RUNS x 4 weights = 80 backtests"
echo "Sample size: $SAMPLE_SIZE symbols"
echo "=================================="
echo ""

START_TIME=$(date +%s)

for indicator in "${INDICATORS[@]}"; do
    echo ""
    echo "========================================"
    echo "Starting indicator: $indicator"
    echo "========================================"

    python src/run_phase3_testing.py \
        --indicator "$indicator" \
        --runs "$RUNS" \
        --sample-size "$SAMPLE_SIZE"

    if [ $? -eq 0 ]; then
        echo "✅ $indicator completed successfully"
    else
        echo "❌ $indicator failed"
    fi
    echo ""
done

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo "========================================"
echo "Phase 3A Sequential Testing Complete"
echo "========================================"
echo "Total time: $DURATION seconds"
echo "Results: src/logs/backtest_log.csv"
echo "========================================"
