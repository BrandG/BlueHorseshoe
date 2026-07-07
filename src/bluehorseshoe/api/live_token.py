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
    "generation": 0,         # bumped on every start; stale workers self-discard
}
# Handle to the in-flight worker + its cancel flag, so an "Abandon & restart"
# can signal the current poll to bail and wait for it to release probe
# clientId 99 before the replacement starts probing. Kept in a mutable
# container (not _state) so the JSON status endpoint stays serializable and
# so _start_refresh can rebind them without a module-level `global`.
_current: dict = {"cancel": None, "worker": None}
# How long the replacement waits for the abandoned worker to notice its
# cancel flag and exit its poll. Comfortably above one poll interval + the
# 4s handshake timeout; if it still overruns we proceed anyway (any brief
# clientId-99 overlap self-heals once the old worker finally exits).
_ABANDON_JOIN_TIMEOUT_S = 12.0


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


def _run_refresh(generation: int, cancel: threading.Event,
                 prev_worker: threading.Thread | None) -> None:
    """Run refresh_token() and record the outcome in module state.

    Imported lazily so importing this router never drags in ib_async/docker.

    When this job supersedes a still-running one (Abandon & restart), first
    wait for that worker to notice its cancel flag and exit — otherwise both
    would probe the gateway with clientId 99 and mutually fail. We only write
    our result if ``generation`` is still current; a worker that was itself
    abandoned finds the generation bumped and discards its (stale) result.
    """
    if prev_worker is not None and prev_worker.is_alive():
        prev_worker.join(timeout=_ABANDON_JOIN_TIMEOUT_S)
    buf = io.StringIO()
    try:
        from bluehorseshoe.trading.live_gateway_lifecycle import (  # noqa: PLC0415
            refresh_token,
        )
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = refresh_token(cancel=cancel)
        tail = (buf.getvalue() or "").strip().splitlines()
        last = tail[-1] if tail else ""
        with _lock:
            if generation != _state["generation"]:
                return  # a newer refresh took over; our result is stale
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
            if generation != _state["generation"]:
                return
            _state["status"] = "error"
            _state["message"] = f"Refresh crashed: {exc}"
            _state["finished_at"] = time.time()


def _start_refresh(force: bool = False) -> bool:
    """Start a refresh. Returns True if a new one was started.

    Normally a no-op while one is already running (returns False). With
    ``force`` (the Abandon & restart button), signal the in-flight worker to
    cancel, bump the generation so its result is ignored, and hand the new
    worker a reference to the old one so it can wait for clientId 99 to free
    up before probing.
    """
    with _lock:
        if _state["status"] == "running" and not force:
            return False
        prev_worker = _current["worker"]
        if _current["cancel"] is not None:
            _current["cancel"].set()
        _state["generation"] += 1
        generation = _state["generation"]
        cancel = threading.Event()
        _current["cancel"] = cancel
        _state.update(
            status="running",
            message="Restarting live gateway. Approve the 2FA push on your "
                    "phone — polling up to 240s…",
            started_at=time.time(),
            finished_at=None,
        )
        worker = threading.Thread(
            target=_run_refresh, args=(generation, cancel, prev_worker),
            name="live-token-refresh", daemon=True)
        _current["worker"] = worker
    worker.start()
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
        # Still offer a way out: abandon the (possibly doomed — swallowed 2FA
        # push) in-flight poll and fire a fresh restart+push immediately,
        # instead of waiting out the ~240s timeout. force=1 makes _start_refresh
        # supersede the running job. A manual tap is required (go=1), so the 5s
        # auto-refresh — which drops go — can't re-fire it on its own.
        button = (
            "<p class='muted'>A refresh is in progress. This page "
            "updates every 5s.</p>"
            f"<form method='get'>"
            f"<input type='hidden' name='token' value='{token}'>"
            f"<input type='hidden' name='go' value='1'>"
            f"<input type='hidden' name='force' value='1'>"
            f"<button type='submit' class='secondary'>"
            f"Abandon &amp; restart now</button>"
            f"</form>"
        )
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
  button.secondary {{ background:#b5713a; margin-top:12px; }}
  button.secondary:active {{ background:#985d2e; }}
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
    force: int = Query(default=0),
    settings: Settings = Depends(get_config),
) -> HTMLResponse:
    """Phone-facing page. ``?go=1`` starts a refresh; otherwise shows status.

    ``?go=1&force=1`` abandons an in-flight refresh and starts a fresh one —
    the escape hatch for a swallowed 2FA push.
    """
    _require_token(token, settings)
    if go == 1:
        _start_refresh(force=force == 1)
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
