#!/bin/bash
# BH FTMO V2 autonomous trader — limit-entry production cells (cron wrapper)
# Cron: 16 1,5,9,13,17,21 * * * /root/BlueHorseshoe/run_bh_ftmo_v2_paper.sh
# Runs 1 minute after the rising_3bar paper trader, 11 min after data update.
# Submits LIMIT orders to OANDA practice account. 0.5% NAV risk per trade.

REPO="/root/BlueHorseshoe"
PYTHON="$REPO/.venv/bin/python"
export PYTHONPATH="$REPO/src"
cd "$REPO"

# Load .env so OANDA + SMTP env vars are available
if [ -f "$REPO/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    export "$line" 2>/dev/null || true
  done < "$REPO/.env"
fi

LOG="$REPO/src/logs/bh_ftmo_v2_paper.log"

echo "--- BH FTMO V2 paper started: $(date -u +'%Y-%m-%d %H:%M:%S UTC') ---" >> "$LOG"

$PYTHON src/bud/auto_v2.py >> "$LOG" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
  echo "ERROR: bh_ftmo_v2_paper exit code $EXIT_CODE at $(date -u +'%Y-%m-%d %H:%M:%S UTC')" >> "$LOG"
fi

echo "--- BH FTMO V2 paper finished: $(date -u +'%Y-%m-%d %H:%M:%S UTC') (exit=$EXIT_CODE) ---" >> "$LOG"

exit $EXIT_CODE
