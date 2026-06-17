#!/bin/bash
# Weekly fundamentals refresh for the PIT solvency feed (Altman-Z'').
#
# Keeps the DuckDB `fundamentals` table fresh so the LIVE solvency-gated
# deep_oversold sleeve (deep_oversold_solvency_filter) doesn't drift stale.
# The pull is AlphaVantage-rate-limited (~31 min) and memory-touching, so it
# MUST NOT overlap the daily `-u`/`-p` pipeline or score-backfill — both run
# main.py and a concurrent heavy proc OOM-kills the box (see CLAUDE.md Process
# Safety). Scheduled Sunday 23:00 UTC (an empty slot), with a flock single-
# instance lock and a main.py-active guard as defense-in-depth.
#
# Cron (host crontab AND ops/crontab.txt — keep in sync, drift-checked 04:00):
#   0 23 * * 0  /root/BlueHorseshoe/src/cron_quarterly_fundamentals.sh >> /root/BlueHorseshoe/src/logs/cron_quarterly_fundamentals.log 2>&1

set -u

REPO="/root/BlueHorseshoe"
PYTHON="$REPO/.venv/bin/python"
LOCK="/tmp/bh_fundamentals_refresh.lock"
export PYTHONPATH="$REPO/src"
cd "$REPO" || exit 1

ts() { date '+%Y-%m-%d %H:%M:%S UTC'; }

# Single-instance: never stack two pulls (a slow AV run can exceed a week? no,
# but a wedged one shouldn't be joined by the next).
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(ts)] skip: another fundamentals refresh holds the lock"
  exit 0
fi

# Guard: never run alongside the main.py pipeline / score-backfill. The puller
# is `python -m bluehorseshoe.data.fundamentals_pull` (NOT main.py), so matching
# "src/main.py" cannot self-match (see reference_pgrep_self_match).
if pgrep -f "src/main.py" >/dev/null 2>&1; then
  echo "[$(ts)] skip: main.py pipeline active — deferring to next week to avoid OOM"
  exit 0
fi

# Load .env for ALPHAVANTAGE_KEY / DUCKDB_PATH etc.
if [ -f "$REPO/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    export "$line" 2>/dev/null || true
  done < "$REPO/.env"
fi

echo "--- Fundamentals refresh started: $(ts) ---"
"$PYTHON" -m bluehorseshoe.data.fundamentals_pull
rc=$?
if [ $rc -ne 0 ]; then
  echo "[$(ts)] ERROR: fundamentals refresh failed (rc=$rc)"
  exit 1
fi
echo "--- Fundamentals refresh finished: $(ts) ---"
