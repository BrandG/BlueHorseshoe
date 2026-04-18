#!/bin/bash
# BH Lite FTMO Signal Generator — daily cron wrapper
# Cron: 30 22 * * 1-5 /root/BlueHorseshoe/run_bh_lite.sh
# Runs at 6:30 PM ET (22:30 UTC during EDT) on weekdays

REPO="/root/BlueHorseshoe"
PYTHON="$REPO/.venv/bin/python"
export PYTHONPATH="$REPO/src"
cd "$REPO"

LOG="$REPO/src/logs/bh_lite.log"

echo "--- BH Lite Started: $(date) ---" >> "$LOG"

$PYTHON src/bh_lite.py --top 5 >> "$LOG" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "ERROR: BH Lite failed with exit code $EXIT_CODE at $(date)" >> "$LOG"
fi

echo "--- BH Lite Finished: $(date) ---" >> "$LOG"

exit $EXIT_CODE
