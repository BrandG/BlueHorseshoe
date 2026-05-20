# IB Gateway: raw vs. socat-wrapped API ports

The `ghcr.io/gnzsnz/ib-gateway` image runs the IBC-managed API on two
internal ports per trading mode:

| TRADING_MODE | Raw API port | socat-wrapped port |
|--------------|--------------|--------------------|
| paper        | 4002         | 4004               |
| live         | 4001         | 4003               |

**Always map the host port to the socat-wrapped port**, not the raw
port. The raw port rejects connections whose source IP isn't already
in `TrustedTwsApiClientIPs`, and the docker bridge makes host
connections appear as a non-loopback IP, so they get silently
rejected. Symptoms:

- `Connection reset by peer` from `ib_async`
- No entries in the container logs about a client connecting

The socat-wrapped port bypasses this because socat re-originates the
connection from inside the container.

## Evidence

BlueHorseshoe's paper Gateway maps `4004:4004` (socat) and works.
The first attempt at the live Gateway mapped `4011:4001` (raw) and
timed out for 240s despite IBC reporting "Login has completed" after
7s. Switching to `4011:4003` (socat) made it work immediately.

The container log line below is the giveaway:

```
Forking :::4001 onto 0.0.0.0:4003 > trading mode live
```

## Apply when

Any time you add or modify an `ib-gateway` compose service for this
project (paper, live, or a future test instance), confirm the host
port maps to the socat-wrapped container port, not the raw one. Saves
hours of "but the login succeeded, why won't it accept my client?"

