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
