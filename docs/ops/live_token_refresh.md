# Live IBKR Token Refresh — phone button (ops)

Phone-triggerable endpoint that rolls the **live** IB Gateway's 7-day 2FA
session window. Tap it while the IBKR Mobile app is in hand so the 2FA push
lands on the phone you're holding.

The application code is in the repo (`src/bluehorseshoe/api/live_token.py`,
`live_token_app.py`, wired into `config.py` / `api/main.py`). **This file
records the parts that live OUTSIDE the repo** — systemd, nginx, firewall —
so they aren't lost on a rebuild. All were applied on the dev droplet
(134.122.15.186) on 2026-06-17.

## How to use

Bookmark on the phone (HTTPS, real Let's Encrypt cert via the dailylitbits
vhost; the token is the `LIVE_REFRESH_TOKEN` secret from `.env`):

```
https://dailylitbits.com/api/v1/live/refresh-token?token=<LIVE_REFRESH_TOKEN>
```

Opening the page is **safe** — it only shows status. Tapping **Roll token now**
(`?go=1`) restarts `ib-gateway-live` and triggers one 2FA push; approve it on the
phone. The page polls up to 240s and lands on **Success**.

## Architecture (why a separate localhost service)

The main API (`bluehorseshoe-api`, :8001) exposes UNAUTHENTICATED heavy
endpoints (`/pipeline/run`, `/predict`). To avoid ever exposing those, the
phone button runs as its own mini-service bound to **127.0.0.1:8011** and is
reachable from the internet ONLY through the nginx 443 reverse proxy. No new
internet-facing port is opened; the secret travels over TLS.

```
phone → https://dailylitbits.com/api/v1/live/refresh-token
      → nginx :443 (location /api/v1/live/refresh-token)
      → 127.0.0.1:8011  (bluehorseshoe-token.service, uvicorn live_token_app:app)
      → refresh_token()  → restarts ib-gateway-live (4011) → 2FA push
```

## systemd: `/etc/systemd/system/bluehorseshoe-token.service`

```ini
[Unit]
Description=BlueHorseshoe Live-Token Refresh (phone-facing, localhost-only)
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/BlueHorseshoe
Environment=PYTHONPATH=/root/BlueHorseshoe/src
ExecStart=/root/BlueHorseshoe/.venv/bin/uvicorn bluehorseshoe.api.live_token_app:app --host 127.0.0.1 --port 8011
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`WorkingDirectory` must be the repo root so pydantic reads `.env` for
`LIVE_REFRESH_TOKEN`. (Empty/unset token ⇒ endpoint returns 503, i.e. disabled.)

## nginx: `/etc/nginx/sites-available/app_router`

Added inside the `dailylitbits.com` **443** server block (above its `location /`):

```nginx
location /api/v1/live/refresh-token {
    proxy_pass http://127.0.0.1:8011;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

The port-80 catch-all `default_server` used to `proxy_pass` `/` → `:8001`,
exposing the whole main API over plain HTTP. It now `return 444;` (drops without
a response). The API is reachable locally only (127.0.0.1:8001 or via SSH
tunnel).

## Firewall (this box has NO ufw — pure iptables)

ufw is uninstalled (`dpkg` state `rc`); INPUT policy is `ACCEPT` with empty ufw
chains, so host ports are open unless explicitly dropped. There is no
DigitalOcean cloud firewall. Two persisted drops hold the line (saved via
`netfilter-persistent` → `/etc/iptables/rules.v4`):

```
iptables -I INPUT       -i eth0 -p tcp --dport 8001 -j DROP                       # main API off the internet
iptables -I DOCKER-USER -i eth0 -p tcp -m multiport --dports 4001,4002,4004,4011,5900,8002 -j DROP   # VNC + gateways
```

Container ports bypass the INPUT chain (Docker DNAT → FORWARD), which is why the
gateway/VNC drops live in `DOCKER-USER`, not `INPUT`. Local services reach the
gateways over `127.0.0.1`/`lo`, so the drops don't affect the trading stack.

## Operations

- **Status / logs:** `systemctl status bluehorseshoe-token`,
  `journalctl -u bluehorseshoe-token -f`
- **Stop the button entirely (kill switch):** `systemctl stop bluehorseshoe-token`
- **Watch a refresh:** `docker logs ib-gateway-live -f` — look for
  `Login has completed` then the API listener coming up. The 240s poll only
  *looks* hung; it's waiting for your 2FA approval.
- **Recover from the command line** (no phone page needed), safe during `-u`/`-p`
  (short-circuits before the heavy pipeline):
  ```
  ./run.sh python src/main.py -s --refresh-token
  ```

## History / gotcha

First live test (2026-06-17) looped: each `refresh_token()` cycle *succeeded*,
but the page's `<meta refresh>` re-requested the same URL — which still carried
`&go=1` — so the moment a run finished, the 5s auto-refresh fired `go=1` again,
restarting the gateway and demanding another 2FA push (~5 before we caught it).
Fixed in `_render_page`: the auto-refresh now targets a go-less URL
(`content="5; url=?token=…"`). **Lesson: never put the trigger param in a URL the
page auto-refreshes.**

## Pending proper fix

The container ports are protected by the `DOCKER-USER` drop, but the durable fix
is to bind the compose publishes to loopback in `docker/docker-compose.yml`
(`127.0.0.1:4004:4004`, `127.0.0.1:5900:5900`, `4011:4003`→`127.0.0.1:4011:4003`).
That recreates the gateway containers (restarts trading infra + triggers a
live-gateway 2FA), so do it in a planned window — never during `-p`/`-u`.
