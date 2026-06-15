#!/usr/bin/env bash
#
# run_crontab_drift_check.sh — warn when the live crontab diverges from the
# version-controlled snapshot at ops/crontab.txt.
#
# ops/crontab.txt is a manually-maintained source-of-truth copy of the crontab.
# Nothing forces the two to stay in sync, so an edit to `crontab -l` that isn't
# re-dumped here drifts silently. This check catches that: silent when in sync,
# logs a timestamped unified diff when they diverge.
#
# Silent on a healthy box; logs only on drift. Modeled on run_ibgw_watchdog.sh.

set -uo pipefail

REPO="/root/BlueHorseshoe"
SNAPSHOT="$REPO/ops/crontab.txt"
LOG="$REPO/src/logs/crontab_drift.log"

ts() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }

if [[ ! -f "$SNAPSHOT" ]]; then
    echo "$(ts) DRIFT: snapshot missing at $SNAPSHOT" >> "$LOG"
    exit 1
fi

# diff exits 0 when identical, 1 when different. Compare live crontab to snapshot.
if ! d=$(diff -u "$SNAPSHOT" <(crontab -l 2>/dev/null) 2>&1); then
    {
        echo "$(ts) DRIFT: live crontab differs from $SNAPSHOT"
        echo "  (--- = snapshot in git, +++ = live crontab)"
        echo "$d" | sed 's/^/  /'
        echo "  fix: crontab -l > $SNAPSHOT   (then commit)  OR   crontab $SNAPSHOT   (to restore)"
        echo
    } >> "$LOG"
    exit 1
fi

exit 0
