#!/bin/bash
# Live IBKR gateway watchdog — detect a wedged listener and EMAIL Brand to hit
# the phone-facing refresh page. Detect-and-notify only (2FA needs a human, so
# unlike run_ibgw_watchdog.sh this does NOT force-recreate). See
# bluehorseshoe/maintenance/ibgw_live_alert.py for the state machine.
#
# Cron (offset from the other */5 jobs so we don't pile onto a tick):
#   3-58/5 * * * * /root/BlueHorseshoe/run_ibgw_live_watchdog.sh

REPO="/root/BlueHorseshoe"
PYTHON="$REPO/.venv/bin/python"
export PYTHONPATH="$REPO/src"
cd "$REPO" || exit 1

# Load .env so SMTP_* / EMAIL_* are available to EmailService.
if [ -f "$REPO/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    export "$line" 2>/dev/null || true
  done < "$REPO/.env"
fi

LOG="$REPO/src/logs/ibgw_live_watchdog.log"
exec >> "$LOG" 2>&1

$PYTHON -m bluehorseshoe.maintenance.ibgw_live_alert
