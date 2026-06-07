#!/bin/bash
# Weekly ML Model Retraining Script for BlueHorseshoe
# Updates the symbol universe, historical data, fundamentals, news, and retrains ML models.
#
# Crontab entry (every Sunday at 2 AM UTC):
# 0 2 * * 0 /root/BlueHorseshoe/src/cron_weekly_retrain.sh >> /root/BlueHorseshoe/src/logs/cron_retrain.log 2>&1

REPO="/root/BlueHorseshoe"
PYTHON="$REPO/.venv/bin/python"
export PYTHONPATH="$REPO/src"
cd "$REPO"

# Load .env so cron has ALPHAVANTAGE_KEY, MONGO_URI, etc. (cron does not inherit the
# interactive shell environment). Without this, every --symbols/--history fetch fails
# with "ALPHAVANTAGE_KEY not set" and --retrain can't reach authenticated Mongo.
# Mirrors run_daily_pipeline.sh.
if [ -f "$REPO/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    export "$line" 2>/dev/null || true
  done < "$REPO/.env"
fi

EXEC="$PYTHON -m bluehorseshoe.core.maintenance"

echo "--- Weekly Retraining Started: $(date) ---"

# 1. Update Symbol Universe
$EXEC --symbols
if [ $? -ne 0 ]; then
    echo "ERROR: Symbol update failed at $(date)"
    exit 1
fi

# 2. Update Recent Price History
$EXEC --history
if [ $? -ne 0 ]; then
    echo "ERROR: History update failed at $(date)"
    exit 1
fi

# 3. Update Fundamentals & News
$EXEC --overviews
$EXEC --news

# 4. Retrain ML Models
$EXEC --retrain --limit 10000
if [ $? -ne 0 ]; then
    echo "ERROR: ML retraining failed at $(date)"
    exit 1
fi

echo "--- Weekly Retraining Finished: $(date) ---"
