#!/bin/bash
# Phase 3C Testing - MACD and MACD Signal
# Estimated time: 6-8 hours

RUNS=20
SAMPLE_SIZE=1000

INDICATORS=("MACD" "MACD_SIGNAL")

echo "=========================================="
echo "Phase 3C Testing"
echo "=========================================="
echo "Indicators: 2 (MACD, MACD Signal)"
echo "Runs per indicator: $RUNS x 4 weights = 80 backtests"
echo "Sample size: $SAMPLE_SIZE symbols"
echo "Total backtests: 160"
echo "Estimated time: 6-8 hours"
echo "=========================================="
echo ""
echo "Start time: $(date)"
echo ""

START_TIME=$(date +%s)

for indicator in "${INDICATORS[@]}"; do
    echo ""
    echo "========================================"
    echo "Starting indicator: $indicator"
    echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
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

    echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
done

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
HOURS=$((DURATION / 3600))
MINUTES=$(((DURATION % 3600) / 60))

echo ""
echo "========================================"
echo "Phase 3C Testing Complete"
echo "========================================"
echo "Total time: ${HOURS}h ${MINUTES}m"
echo "Results: src/logs/backtest_log.csv"
echo "End time: $(date)"
echo "========================================"
