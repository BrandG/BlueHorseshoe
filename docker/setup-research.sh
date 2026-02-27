#!/usr/bin/env bash
# ==========================================================================
# Research Droplet One-Shot Setup
# Run this after SSH'ing into the new droplet: ssh root@104.236.127.169
#
# Usage: curl -s <raw-url> | bash
#   — or paste the contents directly into the terminal
# ==========================================================================
set -euo pipefail

REPO_URL="https://github.com/BrandG/BlueHorseshoe.git"
MONGO_VPC_IP="10.132.0.2"
TIINGO_API_KEY="8704362c5fcc8009fd7521e794fdb0b292b08006"

echo "=== 1/5 Installing Docker ==="
curl -fsSL https://get.docker.com | sh

echo "=== 2/5 Cloning repo ==="
cd /root
git clone "$REPO_URL" BlueHorseshoe
cd BlueHorseshoe

echo "=== 3/5 Creating .env.research ==="
cat > docker/.env.research <<EOF
MONGO_URI=mongodb://${MONGO_VPC_IP}:27017
MONGO_DB=bluehorseshoe
TIINGO_API_KEY=${TIINGO_API_KEY}
TIINGO_CPS=5
EOF

echo "=== 4/5 Building and starting container ==="
cd docker
docker compose -f docker-compose.research.yml --env-file .env.research up -d --build

echo "=== 5/5 Verifying MongoDB connectivity ==="
sleep 5
docker exec bh-research python -c "
from pymongo import MongoClient
c = MongoClient('mongodb://${MONGO_VPC_IP}:27017', serverSelectionTimeoutMS=5000)
count = c.bluehorseshoe.historical_prices_recent.count_documents({})
print(f'Connected! historical_prices_recent has {count:,} documents')
"

echo ""
echo "=== Setup complete ==="
echo "Run research with:"
echo "  docker exec bh-research python src/main.py -t 2025-01-15"
echo "  docker exec bh-research python src/run_clean_backtest.py --version v2"
echo ""
echo "When done, destroy this droplet to stop billing."
