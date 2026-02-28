#!/usr/bin/env bash
# ==========================================================================
# Tear down the research droplet (run from production server)
#
# Usage:
#   bash docker/research-down.sh          # Prompts for confirmation
#   bash docker/research-down.sh --force  # No prompt
# ==========================================================================
set -euo pipefail

NAME="bh-research"
FORCE="${1:-}"
LOGS_DIR="$(cd "$(dirname "$0")/.." && pwd)/src/logs"

# Check if it exists
if ! doctl compute droplet list --format Name --no-header | grep -q "^${NAME}$"; then
    echo "No droplet named '$NAME' found. Nothing to destroy."
    exit 0
fi

# Get droplet info
INFO=$(doctl compute droplet list --format ID,PublicIPv4,PrivateIPv4,Status --no-header | grep "$NAME" || true)
VPC_IP=$(echo "$INFO" | awk '{print $3}')

# Try to copy results before destroying
if [ -n "$VPC_IP" ]; then
    echo "=== Copying results from research droplet ==="
    for f in clean_backtest_v2.csv clean_backtest_v3.csv clean_backtest_v31.csv; do
        REMOTE="/root/BlueHorseshoe/src/logs/$f"
        if ssh -o ConnectTimeout=5 -o BatchMode=yes "root@${VPC_IP}" "test -f $REMOTE" 2>/dev/null; then
            scp "root@${VPC_IP}:${REMOTE}" "${LOGS_DIR}/${f}"
            echo "  Copied $f"
        fi
    done
fi

echo ""
echo "Droplet: $NAME"
echo "$INFO"
echo ""

if [ "$FORCE" = "--force" ]; then
    doctl compute droplet delete "$NAME" --force
    echo "Droplet '$NAME' destroyed."
else
    read -p "Destroy this droplet? Billing stops immediately. [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        doctl compute droplet delete "$NAME" --force
        echo "Droplet '$NAME' destroyed."
    else
        echo "Cancelled."
    fi
fi
