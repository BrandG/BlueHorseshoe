#!/usr/bin/env bash
#
# run_forward_mnq.sh — forward paper driver for the opening-range fade study.
# (Filename kept for cron stability; it now drives the full 3-instrument book MNQ+MES+M2K.)
#
# Cron: `10 16 * * 1-5` (16:10 UTC = 11:10 ET in winter / 12:10 ET in summer, always AFTER
# the 11:00-ET trade window closes -> DST-safe with a single entry). The driver is idempotent
# per (ET date, instrument), so an accidental double-fire is harmless.
#
# For each of MNQ/MES/M2K: reads the front-month morning (09:30-11:00 ET) from the project's PAPER
# IB Gateway (4004 — the reliable one; live 4011 has the 2FA wedge), builds the Variant B setup,
# simulates the paper fill, and appends one row per instrument to
# research/opening_range_fade_v1/forward_paper_log.csv. Read-only and light. Logs to src/logs/forward_mnq.log.
#
set -uo pipefail
cd /root/BlueHorseshoe || exit 1
LOG=src/logs/forward_mnq.log
exec >> "$LOG" 2>&1
echo "=== $(date -u +'%F %T') UTC forward_mnq ==="
flock -n /tmp/forward_mnq.lock \
  ./run.sh python research/opening_range_fade_v1/forward_driver.py \
  || echo "skipped (lock held or driver error)"
