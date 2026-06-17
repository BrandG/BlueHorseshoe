"""Standalone mini-service exposing ONLY the token-guarded live-token refresh
endpoint.

Why a separate app/port instead of reusing the main API on 8001:
the main ``bluehorseshoe-api`` exposes UNAUTHENTICATED endpoints
(``/pipeline/run``, ``/predict``, …) that can kick off the heavy daily
pipeline. Opening 8001 through the firewall to reach the phone button would
expose all of those to the internet. Instead, 8001 stays firewalled to
localhost, and we open only this port — which serves nothing but the
token-guarded refresh page.

Runs via its own systemd unit (``bluehorseshoe-token.service``) on port 8011.
WorkingDirectory must be the repo root so pydantic reads ``.env`` for the
``LIVE_REFRESH_TOKEN`` secret.
"""
from fastapi import FastAPI

from bluehorseshoe.api.live_token import router as live_token_router
from bluehorseshoe.core.config import get_settings
from bluehorseshoe.core.dependencies import get_config

app = FastAPI(
    title="BlueHorseshoe Live-Token Refresh",
    description="Phone-facing endpoint to roll the live IBKR 7-day session.",
    version="1.0.0",
)

# This mini-service has no DI container. The live_token router only needs
# Settings, so resolve get_config straight from the .env-backed singleton
# rather than from app.state.container (which is never created here).
app.dependency_overrides[get_config] = get_settings

app.include_router(live_token_router, prefix="/api/v1")
