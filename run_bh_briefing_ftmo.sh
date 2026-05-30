#!/bin/bash
# BH Briefing → FTMO — sized orders + position health (cron wrapper)
# Cron: 25 1,5,9,13,17,21 * * * /root/BlueHorseshoe/run_bh_briefing_ftmo.sh
# Runs 25 min after each H4 close (data update :00, predict :15, paper :20).
# Sends ONE consolidated HTML email: orders to place (lots/SIDE/entry/stop/
# target/pips) + position health for the open book. Emails only when there is
# an order to place or an open position to report on.

REPO="/root/BlueHorseshoe"
PYTHON="$REPO/.venv/bin/python"
export PYTHONPATH="$REPO/src"
cd "$REPO"

# Load .env so SMTP_* and EMAIL_* are available
if [ -f "$REPO/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    export "$line" 2>/dev/null || true
  done < "$REPO/.env"
fi

LOG="$REPO/src/logs/bh_briefing_ftmo.log"

echo "--- BH Briefing FTMO started: $(date -u +'%Y-%m-%d %H:%M:%S UTC') ---" >> "$LOG"

$PYTHON src/bud/briefing_ftmo.py --email --email-only-if-activity >> "$LOG" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
  echo "ERROR: bh_briefing_ftmo exit code $EXIT_CODE at $(date -u +'%Y-%m-%d %H:%M:%S UTC')" >> "$LOG"
fi

echo "--- BH Briefing FTMO finished: $(date -u +'%Y-%m-%d %H:%M:%S UTC') (exit=$EXIT_CODE) ---" >> "$LOG"

exit $EXIT_CODE
