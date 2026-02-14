#!/bin/bash
#
# backfill_predictions_for_training.sh
#
# Generates predictions on historical dates to quickly accumulate graded trades
# for training the ML profit target models.
#
# This script:
# 1. Runs predictions on 20-30 past trading dates
# 2. Each prediction is immediately gradable (future data exists)
# 3. Provides enough samples to train profit target models
#
# Usage: ./backfill_predictions_for_training.sh [start_date] [num_dates]
#   start_date: Starting date (YYYY-MM-DD), defaults to 2026-01-06
#   num_dates: Number of dates to process, defaults to 25

set -e  # Exit on error

# Configuration
START_DATE=${1:-"2026-01-06"}  # Default: Start of January 2026
NUM_DATES=${2:-25}             # Default: 25 trading dates
CONTAINER="bluehorseshoe"
LOG_FILE="/root/BlueHorseshoe/src/logs/backfill_predictions.log"

echo "======================================================================="
echo "BACKFILLING PREDICTIONS FOR ML TRAINING"
echo "======================================================================="
echo "Start Date: $START_DATE"
echo "Number of Dates: $NUM_DATES"
echo "Log File: $LOG_FILE"
echo "======================================================================="
echo ""

# Create log file
mkdir -p "$(dirname "$LOG_FILE")"
echo "Backfill started at $(date)" > "$LOG_FILE"
echo "Start Date: $START_DATE" >> "$LOG_FILE"
echo "Number of Dates: $NUM_DATES" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# Function to get next trading date (skips weekends)
get_next_trading_date() {
    local current_date=$1
    local next_date=$(date -d "$current_date + 1 day" +%Y-%m-%d)
    local day_of_week=$(date -d "$next_date" +%u)

    # Skip weekends (6=Saturday, 7=Sunday)
    while [ "$day_of_week" -eq 6 ] || [ "$day_of_week" -eq 7 ]; do
        next_date=$(date -d "$next_date + 1 day" +%Y-%m-%d)
        day_of_week=$(date -d "$next_date" +%u)
    done

    echo "$next_date"
}

# Generate list of trading dates
current_date=$START_DATE
dates_processed=0
success_count=0
failed_dates=()

echo "Generating predictions for historical dates..."
echo ""

while [ $dates_processed -lt $NUM_DATES ]; do
    dates_processed=$((dates_processed + 1))

    echo "[$dates_processed/$NUM_DATES] Processing $current_date..."
    echo "[$dates_processed/$NUM_DATES] Processing $current_date..." >> "$LOG_FILE"

    # Run prediction for this date
    if docker exec $CONTAINER python src/main.py -p "$current_date" >> "$LOG_FILE" 2>&1; then
        echo "  ✅ Success"
        echo "  ✅ Success" >> "$LOG_FILE"
        success_count=$((success_count + 1))
    else
        echo "  ❌ Failed"
        echo "  ❌ Failed" >> "$LOG_FILE"
        failed_dates+=("$current_date")
    fi

    # Move to next trading date
    current_date=$(get_next_trading_date "$current_date")

    echo ""
done

# Summary
echo "======================================================================="
echo "BACKFILL COMPLETE"
echo "======================================================================="
echo "Total Dates Processed: $dates_processed"
echo "Successful: $success_count"
echo "Failed: $((dates_processed - success_count))"

if [ ${#failed_dates[@]} -gt 0 ]; then
    echo ""
    echo "Failed Dates:"
    for date in "${failed_dates[@]}"; do
        echo "  - $date"
    done
fi

echo ""
echo "======================================================================="
echo "NEXT STEPS"
echo "======================================================================="
echo "1. Check MongoDB for scored trades:"
echo "   docker exec bluehorseshoe python -c \"from bluehorseshoe.core.container import create_app_container; c = create_app_container(); db = c.get_database(); print(f'Total scores: {db[\"trade_scores\"].count_documents({})}'); c.close()\""
echo ""
echo "2. Train profit target models:"
echo "   docker exec bluehorseshoe python src/train_profit_target.py 10000"
echo ""
echo "3. Verify models created:"
echo "   ls -lh src/models/ml_profit_target_*.joblib"
echo ""
echo "Log saved to: $LOG_FILE"
echo "======================================================================="

# Log summary
echo "" >> "$LOG_FILE"
echo "=======================================================================" >> "$LOG_FILE"
echo "SUMMARY" >> "$LOG_FILE"
echo "=======================================================================" >> "$LOG_FILE"
echo "Total: $dates_processed" >> "$LOG_FILE"
echo "Success: $success_count" >> "$LOG_FILE"
echo "Failed: $((dates_processed - success_count))" >> "$LOG_FILE"
echo "Completed at: $(date)" >> "$LOG_FILE"
