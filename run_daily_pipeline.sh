#!/bin/bash
# Daily Trading Pipeline for BlueHorseshoe
# Cron: 0 2 * * 1-6 /root/BlueHorseshoe/run_daily_pipeline.sh
#
# Mon-Fri: Update active symbols only -> Predict -> Generate Report -> Send Email
# Saturday: Full symbol update (reclassifies active/inactive for next week)

LOG="/root/BlueHorseshoe/src/logs/daily_pipeline.log"

echo "--- Daily Pipeline Started: $(date) ---" >> "$LOG"

# 1. Update historical data (active-only on weekdays, full on Saturday)
DOW=$(date +%u)  # 1=Mon ... 6=Sat
if [ "$DOW" -eq 6 ]; then
    echo "Saturday: running full symbol update" >> "$LOG"
    docker exec bluehorseshoe python src/main.py -u >> "$LOG" 2>&1
else
    echo "Weekday: running active-only symbol update" >> "$LOG"
    docker exec bluehorseshoe python src/main.py -u --active-only >> "$LOG" 2>&1
fi

if [ $? -ne 0 ]; then
    echo "ERROR: Data update failed at $(date)" >> "$LOG"
    exit 1
fi

# 2. Run prediction (generates report) — skip on Saturday
if [ "$DOW" -ne 6 ]; then
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
fi

echo "--- Daily Pipeline Finished: $(date) ---" >> "$LOG"
