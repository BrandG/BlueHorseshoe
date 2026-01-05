#!/bin/bash
# Weekly ML Model Retraining Script for BlueHorseshoe
# This script updates the symbol universe, historical data, and retrains the ML models.
#
# To install this as a weekly cron job (e.g., every Sunday at 2 AM):
# 0 2 * * 0 /root/BlueHorseshoe/src/cron_weekly_retrain.sh >> /root/BlueHorseshoe/src/logs/cron_retrain.log 2>&1

PROJECT_DIR="/root/BlueHorseshoe"
cd $PROJECT_DIR

echo "--- Weekly Retraining Started: $(date) ---"

# 1. Update Symbol Universe
./maintenance.sh --symbols

# 2. Update Recent Price History
./maintenance.sh --history

# 3. Update Fundamentals & News (limited to ensure completion if needed, or full)
./maintenance.sh --overviews
./maintenance.sh --news

# 4. Retrain ML Models (using a larger limit for production)
./maintenance.sh --retrain --limit 10000

echo "--- Weekly Retraining Finished: $(date) ---"
