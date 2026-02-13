#!/bin/bash
#
# Daily BlueHorseshoe Pipeline
# Runs: Update market data -> Predict -> Generate report -> Send email
# Schedule: 02:00 UTC (9 PM EST) Monday-Friday
#

# Set up logging
LOG_FILE="/root/BlueHorseshoe/src/logs/cron_pipeline.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S UTC')

echo "============================================" >> "$LOG_FILE"
echo "Pipeline started: $DATE" >> "$LOG_FILE"
echo "============================================" >> "$LOG_FILE"

# Step 1: Update market data
echo "[$DATE] Step 1: Updating market data..." >> "$LOG_FILE"
docker exec bluehorseshoe python src/main.py -u >> "$LOG_FILE" 2>&1
UPDATE_EXIT=$?

if [ $UPDATE_EXIT -ne 0 ]; then
    echo "[$DATE] ERROR: Market data update failed with exit code $UPDATE_EXIT" >> "$LOG_FILE"
    exit 1
fi

echo "[$DATE] Market data update completed successfully" >> "$LOG_FILE"

# Step 2: Run prediction (also generates report and sends email)
DATE=$(date '+%Y-%m-%d %H:%M:%S UTC')
echo "[$DATE] Step 2: Running prediction and generating report..." >> "$LOG_FILE"
docker exec bluehorseshoe python src/main.py -p >> "$LOG_FILE" 2>&1
PREDICT_EXIT=$?

if [ $PREDICT_EXIT -ne 0 ]; then
    echo "[$DATE] ERROR: Prediction failed with exit code $PREDICT_EXIT" >> "$LOG_FILE"
    exit 1
fi

DATE=$(date '+%Y-%m-%d %H:%M:%S UTC')
echo "[$DATE] Pipeline completed successfully" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

exit 0
