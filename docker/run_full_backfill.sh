#!/usr/bin/env bash
set -euo pipefail

cd /root/BlueHorseshoe/docker

# Safety: don't allow overlapping runs
LOCK="/tmp/bh_backfill.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date -Is) backfill already running, exiting"
  exit 0
fi

echo "$(date -Is) starting BH full backfill loop"

# Tune these for your plan
export BH_TARGET_RPM=50
export BH_BATCH_LIMIT=50
export BH_SLEEP_SECONDS=1.2   # 60/50 = 1.2s pacing

while true; do
  OUT=$(docker compose exec -T bluehorseshoe python - <<'PY'
from bluehorseshoe.batch_loader import run_historical_batch
res = run_historical_batch(limit=50, recent_only=False, sleep_seconds=1.2, classify=True)
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
