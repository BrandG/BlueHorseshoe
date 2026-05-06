#!/bin/bash
# BH Briefing — H4 v2-cell signal report (cron wrapper)
# Cron: 25 */4 * * * /root/BlueHorseshoe/run_bh_briefing.sh
# Runs 25 minutes after each H4 close (data update is at :00, predict :15, paper :20).
# Emails only when there are fires; HTML always archived to src/logs/briefings/.

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

LOG="$REPO/src/logs/bh_briefing.log"

echo "--- BH Briefing started: $(date -u +'%Y-%m-%d %H:%M:%S UTC') ---" >> "$LOG"

$PYTHON src/bh_briefing.py --email --email-only-if-fires >> "$LOG" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
  echo "ERROR: bh_briefing exit code $EXIT_CODE at $(date -u +'%Y-%m-%d %H:%M:%S UTC')" >> "$LOG"
fi

echo "--- BH Briefing finished: $(date -u +'%Y-%m-%d %H:%M:%S UTC') (exit=$EXIT_CODE) ---" >> "$LOG"

exit $EXIT_CODE
