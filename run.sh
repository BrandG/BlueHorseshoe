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
exec "$@"
