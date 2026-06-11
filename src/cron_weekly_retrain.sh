#!/bin/bash
# Weekly Data Maintenance Script for BlueHorseshoe
# Updates the symbol universe, historical data, fundamentals, and news.
#
# ML retraining RETIRED 2026-06-11: the overlay win-prob models carry no selection
# signal (test AUC ~0.50, see project_deep_os_ml_selection) and are display-only;
# retraining them weekly was maintenance spend on a dead input. The --retrain
# maintenance command still exists for manual/research use.
#
# Filename kept (crontab points here). Crontab entry (every Sunday at 2 AM UTC):
# 0 2 * * 0 /root/BlueHorseshoe/src/cron_weekly_retrain.sh >> /root/BlueHorseshoe/src/logs/cron_retrain.log 2>&1

REPO="/root/BlueHorseshoe"
PYTHON="$REPO/.venv/bin/python"
export PYTHONPATH="$REPO/src"
cd "$REPO"

# Load .env so cron has ALPHAVANTAGE_KEY, MONGO_URI, etc. (cron does not inherit the
# interactive shell environment). Without this, every --symbols/--history fetch fails
# with "ALPHAVANTAGE_KEY not set" and authenticated Mongo is unreachable.
# Mirrors run_daily_pipeline.sh.
if [ -f "$REPO/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    export "$line" 2>/dev/null || true
  done < "$REPO/.env"
fi

EXEC="$PYTHON -m bluehorseshoe.core.maintenance"

echo "--- Weekly Maintenance Started: $(date) ---"

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

# (Step 4, ML model retraining, retired 2026-06-11 — see header.)

echo "--- Weekly Maintenance Finished: $(date) ---"
