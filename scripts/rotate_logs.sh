#!/usr/bin/env bash
#
# rotate_logs.sh — keep src/logs from ballooning again.
#
# The big offenders are append-only cron logs (daily_pipeline.log,
# cron_retrain.log, cron_pipeline.log, score_backfill.log, etc.) that no
# scheduler was rotating. This script caps every *.log in src/logs at a
# tail of MAX_LINES, keeping one .1 backup, and prunes dated report HTML
# and one-off experiment dumps older than KEEP_DAYS.
#
# Idempotent and safe to run daily from cron. It NEVER touches the active
# journals (*_journal.csv), the DuckDB stores, or models.
#
# Cron suggestion (host crontab, runs 03:30 daily — after the nightly
# pipeline at ~04:00 finishes the *previous* day, adjust if it overlaps):
#   30 3 * * * /root/BlueHorseshoe/scripts/rotate_logs.sh >> /root/BlueHorseshoe/src/logs/rotate_logs.log 2>&1
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$REPO_ROOT/src/logs"
GRAPH_DIR="$REPO_ROOT/src/graphs"

MAX_LINES="${ROTATE_MAX_LINES:-20000}"   # tail kept per *.log
KEEP_DAYS="${ROTATE_KEEP_DAYS:-21}"      # age cutoff for reports/experiment dumps
BRIEFING_KEEP_DAYS="${ROTATE_BRIEFING_KEEP_DAYS:-90}"  # archived briefing HTML

ts() { date '+%Y-%m-%d %H:%M:%S'; }
echo "[$(ts)] rotate_logs start (max_lines=$MAX_LINES keep_days=$KEEP_DAYS)"

# 1. Cap append-only logs at a tail, keeping a single .1 backup.
shopt -s nullglob
for f in "$LOG_DIR"/*.log; do
  # Skip this script's own log and anything already tiny.
  case "$(basename "$f")" in rotate_logs.log) continue;; esac
  lines=$(wc -l < "$f" 2>/dev/null || echo 0)
  if [ "$lines" -gt "$MAX_LINES" ]; then
    cp -f "$f" "$f.1"
    tail -n "$MAX_LINES" "$f.1" > "$f"
    echo "[$(ts)] capped $(basename "$f"): $lines -> $MAX_LINES lines (backup: $(basename "$f").1)"
  fi
done

# 2. Prune dated report HTML older than KEEP_DAYS (regenerable via main.py -r DATE).
# Cutoff is the DATE IN THE FILENAME, not mtime: the score-backfill cron
# regenerates reports for ancient dates daily, so their mtime is always
# fresh and an -mtime prune never catches them.
cutoff=$(date -d "-$KEEP_DAYS days" '+%Y-%m-%d')
pruned=0
for f in "$LOG_DIR"/*report_*.html; do
  d=$(basename "$f" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | head -1)
  if [ -n "$d" ] && [[ "$d" < "$cutoff" ]]; then
    rm -f "$f"; pruned=$((pruned+1))
  fi
done
[ "$pruned" -gt 0 ] && echo "[$(ts)] pruned $pruned old report HTML files (report date < $cutoff)"

# 2b. Prune archived briefing HTML older than BRIEFING_KEEP_DAYS. These are
# write-once (mtime == creation), so an mtime cutoff is correct here.
bpruned=0
for dir in "$LOG_DIR/briefings" "$LOG_DIR/briefings_ftmo"; do
  [ -d "$dir" ] || continue
  while IFS= read -r f; do
    rm -f "$f"; bpruned=$((bpruned+1))
  done < <(find "$dir" -name '*.html' -type f -mtime +"$BRIEFING_KEEP_DAYS" -print)
done
[ "$bpruned" -gt 0 ] && echo "[$(ts)] pruned $bpruned archived briefing HTML files (>${BRIEFING_KEEP_DAYS}d)"

# 3. Prune one-off experiment dumps in src/graphs older than KEEP_DAYS.
gpruned=0
for f in "$GRAPH_DIR"/bh_ftmo_gate_*.html "$GRAPH_DIR"/sandbox_*.html; do
  if [ "$(find "$f" -mtime +"$KEEP_DAYS" -print 2>/dev/null)" ]; then
    rm -f "$f"; gpruned=$((gpruned+1))
  fi
done
[ "$gpruned" -gt 0 ] && echo "[$(ts)] pruned $gpruned old graph dumps"

echo "[$(ts)] rotate_logs done (src/logs now $(du -sh "$LOG_DIR" | cut -f1))"
