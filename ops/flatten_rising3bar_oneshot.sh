#!/usr/bin/env bash
# One-shot retirement flatten for rising_3bar (2026-05-31). Installed in crontab to
# fire hourly; runs the guarded, idempotent flatten and SELF-REMOVES its own cron line
# once the positions are closed. While forex is halted (weekend) the flatten exits 3
# and this wrapper leaves the cron entry in place to retry next hour.
set -u
REPO=/root/BlueHorseshoe
LOG="$REPO/src/logs/rising3bar_flatten_oneshot.log"
MARKER='flatten_rising3bar_oneshot'

# avoid overlapping runs
exec 9>"/tmp/.rising3bar_flatten.lock"
flock -n 9 || exit 0

echo "=== $(date -u +%FT%TZ) run ===" >> "$LOG"
cd "$REPO" || { echo "cd failed" >> "$LOG"; exit 1; }
./run.sh python "$REPO/ops/flatten_rising3bar.py" >> "$LOG" 2>&1
rc=$?
echo "flatten exit rc=$rc" >> "$LOG"

if [ "$rc" -eq 0 ]; then
    # rc=0 means: positions closed, or none left to close. Self-remove the cron line.
    crontab -l 2>/dev/null | grep -v "$MARKER" | crontab -
    echo "DONE (rc=0) — cron line removed, one-shot complete" >> "$LOG"
fi
# rc=3 (MARKET_HALTED) or rc=2 (guard) -> leave cron in place; retries next hour.
