# Research Droplet Setup

Two-droplet architecture: production runs daily workflows undisturbed, research runs on a separate on-demand droplet that connects to production's MongoDB over VPC.

## Architecture

- **Production droplet** (always-on, 4GB): API server, daily `-u`/`-p`, IBKR gateway, MongoDB
- **Research droplet** (on-demand, 8GB): Backtests, weight optimization, indicator analysis

Both droplets share the same DigitalOcean VPC (private 10.x.x.x network). Research connects to production's MongoDB over the VPC — no local Mongo needed.

## Prerequisites

### On the production droplet

1. Set `MONGO_BIND_IP` in `docker/.env` to the droplet's VPC private IP:
   ```
   MONGO_BIND_IP=10.116.0.2    # Replace with your actual VPC IP
   ```

2. Restart production containers to apply the port binding:
   ```bash
   cd docker && docker compose up -d
   ```

3. Verify MongoDB is listening on the VPC IP:
   ```bash
   ss -tlnp | grep 27017
   # Should show 10.116.0.2:27017
   ```

## Create the research droplet

1. **Create droplet** on DigitalOcean:
   - Image: Ubuntu 22.04
   - Size: 8GB / 4 vCPU (~$0.071/hr)
   - Region: Same as production
   - VPC: Same VPC as production
   - Add your SSH key

2. **Install Docker** on the new droplet:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```

3. **Clone the repo:**
   ```bash
   git clone <repo-url> BlueHorseshoe
   cd BlueHorseshoe
   ```

4. **Configure environment:**
   ```bash
   cp docker/env.research.example docker/.env.research
   # Edit docker/.env.research — set MONGO_URI to production VPC IP:
   #   MONGO_URI=mongodb://10.116.0.2:27017
   ```

5. **Start the research container:**
   ```bash
   cd docker && docker compose -f docker-compose.research.yml --env-file .env.research up -d
   ```

6. **Verify connectivity:**
   ```bash
   docker exec bh-research python -c "
   from pymongo import MongoClient
   c = MongoClient('mongodb://10.116.0.2:27017')
   print('Documents:', c.bluehorseshoe.historical_prices_recent.count_documents({}))
   "
   ```

## Running research

```bash
# Backtests
docker exec bh-research python src/main.py -t 2025-01-15
docker exec bh-research python src/main.py -t 2025-01-15 --end 2025-02-15 --interval 7

# Weight optimization
docker exec bh-research python src/main.py -o

# Versioned backtests
docker exec bh-research python src/run_clean_backtest.py --version v2
docker exec bh-research python src/run_clean_backtest.py --version v3

# Comparison scripts
docker exec bh-research python src/compare_clean_backtests.py
docker exec bh-research python src/compare_v2_v3.py

# Indicator analysis
docker exec bh-research python src/analyze_indicator_impact.py
```

## Teardown

When done with research, **destroy the droplet** to stop billing:

```bash
# From your local machine or DigitalOcean console:
doctl compute droplet delete <research-droplet-id>
```

The research droplet is fully disposable — all code is in git, all data is in production's MongoDB. Nothing is lost by destroying it.

## Security notes

- MongoDB has no authentication. This is safe because:
  - VPC traffic is isolated at the hypervisor level
  - Port 27017 is only bound to the private VPC IP, not the public interface
  - Only droplets in the same VPC can reach it
- Research workloads are read-only (backtests and analysis only read data)
- Future: add MongoDB auth (`--auth` + user/password) if adding more droplets or collaborators
