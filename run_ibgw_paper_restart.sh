#!/bin/bash
# Paper IB Gateway — daily scheduled restart cron wrapper.
#
# Cron suggestion (4am ET / 08:00 UTC daily):
#   0 8 * * * /root/BlueHorseshoe/run_ibgw_paper_restart.sh
#
# Why this exists: AUTO_RESTART_TIME=08:00 set in docker-compose.yml is
# silently ignored by IBC (verified 2026-05-20: 0 scheduled restarts
# fired across 5 days of uptime, despite the env var being read into
# config.ini correctly). Rather than debug IBC's internal scheduler we
# drive the daily restart from cron — more predictable, fully visible
# in the watchdog log if something goes wrong.
#
# `docker compose restart` (not `up -d --force-recreate`) preserves the
# in-container Jts directory, including IBC's autorestart token. So
# normal operation: NO 2FA required. The token only resets if the
# watchdog has done a `--force-recreate` within the prior 24h, in which
# case the next 08:00 UTC restart needs 2FA. Rare.
#
# Timing: 08:00 UTC = 4am ET. Past IBKR's nightly server-maintenance
# disconnect (~01:40 UTC), well before US market open (13:30 UTC), and
# well clear of all bh_* crons.

REPO="/root/BlueHorseshoe"
LOG="$REPO/src/logs/ibgw_paper_restart.log"
mkdir -p "$(dirname "$LOG")"

echo "--- ibgw_paper_restart started: $(date -u +'%Y-%m-%d %H:%M:%S UTC') ---" >> "$LOG"

cd "$REPO/docker" && docker compose restart ib-gateway >> "$LOG" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
  echo "ERROR: docker compose restart ib-gateway exit=$EXIT_CODE" >> "$LOG"
fi

echo "--- ibgw_paper_restart finished: $(date -u +'%Y-%m-%d %H:%M:%S UTC') (exit=$EXIT_CODE) ---" >> "$LOG"
exit $EXIT_CODE
