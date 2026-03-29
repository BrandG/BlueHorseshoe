#!/bin/bash
# Wrapper to run BlueHorseshoe Python commands on the host.
# Usage: ./run.sh python src/main.py -p
#        ./run.sh pytest src/tests/
#        ./run.sh ./lint.sh
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$REPO_DIR/.venv/bin/activate"
export PYTHONPATH="$REPO_DIR/src"
cd "$REPO_DIR"
if [ -f "$REPO_DIR/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    # Skip comments and empty lines
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    export "$line" 2>/dev/null || true
  done < "$REPO_DIR/.env"
fi
exec "$@"
