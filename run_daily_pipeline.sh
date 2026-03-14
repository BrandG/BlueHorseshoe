#!/bin/bash
# Daily Trading Pipeline for BlueHorseshoe
# Cron: 0 2 * * 1-6 /root/BlueHorseshoe/run_daily_pipeline.sh
#
# Mon-Fri: Update active symbols only -> Predict -> Generate Report -> Send Email
# Saturday: Full symbol update + Predict Friday data -> Report -> Email

LOG="/root/BlueHorseshoe/src/logs/daily_pipeline.log"
STATUS="python src/pipeline_status.py"

echo "--- Daily Pipeline Started: $(date) ---" >> "$LOG"

# Initialize pipeline status
docker exec bluehorseshoe $STATUS begin

# 1. Update historical data (active-only on weekdays, full on Saturday)
DOW=$(date +%u)  # 1=Mon ... 6=Sat
docker exec bluehorseshoe $STATUS start update
if [ "$DOW" -eq 6 ]; then
    echo "Saturday: running full symbol update" >> "$LOG"
    docker exec bluehorseshoe python src/main.py -u >> "$LOG" 2>&1
else
    echo "Weekday: running active-only symbol update" >> "$LOG"
    docker exec bluehorseshoe python src/main.py -u --active-only >> "$LOG" 2>&1
fi

if [ $? -ne 0 ]; then
    echo "ERROR: Data update failed at $(date)" >> "$LOG"
    docker exec bluehorseshoe $STATUS fail update "Data update failed"
    exit 1
fi
docker exec bluehorseshoe $STATUS complete update

# 2. Run prediction (generates report)
docker exec bluehorseshoe $STATUS start predict
docker exec bluehorseshoe python src/main.py -p >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: Prediction failed at $(date)" >> "$LOG"
    docker exec bluehorseshoe $STATUS fail predict "Prediction failed"
    exit 1
fi
docker exec bluehorseshoe $STATUS complete predict

# 3. Verify report was generated (created by predict step)
docker exec bluehorseshoe $STATUS start report
# On Saturday, the report is for Friday (2 days ago), not yesterday
if [ "$DOW" -eq 6 ]; then
    REPORT_DATE=$(date -d "2 days ago" +%Y-%m-%d 2>/dev/null || date -v-2d +%Y-%m-%d)
else
    REPORT_DATE=$(date -d "yesterday" +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d)
fi
if docker exec bluehorseshoe test -f "src/logs/report_${REPORT_DATE}_arcade.html"; then
    docker exec bluehorseshoe $STATUS complete report
else
    echo "WARNING: Report file not found for ${REPORT_DATE}" >> "$LOG"
    docker exec bluehorseshoe $STATUS fail report "Report file not found for ${REPORT_DATE}"
fi

# 4. Send report email
docker exec bluehorseshoe $STATUS start email
docker exec bluehorseshoe python src/send_report_email.py >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    echo "WARNING: Email send failed at $(date)" >> "$LOG"
    docker exec bluehorseshoe $STATUS fail email "Email send failed"
else
    docker exec bluehorseshoe $STATUS complete email
fi

# Mark pipeline as done
docker exec bluehorseshoe $STATUS finish

echo "--- Daily Pipeline Finished: $(date) ---" >> "$LOG"
