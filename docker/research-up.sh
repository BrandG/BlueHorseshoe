#!/usr/bin/env bash
# ==========================================================================
# Spin up the research droplet (run from production server)
#
# Usage:
#   bash docker/research-up.sh           # Default 8GB / 4 vCPU
#   bash docker/research-up.sh s-2vcpu-4gb   # Custom size (cheaper)
# ==========================================================================
set -euo pipefail

SIZE="${1:-s-4vcpu-8gb}"
REGION="nyc3"
VPC_UUID="953f4856-dc84-11e8-80bc-3cfdfea9fba1"
SSH_KEYS="3072866,54444403"
NAME="bh-research"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Creating research droplet ($SIZE in $REGION) ==="

# Check if it already exists
if doctl compute droplet list --format Name --no-header | grep -q "^${NAME}$"; then
    echo "ERROR: Droplet '$NAME' already exists."
    echo "Destroy it first:  bash docker/research-down.sh"
    echo ""
    doctl compute droplet list --format ID,Name,PublicIPv4,PrivateIPv4,Status --no-header | grep "$NAME"
    exit 1
fi

# Create and wait for it to come online
RESULT=$(doctl compute droplet create "$NAME" \
    --region "$REGION" \
    --size "$SIZE" \
    --image ubuntu-24-04-x64 \
    --ssh-keys "$SSH_KEYS" \
    --vpc-uuid "$VPC_UUID" \
    --format ID,PublicIPv4,PrivateIPv4 \
    --no-header \
    --wait)

DROPLET_ID=$(echo "$RESULT" | awk '{print $1}')
PUBLIC_IP=$(echo "$RESULT" | awk '{print $2}')
VPC_IP=$(echo "$RESULT" | awk '{print $3}')

echo "Droplet created: ID=$DROPLET_ID  Public=$PUBLIC_IP  VPC=$VPC_IP"

# DigitalOcean recycles VPC IPs in nyc3, so a fresh droplet may collide with a
# stale known_hosts entry. StrictHostKeyChecking=no alone won't bypass a key
# MISMATCH in modern OpenSSH — must purge the entry or skip the file.
for ip in "$VPC_IP" "$PUBLIC_IP"; do
    ssh-keygen -f /root/.ssh/known_hosts -R "$ip" >/dev/null 2>&1 || true
done

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

# Wait for SSH to be ready
echo "=== Waiting for SSH to be ready ==="
for i in $(seq 1 30); do
    if ssh $SSH_OPTS -o ConnectTimeout=5 -o BatchMode=yes "root@${VPC_IP}" "echo ok" &>/dev/null; then
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: SSH not ready after 150s. Droplet may still be booting."
        echo "Try manually: ssh root@${VPC_IP}"
        exit 1
    fi
    sleep 5
done

# Copy and run setup script
echo "=== Running setup script ==="
scp $SSH_OPTS "${SCRIPT_DIR}/setup-research.sh" "root@${VPC_IP}:/root/setup-research.sh"
ssh $SSH_OPTS "root@${VPC_IP}" "bash /root/setup-research.sh"

echo ""
echo "============================================"
echo "  Research droplet is ready!"
echo "============================================"
echo "  VPC IP:    $VPC_IP"
echo "  Public IP: $PUBLIC_IP"
echo "  SSH:       ssh root@${VPC_IP}"
echo ""
echo "  Run research:"
echo "    ssh root@${VPC_IP} \"docker exec bh-research python src/run_clean_backtest.py --version v3\""
echo ""
echo "  Destroy when done:"
echo "    bash docker/research-down.sh"
echo "============================================"
