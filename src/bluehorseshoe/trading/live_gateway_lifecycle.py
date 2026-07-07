"""Lifecycle helpers for the persistent `ib-gateway-live` container.

The live Gateway runs continuously (started by `docker compose up -d`),
authenticated once with 2FA. IBC's auto-restart token keeps the
session alive for ~7 days across daily restarts without re-auth. Two
public entry points:

  - snapshot_live_account() : just snapshot, assumes container is up
  - refresh_token()         : force a fresh login NOW (triggers 2FA
                              push), used to reset the 7-day window
                              while the phone is in hand
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKER_DIR = REPO_ROOT / "docker"
SERVICE = "ib-gateway-live"
# IBC's LoginDialogDisplayTimeout is 60s and
# SecondFactorAuthenticationTimeout is 180s — match the longer.
READY_TIMEOUT_S = 240
# Shorter window for the no-2FA "is it already up?" probe used by the
# snapshot path. If it doesn't answer in 8s the session is probably
# either yielded to the phone or the token has expired.
QUICK_PROBE_TIMEOUT_S = 8
POLL_INTERVAL_S = 3.0
PROBE_CLIENT_ID = 99


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=DOCKER_DIR, check=check, capture_output=True, text=True,
    )


def _api_handshake_ok(host: str, port: int) -> bool:
    """Attempt a real ib_async connect+disconnect. TCP-open != API-ready
    (the gnzsnz image's port forwarder accepts before IBC is serving),
    so we have to drive an actual handshake."""
    try:
        import ib_async  # noqa: PLC0415
    except ImportError:
        return False
    ib = ib_async.IB()
    try:
        ib.connect(host, port, clientId=PROBE_CLIENT_ID, timeout=4,
                   readonly=True)
        connected = ib.isConnected()
        ib.disconnect()
        return connected
    except Exception:  # noqa: BLE001
        try:
            ib.disconnect()
        except Exception:  # noqa: BLE001
            pass
        return False


def _wait_for_api(host: str, port: int, timeout_s: int,
                  cancel: threading.Event | None = None) -> bool:
    """Poll until a real ib_async handshake succeeds, up to timeout_s.

    If ``cancel`` is provided and gets set — an operator pressed
    "Abandon & restart" on the phone page — bail out promptly. The cancel
    is checked *before* each handshake so the superseding refresh isn't left
    fighting this one over probe clientId 99 while it does its own polling.
    """
    deadline = time.monotonic() + timeout_s
    last_dot = 0.0
    while time.monotonic() < deadline:
        if cancel is not None and cancel.is_set():
            print(" (abandoned)")
            return False
        if _api_handshake_ok(host, port):
            print()
            return True
        now = time.monotonic()
        if now - last_dot > 2.5:
            print(".", end="", flush=True)
            last_dot = now
        time.sleep(POLL_INTERVAL_S)
    print()
    return False


def _container_running() -> bool:
    """Check if the live Gateway container is up (any state)."""
    try:
        res = _compose("ps", "--status=running", "--format", "{{.Name}}",
                       check=False)
        return SERVICE in (res.stdout or "")
    except Exception:  # noqa: BLE001
        return False


def snapshot_live_account() -> int:
    """Snapshot the live account. Assumes the Gateway is already up.

    Prints a clear message and returns non-zero if the Gateway isn't
    running, isn't responsive, or has yielded its session to the phone.
    """
    host = os.environ.get("IBKR_HOST_LIVE", "127.0.0.1")
    port = int(os.environ.get("IBKR_PORT_LIVE", "4011"))

    if not _container_running():
        print(
            f"ERROR: {SERVICE} is not running. Start it with:\n"
            f"  cd docker && docker compose up -d {SERVICE}\n"
            f"First-time start requires phone-based 2FA approval. "
            f"After that, use `-s --refresh-token` to roll the 7-day "
            f"session window.", file=sys.stderr)
        return 1

    if not _api_handshake_ok(host, port):
        # One more quick poll in case IBC just restarted on schedule.
        print(f"Gateway slow to respond — quick retry ", end="", flush=True)
        if not _wait_for_api(host, port, QUICK_PROBE_TIMEOUT_S):
            print(
                f"ERROR: {SERVICE} is up but the API isn't accepting "
                f"connections.\n"
                f"Likely causes:\n"
                f"  (1) Phone is currently logged into the IBKR Mobile "
                f"app — Gateway has yielded the session. Close the "
                f"phone session and retry in a few seconds.\n"
                f"  (2) Auto-restart token has expired (>7 days since "
                f"last 2FA). Refresh with `-s --refresh-token` while "
                f"phone is in hand.\n"
                f"Logs: cd docker && docker compose logs --tail=50 "
                f"{SERVICE}", file=sys.stderr)
            return 2

    from bh_live_status import main as snapshot_main  # noqa: PLC0415
    return snapshot_main([])


def refresh_token(cancel: threading.Event | None = None) -> int:
    """Force a fresh 2FA login to roll the auto-restart token's 7-day
    window. Restarts the container, waits for IBC to authenticate (you
    approve the 2FA push on your phone), then verifies the API is live.

    Run this while your phone is in hand — typically right after using
    the IBKR Mobile app, so the 2FA push lands on a phone you're
    already looking at.

    ``cancel`` lets a caller abandon the wait early (the phone page's
    "Abandon & restart" button). When it's set mid-poll this returns 2
    ("abandoned") rather than 1 ("timed out"), so the caller can tell an
    operator-superseded refresh apart from a real 2FA failure.
    """
    host = os.environ.get("IBKR_HOST_LIVE", "127.0.0.1")
    port = int(os.environ.get("IBKR_PORT_LIVE", "4011"))

    if not _container_running():
        print(f"{SERVICE} not running; starting it (first-time setup).",
              flush=True)
        try:
            _compose("up", "-d", SERVICE)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: failed to start {SERVICE}: {e.stderr or e}",
                  file=sys.stderr)
            return 1
    else:
        print(f"Restarting {SERVICE} to force fresh login...", flush=True)
        try:
            _compose("restart", SERVICE)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: failed to restart {SERVICE}: {e.stderr or e}",
                  file=sys.stderr)
            return 1

    print(f"Waiting for API at {host}:{port}. "
          f"IBKR Mobile will push a 2FA prompt — approve it on your "
          f"phone. Polling up to {READY_TIMEOUT_S}s ",
          end="", flush=True)
    if not _wait_for_api(host, port, READY_TIMEOUT_S, cancel=cancel):
        if cancel is not None and cancel.is_set():
            print(f"Abandoned {SERVICE} refresh in favour of a newer request.",
                  file=sys.stderr)
            return 2
        print(f"ERROR: {SERVICE} did not authenticate within "
              f"{READY_TIMEOUT_S}s. Did the 2FA push arrive? "
              f"Logs: cd docker && docker compose logs --tail=50 "
              f"{SERVICE}", file=sys.stderr)
        return 1

    print(f"Token refreshed. 7-day window starts now. "
          f"Subsequent `-s --live` snapshots will be instant.")
    return 0
