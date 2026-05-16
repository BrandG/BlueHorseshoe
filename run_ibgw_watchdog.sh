#!/usr/bin/env bash
# IB Gateway watchdog: detect a wedged API listener and force-recreate the
# container. Designed for cron at */5 (1-min offset from bh_swing_monitor so
# the monitor doesn't fire while we're mid-bounce).
#
# Failure mode this catches: Java process inside the container dies after a
# failed daily-reconnect, but the container stays "up" so docker's restart
# policy never fires. Crucially, socat keeps accepting TCP on the host-side
# port (4004) — so a host-side nc probe is useless. The right probe is to
# `docker exec` into the container and test whether Java's listener
# (127.0.0.1:4002) is alive. We use `bash -c "exec 3<>/dev/tcp/..."` with a
# 3s `timeout` wrapper: rc=0 means Java accepted, rc=124 means it never did.
#
# Cooldown: after a bounce, skip subsequent runs for 15 min so we don't
# stack force-recreates while the new gateway is still starting up.
set -euo pipefail

LOG=/root/BlueHorseshoe/src/logs/ibgw_watchdog.log
COMPOSE_DIR=/root/BlueHorseshoe/docker
COOLDOWN_FILE=/tmp/ibgw_watchdog.last_bounce
COOLDOWN_SEC=900   # 15 min
CONTAINER=ib-gateway
JAVA_PORT=4002     # Java API listener inside the container

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$LOG"; }

# Cooldown — if we bounced recently, skip silently. Prevents stacked
# recreates while the new container is still in its login flow.
if [[ -f "$COOLDOWN_FILE" ]]; then
  last=$(stat -c %Y "$COOLDOWN_FILE")
  now=$(date +%s)
  if (( now - last < COOLDOWN_SEC )); then
    exit 0
  fi
fi

# If the container isn't running at all, docker's restart policy handles
# it — bail and let docker do its thing.
if ! docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
  log "container $CONTAINER not running; deferring to docker restart policy"
  exit 0
fi

# Probe Java's listener from inside the container. /dev/tcp open blocks
# when the listener is dead; outer `timeout 3` gives us a clean rc=124 in
# that case. Wrap in `timeout 8` on the docker exec to bound the worst case.
if timeout 8 docker exec "$CONTAINER" bash -c \
    "timeout 3 bash -c 'exec 3<>/dev/tcp/127.0.0.1/${JAVA_PORT}' 2>/dev/null" \
    >/dev/null 2>&1; then
  # Exit silently on a healthy probe to keep the log uncluttered.
  exit 0
fi

log "wedge detected: ${CONTAINER}:${JAVA_PORT} (Java listener) unreachable; force-recreating"

# Touch cooldown BEFORE the recreate, so a slow / failing recreate doesn't
# get retried on the next tick.
touch "$COOLDOWN_FILE"

if cd "$COMPOSE_DIR" && docker compose up -d --force-recreate ib-gateway >> "$LOG" 2>&1; then
  log "force-recreate succeeded; new container starting (login takes ~30-60s)"
else
  log "ERROR: force-recreate failed (see log above)"
  exit 1
fi
