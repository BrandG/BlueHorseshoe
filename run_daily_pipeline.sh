#!/bin/bash
# Daily Trading Pipeline for BlueHorseshoe
# Cron: 0 1 * * 2-6 /root/BlueHorseshoe/run_daily_pipeline.sh
#
# Mon-Fri: Update -> Predict -> Journal -> Report -> Email
# Saturday: Full symbol update + Predict Friday data -> Journal -> Report -> Email

REPO="/root/BlueHorseshoe"
PYTHON="$REPO/.venv/bin/python"
export PYTHONPATH="$REPO/src"
cd "$REPO"
if [ -f "$REPO/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    # Skip comments and empty lines
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    export "$line" 2>/dev/null || true
  done < "$REPO/.env"
fi

LOG="$REPO/src/logs/daily_pipeline.log"
STATUS="$PYTHON src/pipeline_status.py"

echo "--- Daily Pipeline Started: $(date) ---" >> "$LOG"

# Initialize pipeline status
$STATUS begin

# 1. Update historical data (active-only on weekdays, full on Saturday)
DOW=$(date +%u)  # 1=Mon ... 6=Sat
$STATUS start update
if [ "$DOW" -eq 6 ]; then
    echo "Saturday: running full symbol update" >> "$LOG"
    $PYTHON src/main.py -u >> "$LOG" 2>&1
else
    echo "Weekday: running active-only symbol update" >> "$LOG"
    $PYTHON src/main.py -u --active-only >> "$LOG" 2>&1
fi

if [ $? -ne 0 ]; then
    echo "ERROR: Data update failed at $(date)" >> "$LOG"
    $STATUS fail update "Data update failed"
    exit 1
fi
$STATUS complete update

# 2. Run prediction (generates report)
$STATUS start predict
$PYTHON src/main.py -p >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: Prediction failed at $(date)" >> "$LOG"
    $STATUS fail predict "Prediction failed"
    exit 1
fi
$STATUS complete predict

# 3. Trade journal — import fills, reconcile positions, generate review (non-fatal)
$STATUS start journal
JOURNAL_ERRORS=0

# Import any new fills from IBKR (skip if gateway not connected)
$PYTHON src/main.py --journal-import-ibkr >> "$LOG" 2>&1 || ((JOURNAL_ERRORS++))

# Reconcile fills into positions
$PYTHON src/main.py --journal-reconcile >> "$LOG" 2>&1 || ((JOURNAL_ERRORS++))

# Generate daily review
$PYTHON src/main.py --journal-review >> "$LOG" 2>&1 || ((JOURNAL_ERRORS++))

if [ "$JOURNAL_ERRORS" -gt 0 ]; then
    echo "WARNING: Journal had $JOURNAL_ERRORS error(s) at $(date)" >> "$LOG"
    $STATUS fail journal "Journal had $JOURNAL_ERRORS error(s)"
else
    $STATUS complete journal
fi

# 4. Verify report was generated (created by predict step)
$STATUS start report
# On Saturday, the report is for Friday (2 days ago), not yesterday
if [ "$DOW" -eq 6 ]; then
    REPORT_DATE=$(date -d "2 days ago" +%Y-%m-%d 2>/dev/null || date -v-2d +%Y-%m-%d)
else
    REPORT_DATE=$(date -d "yesterday" +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d)
fi
if [ -f "$REPO/src/logs/report_${REPORT_DATE}_arcade.html" ]; then
    $STATUS complete report
else
    echo "WARNING: Report file not found for ${REPORT_DATE}" >> "$LOG"
    $STATUS fail report "Report file not found for ${REPORT_DATE}"
fi

# 5. Send report email
$STATUS start email
$PYTHON src/send_report_email.py >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    echo "WARNING: Email send failed at $(date)" >> "$LOG"
    $STATUS fail email "Email send failed"
else
    $STATUS complete email
fi

# 6. Evaluate matured signal hypotheses (non-fatal, runs last)
$STATUS start evaluate
$PYTHON src/main.py --evaluate >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    echo "WARNING: Hypothesis evaluation failed at $(date)" >> "$LOG"
    $STATUS fail evaluate "Hypothesis evaluation failed"
else
    $STATUS complete evaluate
fi

# Mark pipeline as done
$STATUS finish

echo "--- Daily Pipeline Finished: $(date) ---" >> "$LOG"
