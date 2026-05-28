#!/bin/bash
# BH FTMO unified autonomous trader — rising_3bar + v2 cells (cron wrapper)
#
# Cutover crontab change for Brand to apply manually:
# - remove: 15 1,5,9,13,17,21 * * * ... bh_ftmo_paper.py ...
# - remove: 16 1,5,9,13,17,21 * * * /root/BlueHorseshoe/run_bh_ftmo_v2_paper.sh
# - add:    16 1,5,9,13,17,21 * * * /root/BlueHorseshoe/run_bh_ftmo_trader.sh
#
# Do not edit the live crontab from this branch.

REPO="/root/BlueHorseshoe"
PYTHON="$REPO/.venv/bin/python"
export PYTHONPATH="$REPO/src"
cd "$REPO"

# Load .env so OANDA env vars are available
if [ -f "$REPO/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    export "$line" 2>/dev/null || true
  done < "$REPO/.env"
fi

LOG="$REPO/src/logs/bh_ftmo_trader.log"

echo "--- BH FTMO trader started: $(date -u +'%Y-%m-%d %H:%M:%S UTC') ---" >> "$LOG"

$PYTHON src/bh_ftmo_trader.py >> "$LOG" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
  echo "ERROR: bh_ftmo_trader exit code $EXIT_CODE at $(date -u +'%Y-%m-%d %H:%M:%S UTC')" >> "$LOG"
fi

echo "--- BH FTMO trader finished: $(date -u +'%Y-%m-%d %H:%M:%S UTC') (exit=$EXIT_CODE) ---" >> "$LOG"

exit $EXIT_CODE
