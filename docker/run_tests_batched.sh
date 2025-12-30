#!/usr/bin/env bash
set -e

# Navigate to the directory where docker-compose.yml lives
cd "$(dirname "$0")"

echo "Collecting tests from the bluehorseshoe container..."
# Collect tests, filtering out noise
TESTS=$(docker compose exec -T bluehorseshoe pytest --collect-only -q | grep "::" || true)

if [ -z "$TESTS" ]; then
  echo "No tests found."
  exit 0
fi

TOTAL=$(echo "$TESTS" | wc -l)
BATCH_SIZE=10
echo "Found $TOTAL tests. Running in batches of $BATCH_SIZE..."

# Use xargs to run pytest in batches
# -L 10 tells xargs to take 10 lines at a time
echo "$TESTS" | xargs -L $BATCH_SIZE docker compose exec -T bluehorseshoe pytest
