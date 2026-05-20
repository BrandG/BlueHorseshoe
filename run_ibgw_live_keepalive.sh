#!/bin/bash
# IB Gateway LIVE — periodic keepalive cron wrapper.
#
# Cron suggestion (24/7 every 30 min):
#   */30 * * * * /root/BlueHorseshoe/run_ibgw_live_keepalive.sh
#
# Why 24/7 / why 30 min: IBKR's API session goes idle after ~3-4 hours
# of no client activity, leaving the gateway in a zombie state (TCP open,
# auth-layer rejecting new clients). Without a keepalive, the next
# bh_live_status call after a quiet stretch fails — and the live
# container's 7-day autorestart token only rolls if there's activity.
# 30 min gives wide margin against a tighter-than-observed timeout
# without generating excessive connection noise.
#
# Silent on success. Failures land in the log; ops should grep for them
# periodically (cron also emails on non-zero exit if configured).

REPO="/root/BlueHorseshoe"
PYTHON="$REPO/.venv/bin/python"
export PYTHONPATH="$REPO/src"
cd "$REPO"

if [ -f "$REPO/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    export "$line" 2>/dev/null || true
  done < "$REPO/.env"
fi

LOG="$REPO/src/logs/ibgw_live_keepalive.log"
mkdir -p "$(dirname "$LOG")"

$PYTHON src/bh_live_keepalive.py >> "$LOG" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
  echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') ERROR: keepalive exit=$EXIT_CODE" >> "$LOG"
fi

exit $EXIT_CODE
