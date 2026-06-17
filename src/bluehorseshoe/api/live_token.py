"""Phone-triggerable endpoint to roll the live IBKR 7-day session token.

Wraps ``live_gateway_lifecycle.refresh_token()`` behind a token-guarded HTTP
endpoint so the 2FA refresh can be kicked off from a phone bookmark while the
IBKR Mobile app is in hand (the 2FA push lands on the phone you're holding).

Design notes:
  * ``refresh_token()`` restarts the ``ib-gateway-live`` container and then
    blocks up to ~240s polling for the API handshake. That's far too long for
    a single HTTP round-trip, so the work runs in a background thread and the
    page auto-refreshes to surface progress.
  * GET on the page is SAFE — it only shows status and a button. Only pressing
    the button (``?go=1``) triggers the restart, so a stale bookmark, a browser
    prefetch, or an accidental tap can't bounce the live gateway.
  * Single-slot job state guarded by a lock: only one refresh can run at a time
    (it restarts a shared container).
"""
from __future__ import annotations

import hmac
import io
import logging
import threading
import time
from contextlib import redirect_stderr, redirect_stdout

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from bluehorseshoe.core.config import Settings
from bluehorseshoe.core.dependencies import get_config

logger = logging.getLogger("bluehorseshoe.api")

router = APIRouter()

# ── Single-slot job state ──────────────────────────────────────────────
_lock = threading.Lock()
_state: dict = {
    "status": "idle",        # idle | running | success | error
    "message": "No refresh has been run yet.",
    "started_at": None,      # epoch seconds
    "finished_at": None,
}


def _require_token(provided: str | None, settings: Settings) -> None:
    """Constant-time check of the shared secret. 503 if unconfigured."""
    expected = (settings.live_refresh_token or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="LIVE_REFRESH_TOKEN is not set in .env on the server.",
        )
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing token.")


def _run_refresh() -> None:
    """Run refresh_token() and record the outcome in module state.

    Imported lazily so importing this router never drags in ib_async/docker.
    """
    buf = io.StringIO()
    try:
        from bluehorseshoe.trading.live_gateway_lifecycle import (  # noqa: PLC0415
            refresh_token,
        )
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = refresh_token()
        tail = (buf.getvalue() or "").strip().splitlines()
        last = tail[-1] if tail else ""
        with _lock:
            if rc == 0:
                _state["status"] = "success"
                _state["message"] = last or "Token refreshed. 7-day window starts now."
            else:
                _state["status"] = "error"
                _state["message"] = last or f"refresh_token() exited with code {rc}."
            _state["finished_at"] = time.time()
    except Exception as exc:  # noqa: BLE001 — surface any failure to the phone
        logger.exception("Live token refresh thread crashed")
        with _lock:
            _state["status"] = "error"
            _state["message"] = f"Refresh crashed: {exc}"
            _state["finished_at"] = time.time()


def _start_refresh() -> bool:
    """Start a refresh if one isn't already running. Returns True if started."""
    with _lock:
        if _state["status"] == "running":
            return False
        _state.update(
            status="running",
            message="Restarting live gateway. Approve the 2FA push on your "
                    "phone — polling up to 240s…",
            started_at=time.time(),
            finished_at=None,
        )
    threading.Thread(target=_run_refresh, name="live-token-refresh",
                     daemon=True).start()
    return True


# ── HTML rendering ─────────────────────────────────────────────────────
_BADGE = {
    "idle": ("#7d7494", "Idle"),
    "running": ("#4a7cff", "Running…"),
    "success": ("#00c9a7", "Success"),
    "error": ("#e0556b", "Error"),
}


def _render_page(token: str) -> str:
    with _lock:
        status = _state["status"]
        message = _state["message"]
        started = _state["started_at"]
        finished = _state["finished_at"]

    color, label = _BADGE.get(status, _BADGE["idle"])
    running = status == "running"
    # Auto-refresh only while running, so the phone tracks progress hands-free.
    # CRITICAL: refresh to the status URL *without* go=1. Refreshing the current
    # URL (which carries go=1) would re-fire a fresh refresh the instant the job
    # ends, restarting the live gateway in a 2FA-push loop. The query-only URL
    # replaces ?...&go=1 with just ?token=… against the same path (prefix-agnostic).
    meta_refresh = (
        f'<meta http-equiv="refresh" content="5; url=?token={token}">'
        if running else ""
    )

    elapsed = ""
    if started:
        end = finished or time.time()
        elapsed = f"<p class='muted'>Elapsed: {int(end - started)}s</p>"

    if running:
        button = ("<p class='muted'>A refresh is in progress. This page "
                  "updates every 5s.</p>")
    else:
        button = (
            f"<form method='get'>"
            f"<input type='hidden' name='token' value='{token}'>"
            f"<input type='hidden' name='go' value='1'>"
            f"<button type='submit'>Roll token now</button>"
            f"</form>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{meta_refresh}
<title>Live Token Refresh</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; background:#15121e;
          color:#ddd8e8; margin:0; padding:28px; }}
  .card {{ max-width:440px; margin:0 auto; background:rgba(255,255,255,0.04);
           border:1px solid rgba(255,255,255,0.08); border-radius:16px;
           padding:24px; }}
  h1 {{ font-size:20px; margin:0 0 16px; }}
  .badge {{ display:inline-block; padding:6px 14px; border-radius:999px;
            font-weight:600; color:#15121e; background:{color}; }}
  p {{ line-height:1.5; }}
  .muted {{ color:#7d7494; font-size:14px; }}
  .msg {{ background:rgba(0,0,0,0.25); border-radius:10px; padding:12px;
          font-size:14px; word-break:break-word; }}
  button {{ width:100%; padding:16px; font-size:17px; font-weight:600;
            color:#fff; background:#7c5cbf; border:none; border-radius:12px;
            margin-top:20px; }}
  button:active {{ background:#6a4ba8; }}
</style>
</head>
<body>
  <div class="card">
    <h1>IBKR Live Session Token</h1>
    <p><span class="badge">{label}</span></p>
    <p class="msg">{message}</p>
    {elapsed}
    {button}
  </div>
</body>
</html>"""


@router.get("/live/refresh-token", response_class=HTMLResponse)
def live_refresh_token_page(
    token: str = Query(default=""),
    go: int = Query(default=0),
    settings: Settings = Depends(get_config),
) -> HTMLResponse:
    """Phone-facing page. ``?go=1`` starts a refresh; otherwise shows status."""
    _require_token(token, settings)
    if go == 1:
        _start_refresh()
    return HTMLResponse(_render_page(token))


@router.get("/live/refresh-token/status")
def live_refresh_token_status(
    token: str = Query(default=""),
    settings: Settings = Depends(get_config),
) -> dict:
    """Machine-readable status (for scripting / polling)."""
    _require_token(token, settings)
    with _lock:
        return dict(_state)
