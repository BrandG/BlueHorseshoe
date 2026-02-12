#!/bin/bash

# Phase 3E Testing Script - Advanced Momentum & Trend Indicators
# Tests: ADX, Stochastic, CCI, Williams %R, Ichimoku, PSAR, SuperTrend
# 7 indicators × 4 weights × 20 runs = 560 total backtests
# Estimated runtime: 25-30 hours

set -e

# Configuration
PYTHON_CMD="docker exec bluehorseshoe python src/run_phase3_testing.py"
LOG_FILE="src/logs/phase3e_test_run.log"
BACKTEST_LOG="src/logs/phase3e_backtest_log.csv"
WEIGHTS_FILE="src/weights.json"
WEIGHTS_BACKUP="src/weights.json.phase3e_backup"

echo "==================================================" | tee -a "$LOG_FILE"
echo "Phase 3E Testing - Advanced Momentum & Trend" | tee -a "$LOG_FILE"
echo "Start Time: $(date)" | tee -a "$LOG_FILE"
echo "==================================================" | tee -a "$LOG_FILE"

# Backup current weights
echo "Backing up current weights to $WEIGHTS_BACKUP" | tee -a "$LOG_FILE"
cp "$WEIGHTS_FILE" "$WEIGHTS_BACKUP"

# Initialize or clear the backtest log
if [ ! -f "$BACKTEST_LOG" ]; then
    echo "date,symbol,strategy,score,ml_prob,entry,stop_loss,take_profit,exit_price,exit_date,days_held,status,outcome,profit_loss" > "$BACKTEST_LOG"
fi

# Test counter
TEST_NUM=1
TOTAL_TESTS=560

# Indicator list with categories
declare -A INDICATORS
INDICATORS[ADX]="momentum"
INDICATORS[STOCHASTIC]="momentum"
INDICATORS[CCI]="momentum"
INDICATORS[WILLIAMS_R]="momentum"
INDICATORS[ICHIMOKU]="trend"
INDICATORS[PSAR]="trend"
INDICATORS[SUPERTREND]="trend"

# Weight levels to test
WEIGHTS=(0.5 1.0 1.5 2.0)

# Number of runs per configuration
RUNS_PER_CONFIG=20

echo "" | tee -a "$LOG_FILE"
echo "Test Matrix:" | tee -a "$LOG_FILE"
echo "- Indicators: 7 (ADX, Stochastic, CCI, Williams %R, Ichimoku, PSAR, SuperTrend)" | tee -a "$LOG_FILE"
echo "- Weights per indicator: 4 (0.5x, 1.0x, 1.5x, 2.0x)" | tee -a "$LOG_FILE"
echo "- Runs per configuration: $RUNS_PER_CONFIG" | tee -a "$LOG_FILE"
echo "- Total backtests: $TOTAL_TESTS" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Main testing loop
for indicator in "${!INDICATORS[@]}"; do
    CATEGORY="${INDICATORS[$indicator]}"

    echo "=================================================" | tee -a "$LOG_FILE"
    echo "Testing: $indicator (Category: $CATEGORY)" | tee -a "$LOG_FILE"
    echo "=================================================" | tee -a "$LOG_FILE"

    for weight in "${WEIGHTS[@]}"; do
        echo "" | tee -a "$LOG_FILE"
        echo "Configuration: ${indicator}_MULTIPLIER = $weight" | tee -a "$LOG_FILE"
        echo "Running $RUNS_PER_CONFIG backtests..." | tee -a "$LOG_FILE"

        # Run the tests
        RUN_START=$(date +%s)

        $PYTHON_CMD \
            --indicator "$indicator" \
            --weight "$weight" \
            --runs "$RUNS_PER_CONFIG" \
            2>&1 | tee -a "$LOG_FILE"

        RUN_END=$(date +%s)
        RUN_DURATION=$((RUN_END - RUN_START))

        echo "Configuration completed in ${RUN_DURATION}s" | tee -a "$LOG_FILE"
        echo "Progress: $TEST_NUM/$TOTAL_TESTS tests completed ($(echo "scale=1; $TEST_NUM * 100 / $TOTAL_TESTS" | bc)%)" | tee -a "$LOG_FILE"

        TEST_NUM=$((TEST_NUM + RUNS_PER_CONFIG))
    done

    echo "" | tee -a "$LOG_FILE"
    echo "$indicator testing complete!" | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
done

# Final summary
echo "==================================================" | tee -a "$LOG_FILE"
echo "Phase 3E Testing Complete!" | tee -a "$LOG_FILE"
echo "End Time: $(date)" | tee -a "$LOG_FILE"
echo "==================================================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"
echo "Results saved to: $BACKTEST_LOG" | tee -a "$LOG_FILE"
echo "Weights backup at: $WEIGHTS_BACKUP" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"
echo "Next Steps:" | tee -a "$LOG_FILE"
echo "1. Run: python src/analyze_phase3e.py" | tee -a "$LOG_FILE"
echo "2. Review top performers by Sharpe ratio" | tee -a "$LOG_FILE"
echo "3. Deploy winners to weights.json" | tee -a "$LOG_FILE"
echo "4. Commit results to git" | tee -a "$LOG_FILE"

echo "" | tee -a "$LOG_FILE"
echo "Phase 3E testing completed successfully!" | tee -a "$LOG_FILE"
