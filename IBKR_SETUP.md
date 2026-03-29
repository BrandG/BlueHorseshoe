# IBKR Gateway Setup — Status & Next Steps

**Last Updated:** March 27, 2026

## Current State

The IB Gateway container is running but **not connected to IBKR**. Authentication fails with "server error" during the automated login flow. The trade journal system is fully built and wired into the daily cron pipeline, but the IBKR fill import step (`--journal-import-ibkr`) returns 0 fills because the gateway has no active connection.

## What's Already Done

### Infrastructure
- `ib-gateway` service defined in `docker/docker-compose.yml` using `ghcr.io/gnzsnz/ib-gateway:latest`
- Container runs on the same Docker network as `bluehorseshoe` and `mongo`
- Socat forwards port 4004 → 4002 (IB API port)
- VNC port 5900 is mapped but **this image doesn't include a VNC server** (uses Xvfb headless)

### Configuration (`docker/.env`)
```
TWS_USERID=hxnvew795          # Paper account username
TWS_PASSWORD=***               # Set and verified correct
TRADING_MODE=paper
IBKR_READ_ONLY=yes             # Needs to be "not" for order placement
PAPER_TRADING_ENABLED=false    # Needs to be "true" to activate
IBKR_HOST=ib-gateway
IBKR_PORT=4004
IBKR_CLIENT_ID=1
```

### BlueHorseshoe Code
- `IBKRClient` in `src/bluehorseshoe/data/ibkr_client.py` — full client with `place_bracket_order()`, `get_executions()`, `get_commissions()`, `get_quote()`, `get_open_orders()`
- `PaperTrader` in `src/bluehorseshoe/trading/paper_trader.py` — splits positions into T1/T2 bracket orders, writes `trade_orders` linked to `trade_ideas`
- Trade journal system (5 phases) fully implemented and wired into daily cron pipeline
- Idea logging fires automatically during `-p` (10 ideas logged successfully on 2026-03-23)

### IBC Config (`/home/ibgateway/ibc/config.ini` inside container)
- `TrustedIPs=127.0.0.1` — may need updating if bluehorseshoe connects from a different Docker IP
- `TWOFA_TIMEOUT_ACTION=restart` — auto-restarts on 2FA timeout
- `ACCEPT_INCOMING_CONNECTION=accept` — set in docker-compose env

## The Problem

Gateway authenticates credentials, clicks "Paper Log In", then gets:
```
Attempt 1: server error, will retry in 4 seconds...
```
Followed by untitled dialog popups that IBC can't handle. No further retries occur.

### What We Ruled Out
- **Credentials** — paper account username (`hxnvew795`) and password verified correct by manual web login
- **2FA** — manual web login did not require 2FA
- **Concurrent sessions** — logged out of all web sessions before retrying
- **Container networking** — socat forwarding is working (port 4004 listens)
- **Account provisioning** — paper account accessible and functional via web

### Most Likely Cause
IBKR paper accounts typically authenticate through the **live account credentials** with `TRADING_MODE=paper`, not with the paper account's own username. The gateway may need:

```
TWS_USERID=<live account username>
TWS_PASSWORD=<live account password>
TRADING_MODE=paper
```

This was suggested but not yet tested.

## Next Steps (in order)

### 1. Try live account credentials
Update `docker/.env`:
```
TWS_USERID=<your live IBKR username>
TWS_PASSWORD=<your live IBKR password>
TRADING_MODE=paper
```
Then:
```bash
cd /root/BlueHorseshoe/docker && docker compose restart ib-gateway
sleep 45
docker logs ib-gateway --tail 30
```
If you see "Authentication complete" instead of "server error", it worked.

### 2. Verify API port is listening
```bash
docker exec ib-gateway bash -c "cat /proc/net/tcp" | tail -n +2 | \
  awk '{split($2,a,":"); printf "%d\n", strtonum("0x"a[2])}' | sort -un
```
Should show both `4002` and `4004` (not just 4004).

### 3. Test connection from BlueHorseshoe
```bash
docker exec bluehorseshoe python -c "
from bluehorseshoe.data.ibkr_client import IBKRClient, IBKRConfig
client = IBKRClient(IBKRConfig(host='ib-gateway', port=4004, read_only=True))
print('Connected:', client.is_connected())
quote = client.get_quote('SPY')
print(f'SPY: last={quote.last}, error={quote.error}')
client.close()
"
```

### 4. Enable paper trading
Once the gateway connects, update `docker/.env`:
```
PAPER_TRADING_ENABLED=true
IBKR_READ_ONLY=not
```
Then:
```bash
cd /root/BlueHorseshoe/docker && docker compose up -d
```

### 5. Test the full flow
```bash
# Test order placement (will submit a real paper trade)
docker exec bluehorseshoe python -c "
from bluehorseshoe.data.ibkr_client import IBKRClient, IBKRConfig
client = IBKRClient(IBKRConfig(host='ib-gateway', port=4004, read_only=False))
result = client.place_bracket_order('SPY', 1, 400.00, 410.00, 390.00)
print(result)
client.close()
"

# Test fill retrieval
docker exec bluehorseshoe python src/main.py --journal-import-ibkr
```

### 6. If live credentials don't work either
- **Switch to VNC-enabled image** — change docker-compose to use an image tag that includes a VNC server, so you can see and interact with the gateway UI:
  ```yaml
  ib-gateway:
    image: ghcr.io/gnzsnz/ib-gateway:latest-vnc
  ```
  Then connect via VNC to `localhost:5900` (SSH tunnel if remote) to see what dialog/error the gateway is actually showing.

- **Enable API access in TWS first** — download Trader Workstation desktop app, log in, go to Edit → Global Configuration → API → Settings → Enable ActiveX and Socket Clients. This sets the account-level API permission that the gateway needs.

- **Check IBKR security settings** — in Account Management, look for any IP restrictions or API access controls that might block the Docker container's connection.

## Useful Commands

```bash
# Gateway status
docker logs ib-gateway --tail 30

# Restart gateway
cd /root/BlueHorseshoe/docker && docker compose restart ib-gateway

# Check if API port is up
docker exec ib-gateway bash -c "cat /proc/net/tcp" | tail -n +2 | \
  awk '{split($2,a,":"); printf "%d\n", strtonum("0x"a[2])}' | sort -un

# Check for orphaned processes (DuckDB lock issue)
docker top bluehorseshoe

# Restart BH container (clears orphaned processes)
cd /root/BlueHorseshoe/docker && docker compose restart bluehorseshoe
```
