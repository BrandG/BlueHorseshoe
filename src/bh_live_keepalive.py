"""Keep the ib-gateway-live session warm and the autorestart token rolling.

IBKR's API session goes idle after ~3-4 hours with no client activity. Once
idle-expired, the gateway accepts TCP connections (so socat reports it as
up) but rejects every new client at the auth layer — silently, without
firing any dialog IBC could handle to recover. Diagnosed 2026-05-20 after
a 4h34m idle window left the live gateway in a zombie session.

This script does one minimal authenticated read (get_account_summary) every
tick. That serves two purposes:
  1. Resets IBKR's idle-session clock so the API stays warm.
  2. Counts as activity for IBC's 7-day autorestart token tracking, so
     the token keeps rolling across daily restarts.

Designed for cron at `*/30 * * * *` (24/7). Silent on success, logs on
failure. Uses a dedicated client_id (8) to avoid colliding with
bh_live_status (11) or the live_gateway_lifecycle probe (99).
"""
from __future__ import annotations

import logging
import os
import sys

from bluehorseshoe.data.ibkr_client import IBKRClient, IBKRConfig

KEEPALIVE_CLIENT_ID = 8
HOST = os.environ.get("IBKR_HOST_LIVE", "127.0.0.1")
PORT = int(os.environ.get("IBKR_PORT_LIVE", "4011"))

logger = logging.getLogger("bh_live.keepalive")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    logging.Formatter.converter = __import__("time").gmtime
    # ib_async is chatty at INFO — pin to WARNING so the keepalive log
    # stays signal-only.
    for noisy in ("ib_async.wrapper", "ib_async.client", "ib_async.ib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    client = IBKRClient(IBKRConfig(
        host=HOST, port=PORT, client_id=KEEPALIVE_CLIENT_ID,
        timeout=10.0, read_only=True,
    ))
    try:
        account = client.get_account_summary()
    except Exception as e:  # noqa: BLE001
        logger.error("keepalive failed (exception): %s", e)
        return 1
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass

    if not account.get("account_id"):
        # Blank account_id = the gateway didn't actually answer (stub of
        # zeros from IBKRClient's swallow-on-error contract).
        logger.warning("keepalive failed: empty account summary (gateway unreachable or session dead)")
        return 2

    # Silent on success — cron log stays uncluttered. The fact that we
    # got here means the session is alive.
    return 0


if __name__ == "__main__":
    sys.exit(main())
