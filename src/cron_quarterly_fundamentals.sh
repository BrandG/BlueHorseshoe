#!/bin/bash
# Quarterly/weekly fundamentals refresh for PIT solvency data.

REPO="/root/BlueHorseshoe"
PYTHON="$REPO/.venv/bin/python"
export PYTHONPATH="$REPO/src"
cd "$REPO"

if [ -f "$REPO/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    export "$line" 2>/dev/null || true
  done < "$REPO/.env"
fi

echo "--- Quarterly Fundamentals Refresh Started: $(date) ---"

$PYTHON -m bluehorseshoe.data.fundamentals_pull
if [ $? -ne 0 ]; then
    echo "ERROR: fundamentals refresh failed at $(date)"
    exit 1
fi

echo "--- Quarterly Fundamentals Refresh Finished: $(date) ---"
