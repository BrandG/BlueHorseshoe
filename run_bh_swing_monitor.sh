#!/bin/bash
# BH Swing intraday monitor (Phase 0: read-only) — cron wrapper.
# Cron suggestion (US market hours, weekdays):
#   */5 13-21 * * 1-5 /root/BlueHorseshoe/run_bh_swing_monitor.sh
# Reconciles IBKR truth into src/logs/bh_swing_journal.csv and regenerates
# src/graphs/swing_tracker.html. Does not place, modify, or cancel orders.

REPO="/root/BlueHorseshoe"
PYTHON="$REPO/.venv/bin/python"
export PYTHONPATH="$REPO/src"
cd "$REPO"

# Load .env so IBKR + Mongo env vars are available.
if [ -f "$REPO/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    export "$line" 2>/dev/null || true
  done < "$REPO/.env"
fi

LOG="$REPO/src/logs/bh_swing_monitor.log"
mkdir -p "$(dirname "$LOG")"

echo "--- bh_swing_monitor started: $(date -u +'%Y-%m-%d %H:%M:%S UTC') ---" >> "$LOG"

$PYTHON src/gordon/swing_monitor.py "$@" >> "$LOG" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
  echo "ERROR: bh_swing_monitor exit code $EXIT_CODE at $(date -u +'%Y-%m-%d %H:%M:%S UTC')" >> "$LOG"
fi

echo "--- bh_swing_monitor finished: $(date -u +'%Y-%m-%d %H:%M:%S UTC') (exit=$EXIT_CODE) ---" >> "$LOG"
exit $EXIT_CODE
