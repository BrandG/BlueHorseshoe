"""Live IBKR gateway watchdog — detect a wedged listener and EMAIL Brand.

The paper-gateway watchdog (run_ibgw_watchdog.sh) force-recreates on a wedge.
The LIVE gateway can't be auto-fixed that way: every (re)start stalls on a
Second Factor Authentication dialog that only Brand can approve from IBKR Mobile
(see project_live_gateway_2fa_wedge). The live session is 7-day, so it lapses
~weekly. Nothing was watching it, so it would silently go dark for ~a day.

This closes the loop: detect the wedge and email Brand to hit the phone-facing
refresh page (https://dailylitbits.com/api/v1/live/refresh-token) — it does NOT
restart anything (a restart with no one to approve the 2FA just re-sticks).

Detection mirrors the paper watchdog: probe the Java API listener INSIDE the
container (port 4001). Host-side 4011 is useless — socat keeps accepting TCP
even when the Java listener is dead (it answered on 4003 while 4001 refused).

Anti-spam state machine (state file in /tmp):
  - healthy: quiet. If we'd alerted, send one RECOVERED email and reset.
  - first seen down: record the time, DON'T alert yet (grace window absorbs a
    normal restart / a refresh in progress, which completes in ~240s).
  - down past the grace window: alert; then re-nudge at most every 6h.

Cron (offset from the other :*/5 jobs):
  3-58/5 * * * *  /root/BlueHorseshoe/run_ibgw_live_watchdog.sh
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

from bluehorseshoe.core.email_service import EmailService

LOG = logging.getLogger("bluehorseshoe.ibgw_live_alert")

CONTAINER = "ib-gateway-live"
JAVA_PORT = 4001                         # live Java API listener inside container
STATE_PATH = Path("/tmp/ibgw_live_watchdog.state")
REFRESH_URL = "https://dailylitbits.com/api/v1/live/refresh-token"

GRACE_SEC = 600                          # down this long before the first alert
REALERT_SEC = 6 * 3600                   # re-nudge cadence while still down


def gateway_listener_up() -> bool:
    """True iff the Java API listener inside the live container accepts a TCP
    connection. docker-exec a /dev/tcp probe with bounded timeouts; any failure
    (listener dead, container down, docker unreachable) counts as not-up."""
    probe = f"timeout 3 bash -c 'exec 3<>/dev/tcp/127.0.0.1/{JAVA_PORT}'"
    try:
        rc = subprocess.run(
            ["docker", "exec", CONTAINER, "bash", "-c", probe],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=8, check=False,
        ).returncode
        return rc == 0
    except (subprocess.TimeoutExpired, OSError) as exc:
        LOG.warning("probe failed (%s): %s", type(exc).__name__, exc)
        return False


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "up", "first_down": None, "last_alert": None}


def _save_state(state: dict) -> None:
    try:
        STATE_PATH.write_text(json.dumps(state), encoding="utf-8")
    except OSError as exc:
        LOG.warning("could not persist state: %s", exc)


def _fmt_duration(seconds: float) -> str:
    mins = int(seconds // 60)
    if mins < 60:
        return f"{mins} min"
    return f"{mins // 60}h {mins % 60}m"


def _send_down_email(down_for: float) -> bool:
    subject = "⚠ BH live IBKR gateway DOWN — needs 2FA token refresh"
    body = (
        f'<p>The live IBKR gateway (<code>{CONTAINER}</code>) API listener has '
        f'been unreachable for <b>{_fmt_duration(down_for)}</b>. Its 7-day 2FA '
        f'session has likely lapsed (or it restarted and is waiting on Second '
        f'Factor Authentication).</p>'
        f'<p><b>To fix:</b> with IBKR Mobile in hand, open your refresh bookmark '
        f'(<a href="{REFRESH_URL}">{REFRESH_URL}</a> — use the version with your '
        f'<code>?token=…</code>), press the button, and approve the push. It '
        f'rolls a fresh 7-day session (~240s to confirm the handshake).</p>'
        f'<p>This is detect-and-notify only; nothing was restarted automatically '
        f'(a restart with no one to approve the 2FA just re-sticks).</p>'
    )
    text = (
        f"The live IBKR gateway ({CONTAINER}) API listener has been unreachable "
        f"for {_fmt_duration(down_for)}. Its 7-day 2FA session has likely lapsed "
        f"(or it restarted and is waiting on Second Factor Authentication).\n\n"
        f"To fix: with IBKR Mobile in hand, open your refresh bookmark "
        f"({REFRESH_URL} — use the version with your ?token=…), press the button, "
        f"and approve the push. It rolls a fresh 7-day session (~240s to confirm "
        f"the handshake).\n\n"
        f"This is detect-and-notify only; nothing was restarted automatically "
        f"(a restart with no one to approve the 2FA just re-sticks)."
    )
    return bool(EmailService().send(subject, html_body=body, text_body=text))


def _send_recovered_email(down_for: float) -> bool:
    subject = "✓ BH live IBKR gateway RECOVERED"
    body = (
        f'<p>The live IBKR gateway (<code>{CONTAINER}</code>) API listener is '
        f'answering again after ~{_fmt_duration(down_for)} down. No action '
        f'needed.</p>'
    )
    text = (
        f"The live IBKR gateway ({CONTAINER}) API listener is answering again "
        f"after ~{_fmt_duration(down_for)} down. No action needed."
    )
    return bool(EmailService().send(subject, html_body=body, text_body=text))


def main() -> int:
    now = time.time()
    state = _load_state()
    up = gateway_listener_up()

    if up:
        if state.get("status") == "down" and state.get("last_alert"):
            down_for = now - (state.get("first_down") or now)
            if _send_recovered_email(down_for):
                LOG.info("live gateway recovered after %s; sent recovery email",
                         _fmt_duration(down_for))
        _save_state({"status": "up", "first_down": None, "last_alert": None})
        return 0

    # Down.
    first_down = state.get("first_down") or now
    last_alert = state.get("last_alert")
    down_for = now - first_down
    should_alert = (
        down_for >= GRACE_SEC
        and (last_alert is None or now - last_alert >= REALERT_SEC)
    )
    if should_alert:
        if _send_down_email(down_for):
            last_alert = now
            LOG.warning("live gateway down %s; sent alert email",
                        _fmt_duration(down_for))
        else:
            LOG.error("live gateway down %s but alert email FAILED",
                      _fmt_duration(down_for))
    _save_state({"status": "down", "first_down": first_down, "last_alert": last_alert})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
