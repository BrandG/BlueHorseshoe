#!/usr/bin/env bash
# backup.sh — Daily backup of DuckDB + MongoDB + ML models → Google Drive
# Runs on HOST (not inside Docker). Cron: 0 5 * * * /root/BlueHorseshoe/backup.sh
set -euo pipefail

# ── Load configuration ─────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/backup.conf"

TIMESTAMP="$(date -u +%Y%m%d_%H%M%S)"
ARCHIVE_NAME="bh_backup_${TIMESTAMP}.tar"
LOG_PREFIX="[backup $TIMESTAMP]"

# ── Cleanup trap ───────────────────────────────────────────────────────
cleanup() {
    rm -rf "$STAGING_DIR"
}
trap cleanup EXIT

# ── Logging helpers ────────────────────────────────────────────────────
log()  { echo "$LOG_PREFIX $*"; }
fail() {
    echo "$LOG_PREFIX FATAL: $*" >&2
    send_alert "Backup FAILED" "$*"
    exit 1
}

# ── Email alert via Python (uses SMTP creds from docker/.env) ──────────
send_alert() {
    local subject="$1" body="$2"
    # Skip if SMTP not configured
    [[ -z "${SMTP_SERVER:-}" || -z "${EMAIL_RECIPIENT:-}" ]] && return 0
    _ALERT_SUBJECT="$subject" python3 - <<PYEOF || log "WARNING: alert email failed (non-fatal)"
import smtplib
from email.mime.text import MIMEText
import os

msg = MIMEText("""$body

Host: $(hostname)
Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)
""")
msg["Subject"] = f"[BlueHorseshoe] {os.environ.get('_ALERT_SUBJECT', 'Alert')}"
msg["From"]    = os.environ.get("EMAIL_SENDER", "backup@localhost")
msg["To"]      = os.environ.get("EMAIL_RECIPIENT", "")

try:
    with smtplib.SMTP(os.environ["SMTP_SERVER"], int(os.environ.get("SMTP_PORT", 587))) as s:
        s.starttls()
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.sendmail(msg["From"], [msg["To"]], msg.as_string())
except Exception as e:
    print(f"Email send error: {e}")
    raise
PYEOF
}

# ── Step 1: Pipeline safety check ─────────────────────────────────────
log "Checking pipeline status..."
if [[ -f "$PIPELINE_STATUS" ]]; then
    # Check if pipeline_end is null AND any step is "running"
    if python3 -c "
import json, sys
with open('$PIPELINE_STATUS') as f:
    st = json.load(f)
if st.get('pipeline_end') is None:
    for step in st.get('steps', {}).values():
        if step.get('status') == 'running':
            print(f'Pipeline step still running: {step}', file=sys.stderr)
            sys.exit(1)
" 2>&1; then
        log "Pipeline status: safe to proceed"
    else
        fail "Pipeline is still running — aborting backup. Check $PIPELINE_STATUS"
    fi
fi

# Belt-and-suspenders: check if main.py is running
if pgrep -f "python.*main.py" > /dev/null 2>&1; then
    fail "main.py is running — aborting backup"
fi

# ── Step 2: Create staging directory ───────────────────────────────────
mkdir -p "$STAGING_DIR"
log "Staging directory: $STAGING_DIR"

# ── Step 3: DuckDB — flush WAL and compress ────────────────────────────
log "Flushing DuckDB WAL..."
$PYTHON -c "
import duckdb
con = duckdb.connect('$DUCKDB_HOST_PATH')
con.execute('CHECKPOINT')
con.close()
print('WAL flushed successfully')
" || fail "DuckDB WAL flush failed"

if [[ ! -f "$DUCKDB_HOST_PATH" ]]; then
    fail "DuckDB file not found at $DUCKDB_HOST_PATH"
fi

log "Compressing DuckDB ($(du -h "$DUCKDB_HOST_PATH" | cut -f1))..."
cp "$DUCKDB_HOST_PATH" "$STAGING_DIR/ohlcv.duckdb"
zstd -T0 -3 --rm "$STAGING_DIR/ohlcv.duckdb" \
    || fail "DuckDB compression failed"
log "DuckDB compressed: $(du -h "$STAGING_DIR/ohlcv.duckdb.zst" | cut -f1)"

# ── Step 4: MongoDB — selective mongodump + compress ───────────────────
log "Dumping MongoDB collections..."
MONGO_DUMP_DIR="$STAGING_DIR/mongodump"
mkdir -p "$MONGO_DUMP_DIR"

for coll in "${MONGO_COLLECTIONS[@]}"; do
    log "  dumping $coll..."
    mongodump \
        --host="$MONGO_BIND_IP" \
        --port=27017 \
        --db=bluehorseshoe \
        --collection="$coll" \
        --out="$MONGO_DUMP_DIR" \
        --quiet \
        || fail "mongodump failed for collection: $coll"
done

