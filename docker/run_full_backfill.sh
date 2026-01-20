#!/usr/bin/env bash
set -euo pipefail

# Safety: don't allow overlapping runs
LOCK="/tmp/bh_backfill.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date -Is) backfill already running, exiting"
  exit 0
fi

echo "$(date -Is) starting BH full backfill loop"

# Tune these for your plan
export BH_BATCH_LIMIT=${BH_BATCH_LIMIT:-50}
export BH_SLEEP_SECONDS=${BH_SLEEP_SECONDS:-2.5}

while true; do
  OUT=$(python3 - <<'PY'
import os
from bluehorseshoe.core.batch_loader import run_historical_batch

limit = int(os.environ.get("BH_BATCH_LIMIT", 50))
sleep_sec = float(os.environ.get("BH_SLEEP_SECONDS", 1.2))

res = run_historical_batch(limit=limit, recent_only=False, sleep_seconds=sleep_sec, classify=True)
print(res)
PY
)

  echo "$(date -Is) $OUT"

  # stop when done
  if echo "$OUT" | grep -q "'status': 'done'"; then
    echo "$(date -Is) backfill complete"
    break
  fi
done
