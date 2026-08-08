#!/bin/bash
# Daily DATA-ONLY pipeline for BlueHorseshoe (Gordon).
# Cron: 0 1 * * 2-6 /root/BlueHorseshoe/run_daily_data_only.sh
#
# Stand-down variant of run_daily_pipeline.sh, installed 2026-08-07 when
# automated trading was shut down. Keeps the data flowing so the OHLCV store
# and the daily scores stay current for research, but does NOT trade, does NOT
# email, and does NOT touch the broker.
#
#   Mon-Fri: active-only OHLCV update -> score/indicator calculation
#   Saturday: full symbol OHLCV update -> score/indicator calculation
#
# Dropped vs run_daily_pipeline.sh:
#   * paper order submission  (--no-paper; belt-and-braces with .env)
#   * journal import/reconcile/review  (IBKR fills — nothing is trading)
#   * report email  (src/send_report_email.py)
#   * hypothesis evaluation  (--evaluate)
#
# NOTE: `main.py -p` still WRITES the HTML report files into src/logs/ — report
# generation is not separable from scoring without a code change. Nothing is
# emailed, and scripts/rotate_logs.sh prunes those files after 21 days.
#
# To restore full trading, reinstall the original line from ops/crontab.txt:
#   0 1 * * 2-6  /root/BlueHorseshoe/run_daily_pipeline.sh

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

echo "--- Daily DATA-ONLY Pipeline Started: $(date) ---" >> "$LOG"

# Initialize pipeline status. report/email/evaluate stay "pending" by design —
# they are intentionally skipped in this variant.
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

# 2. Calculate indicators/scores. --no-paper suppresses order submission
#    regardless of PAPER_TRADING_ENABLED in .env (see main.py: the flag is
#    checked against sys.argv directly).
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

$PYTHON src/main.py -p --no-paper >> "$LOG" 2>&1
if [ $? -ne 0 ]; then
    # A BrokenProcessPool (OOM-killed worker) aborts the whole run after only
    # partial scores. Pause for memory to free, then retry once before giving up.
    echo "WARNING: Prediction failed (possible OOM/BrokenProcessPool); waiting 120s and retrying once at $(date)" >> "$LOG"
    sleep 120
    wait_for_memory
    $PYTHON src/main.py -p --no-paper >> "$LOG" 2>&1
    if [ $? -ne 0 ]; then
        echo "ERROR: Prediction failed after retry at $(date)" >> "$LOG"
        $STATUS fail predict "Prediction failed after retry"
        exit 1
    fi
fi
$STATUS complete predict

# Mark pipeline as done. No journal, no email, no evaluate — by design.
$STATUS finish

echo "--- Daily DATA-ONLY Pipeline Finished: $(date) ---" >> "$LOG"
