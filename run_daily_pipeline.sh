#!/bin/bash
# Daily Trading Pipeline for BlueHorseshoe
# Cron: 0 2 * * 1-5 /root/BlueHorseshoe/run_daily_pipeline.sh
#
# Runs: Update Data -> Predict -> Generate Report -> Send Email
# Replaces the former Celery Beat scheduled task.

LOG="/root/BlueHorseshoe/src/logs/daily_pipeline.log"

echo "--- Daily Pipeline Started: $(date) ---" >> "$LOG"

# 1. Update recent historical data
docker exec bluehorseshoe python src/main.py -u >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: Data update failed at $(date)" >> "$LOG"
    exit 1
fi

# 2. Run prediction (generates report)
docker exec bluehorseshoe python src/main.py -p >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: Prediction failed at $(date)" >> "$LOG"
    exit 1
fi

# 3. Send report email
docker exec bluehorseshoe python src/send_report_email.py >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    echo "WARNING: Email send failed at $(date)" >> "$LOG"
fi

echo "--- Daily Pipeline Finished: $(date) ---" >> "$LOG"
