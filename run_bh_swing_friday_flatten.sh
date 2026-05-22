#!/bin/bash
# BH Swing Friday-flatten — cron wrapper.
# Cron line (Fridays only, 5 min before US close = 19:55 UTC):
#   55 19 * * 5 /root/BlueHorseshoe/run_bh_swing_friday_flatten.sh
# Closes every open swing position via MKT sell, cancels working brackets,
# journals each as event=friday_flatten in src/logs/bh_swing_flatten_journal.csv.
# Built on the WEEKEND_FLATTEN_EQUITIES_v1 study result (2026-05-21).
# Kill switch: touch /root/BlueHorseshoe/.bh_swing_pause_friday_flatten

REPO="/root/BlueHorseshoe"
PYTHON="$REPO/.venv/bin/python"
export PYTHONPATH="$REPO/src"
cd "$REPO"

# Load .env so IBKR env vars are available.
if [ -f "$REPO/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    export "$line" 2>/dev/null || true
  done < "$REPO/.env"
fi

LOG="$REPO/src/logs/bh_swing_friday_flatten.log"
mkdir -p "$(dirname "$LOG")"

echo "--- bh_swing_friday_flatten started: $(date -u +'%Y-%m-%d %H:%M:%S UTC') ---" >> "$LOG"

$PYTHON src/bh_swing_friday_flatten.py "$@" >> "$LOG" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
  echo "ERROR: bh_swing_friday_flatten exit code $EXIT_CODE at $(date -u +'%Y-%m-%d %H:%M:%S UTC')" >> "$LOG"
fi

echo "--- bh_swing_friday_flatten finished: $(date -u +'%Y-%m-%d %H:%M:%S UTC') (exit=$EXIT_CODE) ---" >> "$LOG"
exit $EXIT_CODE
