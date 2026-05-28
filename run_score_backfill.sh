#!/bin/bash
# Polite background scorer — walks `trade_scores` backwards from the earliest
# present date, running `main.py -p DATE` for one unscored trading day per tick.
# Designed to be cron-fired (~hourly or 2-hourly). Skips ticks when the daily
# pipeline window is active or another main.py invocation is already running,
# so it cannot collide with -u/-p (which CLAUDE.md flags as OOM-sensitive).
#
# Cron: 0 */2 * * * /root/BlueHorseshoe/run_score_backfill.sh
#
# Tunables (env vars):
#   BACKFILL_FLOOR_DATE   earliest date to backfill (default 2015-01-01)
#   BACKFILL_SKIP_FILE    path to skip-list (default src/logs/score_backfill_skip.txt)
#   BACKFILL_PAUSE_FILE   if this file exists, skip every tick (default .score_backfill_pause)

set -u

REPO="/root/BlueHorseshoe"
LOG="$REPO/src/logs/score_backfill.log"
LOCK="/tmp/bh_score_backfill.lock"
PAUSE_FILE="${BACKFILL_PAUSE_FILE:-$REPO/.score_backfill_pause}"
SKIP_FILE="${BACKFILL_SKIP_FILE:-$REPO/src/logs/score_backfill_skip.txt}"
export BACKFILL_FLOOR_DATE="${BACKFILL_FLOOR_DATE:-2015-01-01}"
export BACKFILL_SKIP_FILE="$SKIP_FILE"

mkdir -p "$REPO/src/logs"
ts() { date '+%Y-%m-%d %H:%M:%S UTC'; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

# Single-instance via flock. If we cannot grab the lock, another tick is still
# running (a previous -p went long); bail without complaint.
exec 9>"$LOCK"
if ! flock -n 9; then
    log "skip: another tick is still holding the lock"
    exit 0
fi

cd "$REPO" || { log "fatal: cd $REPO failed"; exit 1; }

# Hard pause switch — operator can `touch .score_backfill_pause` to halt.
if [ -f "$PAUSE_FILE" ]; then
    log "skip: pause file present at $PAUSE_FILE"
    exit 0
fi

# Daily-pipeline blackout window: 00:30–03:30 UTC covers the 01:00 daily
# pipeline and the 02:00 Sunday retrain. pgrep guard below catches stragglers.
HHMM=$(date -u '+%H%M')
if [ "$HHMM" -ge "0030" ] && [ "$HHMM" -le "0330" ]; then
    log "skip: in daily-pipeline blackout window ($HHMM UTC)"
    exit 0
fi

# Concurrency guard — never run alongside another main.py (CLAUDE.md: -u and -p
# can OOM-kill each other and corrupt the run).
if pgrep -f "src/main.py" >/dev/null 2>&1; then
    log "skip: src/main.py already running"
    exit 0
fi

# Pick the next date to score.
PICK_OUT=$(./run.sh python src/score_backfill_pick_date.py 2>>"$LOG")
PICK_RC=$?
if [ "$PICK_RC" -ne 0 ]; then
    log "no work: picker exited $PICK_RC"
    exit 0
fi
TARGET_DATE=$(echo "$PICK_OUT" | tr -d '[:space:]')
if [ -z "$TARGET_DATE" ]; then
    log "no work: picker produced empty date"
    exit 0
fi

log "start: -p $TARGET_DATE (nice 19 / ionice idle)"
START_TS=$(date +%s)

# Low-priority CPU+IO so this never starves foreground work.
# --no-paper is mandatory: this replays historical dates, and submitting
# bracket orders for stale candidates against today's market would pollute
# the live paper book. The flag is honored in-process by main.py — an env
# var cannot disable paper trading because run.sh re-exports .env on top of
# the caller's environment.
nice -n 19 ionice -c 3 ./run.sh python src/main.py -p "$TARGET_DATE" --no-paper \
    >> "$LOG" 2>&1
RC=$?

DUR=$(( $(date +%s) - START_TS ))
if [ "$RC" -eq 0 ]; then
    log "done : -p $TARGET_DATE rc=0 (${DUR}s)"
else
    log "fail : -p $TARGET_DATE rc=$RC (${DUR}s) — adding to skip-list"
    echo "$TARGET_DATE  # rc=$RC at $(ts)" >> "$SKIP_FILE"
fi

exit 0
