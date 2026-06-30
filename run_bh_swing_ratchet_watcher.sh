#!/usr/bin/env bash
# Ratchet watcher — emails the operator on the first (and subsequent) live
# stop_ratcheted events. Cron during/after market hours. Read-only on the journal.
cd /root/BlueHorseshoe || exit 1
exec ./run.sh python src/bh_swing/operator/ratchet_watcher.py
