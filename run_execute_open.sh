#!/bin/bash
# Fill-anchored paper executor — cron wrapper (runs just after the US open).
# Cron (09:31 ET weekdays, DST-safe via CRON_TZ):
#   CRON_TZ=America/New_York
#   31 9 * * 1-5 /root/BlueHorseshoe/run_execute_open.sh
# Places marketable entries for orders staged overnight by `-p`, then anchors
# stop/target to the ACTUAL fill (two OCA pairs). No-op unless
# PAPER_TRADING_ENABLED=true and FILL_ANCHORED_EXECUTION=true. Needs the paper
# IB gateway up at the open.

REPO="/root/BlueHorseshoe"
PYTHON="$REPO/.venv/bin/python"
export PYTHONPATH="$REPO/src"
cd "$REPO"

# Load .env so IBKR + Mongo env vars are available. (The weekly-retrain bug: a
# cron wrapper that doesn't source .env silently runs mis-configured.)
if [ -f "$REPO/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    export "$line" 2>/dev/null || true
  done < "$REPO/.env"
fi

LOG="$REPO/src/logs/execute_open.log"
mkdir -p "$(dirname "$LOG")"

echo "--- execute_open started: $(date -u +'%Y-%m-%d %H:%M:%S UTC') ---" >> "$LOG"
$PYTHON src/main.py --execute-open >> "$LOG" 2>&1
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
  echo "ERROR: execute_open exit $EXIT_CODE at $(date -u +'%Y-%m-%d %H:%M:%S UTC')" >> "$LOG"
fi
echo "--- execute_open finished: $(date -u +'%Y-%m-%d %H:%M:%S UTC') (exit=$EXIT_CODE) ---" >> "$LOG"
exit $EXIT_CODE