log "Compressing MongoDB dump..."
tar -cf - -C "$STAGING_DIR" mongodump | zstd -T0 -3 > "$STAGING_DIR/mongodump.tar.zst" \
    || fail "MongoDB compression failed"
rm -rf "$MONGO_DUMP_DIR"
log "MongoDB compressed: $(du -h "$STAGING_DIR/mongodump.tar.zst" | cut -f1)"

# ── Step 5: ML models — compress ──────────────────────────────────────
log "Compressing ML models..."
JOBLIB_FILES=($(ls "$MODELS_HOST_PATH"/*.joblib 2>/dev/null))
if [[ ${#JOBLIB_FILES[@]} -gt 0 ]]; then
    tar -cf - -C "$MODELS_HOST_PATH" --transform='s,^,models/,' \
        $(cd "$MODELS_HOST_PATH" && ls *.joblib) \
        | zstd -T0 -3 > "$STAGING_DIR/models.tar.zst" \
        || fail "ML models compression failed"
    log "Models compressed: $(du -h "$STAGING_DIR/models.tar.zst" | cut -f1)"
else
    log "WARNING: No .joblib files found in $MODELS_HOST_PATH — skipping"
    echo "(no models found)" > "$STAGING_DIR/models.tar.zst.EMPTY"
fi

# ── Step 6: Create manifest and bundle ─────────────────────────────────
log "Creating manifest..."
cat > "$STAGING_DIR/manifest.txt" <<MANIFEST
BlueHorseshoe Backup
====================
Timestamp:  $TIMESTAMP
Host:       $(hostname)
Date (UTC): $(date -u +%Y-%m-%d)

Contents:
  ohlcv.duckdb.zst    — DuckDB OHLCV database ($(du -h "$STAGING_DIR/ohlcv.duckdb.zst" 2>/dev/null | cut -f1 || echo "N/A"))
  mongodump.tar.zst   — MongoDB collections: ${MONGO_COLLECTIONS[*]}
  models.tar.zst      — ML model files (*.joblib)

DuckDB source:  $DUCKDB_HOST_PATH
Models source:  $MODELS_HOST_PATH
MongoDB host:   $MONGO_BIND_IP:27017
MANIFEST

log "Creating final archive..."
tar -cf "$STAGING_DIR/$ARCHIVE_NAME" \
    -C "$STAGING_DIR" \
    ohlcv.duckdb.zst \
    mongodump.tar.zst \
    manifest.txt \
    $(ls "$STAGING_DIR/models.tar.zst" 2>/dev/null && echo "models.tar.zst" || echo "models.tar.zst.EMPTY") \
    || fail "Archive creation failed"

ARCHIVE_SIZE="$(du -h "$STAGING_DIR/$ARCHIVE_NAME" | cut -f1)"
log "Archive ready: $ARCHIVE_NAME ($ARCHIVE_SIZE)"

# ── Step 7: Upload to Google Drive ─────────────────────────────────────
DAY_OF_WEEK="$(date -u +%u)"  # 1=Monday ... 7=Sunday

if [[ "$DAY_OF_WEEK" -eq 7 ]]; then
    DEST_FOLDER="weekly"
    RETENTION="$WEEKLY_RETENTION_COUNT"
    log "Sunday — uploading to weekly/"
else
    DEST_FOLDER="daily"
    RETENTION="$DAILY_RETENTION_COUNT"
    log "Weekday — uploading to daily/"
fi

REMOTE_PATH="${RCLONE_REMOTE}:${GDRIVE_BASE}/${DEST_FOLDER}/"

log "Uploading to ${REMOTE_PATH}..."
rclone copy "$STAGING_DIR/$ARCHIVE_NAME" "$REMOTE_PATH" \
    --progress \
    || fail "rclone upload failed"
log "Upload complete"

# ── Step 8: Rotate old backups ─────────────────────────────────────────
log "Rotating old backups (keeping $RETENTION in $DEST_FOLDER/)..."

# List files oldest first, extract names of those beyond retention limit
REMOTE_FILES="$(rclone lsf "$REMOTE_PATH" --files-only -t 2>/dev/null | sort)"
FILE_COUNT="$(echo "$REMOTE_FILES" | grep -c . || true)"

if [[ "$FILE_COUNT" -gt "$RETENTION" ]]; then
    DELETE_COUNT=$((FILE_COUNT - RETENTION))
    log "Found $FILE_COUNT backups, deleting oldest $DELETE_COUNT..."

    echo "$REMOTE_FILES" | head -n "$DELETE_COUNT" | while IFS= read -r old_file; do
        [[ -z "$old_file" ]] && continue
        log "  deleting $old_file"
        rclone deletefile "${REMOTE_PATH}${old_file}" || log "WARNING: failed to delete $old_file"
    done
else
    log "Only $FILE_COUNT backups — no rotation needed"
fi

# ── Done ───────────────────────────────────────────────────────────────
log "Backup completed successfully"
