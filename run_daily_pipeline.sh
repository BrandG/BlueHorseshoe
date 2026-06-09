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

# Memory preflight. The prediction ProcessPool needs ~4GB; on this 7.8GB box a
# concurrent Claude/node session can starve it and OOM-kill a pool worker
# (-> concurrent.futures BrokenProcessPool -> only partial scores persisted, as
# happened 2026-06-08). Wait for headroom before the heavy step rather than
# racing it. See memory: project_pipeline_oom_concurrent_claude.
MIN_AVAIL_MB=3500
wait_for_memory() {
    local waited=0 max=900 avail
    while :; do
        avail=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
        if [ "${avail:-0}" -ge "$MIN_AVAIL_MB" ]; then
            return 0
        fi
        if [ "$waited" -ge "$max" ]; then
            echo "WARNING: only ${avail}MB available after ${waited}s wait (< ${MIN_AVAIL_MB}MB); proceeding anyway at $(date)" >> "$LOG"
            return 0
        fi
        echo "Low memory: ${avail}MB available (< ${MIN_AVAIL_MB}MB) — waiting 60s for headroom at $(date)" >> "$LOG"
        sleep 60
        waited=$((waited + 60))
    done
}

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

# Guard: refuse to double-run if another prediction is already in flight (a
# second pipeline or a manual -p) — two ProcessPools would OOM each other.
if pgrep -f "bin/python src/main.py -p" >/dev/null 2>&1; then
    echo "ERROR: another 'main.py -p' is already running; aborting to avoid OOM at $(date)" >> "$LOG"
    $STATUS fail predict "concurrent main.py -p detected"
    exit 1
fi

# Guard: wait for memory headroom so a concurrent session can't OOM a pool worker.
wait_for_memory

$PYTHON src/main.py -p >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    # A BrokenProcessPool (OOM-killed worker) aborts the whole run after only
    # partial scores. Pause for memory to free, then retry once before giving up.
    echo "WARNING: Prediction failed (possible OOM/BrokenProcessPool); waiting 120s and retrying once at $(date)" >> "$LOG"
    sleep 120
    wait_for_memory
    $PYTHON src/main.py -p >> "$LOG" 2>&1
    if [ $? -ne 0 ]; then
        echo "ERROR: Prediction failed after retry at $(date)" >> "$LOG"
        $STATUS fail predict "Prediction failed after retry"
        exit 1
    fi
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
