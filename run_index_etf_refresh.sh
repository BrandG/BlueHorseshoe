#!/bin/bash
# Keeps the index ETFs (SPY, QQQ) fresh in the DuckDB OHLCV store.
#
# SPY/QQQ are NOT in the daily `-u` universe (that universe is NASDAQ stocks),
# so without this they silently drift stale — which on 2026-04-14 wedged the
# hypothesis engine for 7 weeks (the maturity gate used to count SPY bars from
# the store; see CLAUDE.md pitfall #2 and hypothesis_engine._is_mature).
#
# The maturity gate is now calendar-based and no longer depends on this, but
# SPY freshness still drives spy_return_pct / alpha_pct on every evaluated
# trade, so we keep the data current with a tiny daily 2-symbol backfill.
#
# Cron: 15 3 * * *  /root/BlueHorseshoe/run_index_etf_refresh.sh
#   03:15 UTC sits after the 01:00 daily pipeline finishes (~02:16) and before
#   the score-backfill resumes at 04:00 — a clean, no-other-main.py window.

set -u

REPO="/root/BlueHorseshoe"
LOG="$REPO/src/logs/index_etf_refresh.log"
LOCK="/tmp/bh_index_etf_refresh.lock"

mkdir -p "$REPO/src/logs"
ts() { date '+%Y-%m-%d %H:%M:%S UTC'; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

# Single-instance via flock.
exec 9>"$LOCK"
if ! flock -n 9; then
    log "skip: another refresh is still holding the lock"
    exit 0
fi

cd "$REPO" || { log "fatal: cd $REPO failed"; exit 1; }

# Concurrency guard — never run alongside another main.py (CLAUDE.md: -u and -p
# can OOM-kill each other and corrupt the run).
if pgrep -f "src/main.py" >/dev/null 2>&1; then
    log "skip: src/main.py already running"
    exit 0
fi

log "start: -b --symbols SPY,QQQ"
START_TS=$(date +%s)
nice -n 19 ionice -c 3 ./run.sh python src/main.py -b --symbols SPY,QQQ >> "$LOG" 2>&1
RC=$?
DUR=$(( $(date +%s) - START_TS ))

if [ "$RC" -eq 0 ]; then
    log "done : rc=0 (${DUR}s)"
else
    log "fail : rc=$RC (${DUR}s)"
fi

exit 0
