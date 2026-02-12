#!/bin/bash
# Phase 3D Testing - Candlestick Patterns
# Estimated time: 6-8 hours

RUNS=20
SAMPLE_SIZE=1000

INDICATORS=("RISE_FALL" "THREE_SOLDIERS" "BELT_HOLD")

LOG_FILE="src/logs/phase3d_test_run.log"

echo "==========================================" | tee "$LOG_FILE"
echo "Phase 3D Testing" | tee -a "$LOG_FILE"
echo "==========================================" | tee -a "$LOG_FILE"
echo "Indicators: 3 (Rise/Fall Three Methods, Three White Soldiers, Belt Hold)" | tee -a "$LOG_FILE"
echo "Runs per indicator: $RUNS x 4 weights = 80 backtests" | tee -a "$LOG_FILE"
echo "Sample size: $SAMPLE_SIZE symbols" | tee -a "$LOG_FILE"
echo "Total backtests: 240" | tee -a "$LOG_FILE"
echo "Estimated time: 6-8 hours" | tee -a "$LOG_FILE"
echo "==========================================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"
echo "Start time: $(date)" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

START_TIME=$(date +%s)

for indicator in "${INDICATORS[@]}"; do
    echo "" | tee -a "$LOG_FILE"
    echo "========================================" | tee -a "$LOG_FILE"
    echo "Starting indicator: $indicator" | tee -a "$LOG_FILE"
    echo "Time: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
    echo "========================================" | tee -a "$LOG_FILE"

    python src/run_phase3_testing.py \
        --indicator "$indicator" \
        --runs "$RUNS" \
        --sample-size "$SAMPLE_SIZE" 2>&1 | tee -a "$LOG_FILE"

    if [ $? -eq 0 ]; then
        echo "✅ $indicator completed successfully" | tee -a "$LOG_FILE"
    else
        echo "❌ $indicator failed" | tee -a "$LOG_FILE"
    fi

    echo "Time: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
done

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
HOURS=$((DURATION / 3600))
MINUTES=$(((DURATION % 3600) / 60))

echo "" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
echo "Phase 3D Testing Complete" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
echo "Total time: ${HOURS}h ${MINUTES}m" | tee -a "$LOG_FILE"
echo "Results: src/logs/phase3d_backtest_log.csv" | tee -a "$LOG_FILE"
echo "End time: $(date)" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
