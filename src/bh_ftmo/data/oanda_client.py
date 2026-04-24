"""OANDA v20 REST client — Phase 1 data foundation.

Wraps the subset of OANDA's v20 API that BH FTMO needs: instrument listing,
candle fetching (single + paginated), and a token health check. Handles rate
limiting, 429/5xx retry with exponential backoff, and safe logging (token is
never logged).

Used by:
  - ``fx_store.py`` / ``backfill.py``: historical + incremental data ingestion
  - ``oanda_probe.py``: periodic sanity check (via ``list_instruments``)
  - ``python -m bh_ftmo.data.oanda_client``: standalone token health check CLI

Environment:
  OANDA_API_TOKEN   personal access token (required)
  OANDA_ACCOUNT_ID  account ID string (required)
  OANDA_ENV         "live" (default) or "practice"

Per plan decisions #1, #13, C-2: data-only usage, no order placement via OANDA;
token and account ID must never appear in logs.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import requests

REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_RATE_LIMIT_RPS = 20.0
DEFAULT_MAX_RETRIES = 5
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_CAP = 32.0
DEFAULT_TIMEOUT = 30.0

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

log = logging.getLogger("bh_ftmo.data.oanda_client")


class OandaError(RuntimeError):
    """Base for OANDA client errors that survive the retry loop."""


class OandaAuthError(OandaError):
    """Token rejected (401/403) — does not retry."""


class OandaRateLimitError(OandaError):
    """Exhausted retries on 429 responses."""


class OandaServerError(OandaError):
    """Exhausted retries on 5xx responses."""


@dataclass(frozen=True)
class OandaConfig:
    token: str
    account_id: str
    env: str
    base_url: str

    @classmethod
    def from_env(cls, env_path: Optional[Path] = None) -> "OandaConfig":
        token = os.environ.get("OANDA_API_TOKEN")
        account = os.environ.get("OANDA_ACCOUNT_ID")
        env = os.environ.get("OANDA_ENV", "live").lower()

        if (not token or not account) and env_path is None:
            env_path = REPO_ROOT / ".env"
        if (not token or not account) and env_path is not None and env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k == "OANDA_API_TOKEN" and not token:
                    token = v
                elif k == "OANDA_ACCOUNT_ID" and not account:
                    account = v
                elif k == "OANDA_ENV" and "OANDA_ENV" not in os.environ:
                    env = v.lower()

        if not token:
            raise OandaError("OANDA_API_TOKEN is not set (export it or add to .env)")
        if not account:
            raise OandaError("OANDA_ACCOUNT_ID is not set (export it or add to .env)")

        if env == "live":
            base = "https://api-fxtrade.oanda.com/v3"
        elif env == "practice":
            base = "https://api-fxpractice.oanda.com/v3"
        else:
            raise OandaError(f"OANDA_ENV must be 'live' or 'practice', got {env!r}")

        return cls(token=token, account_id=account, env=env, base_url=base)


@dataclass
class HealthReport:
    ok: bool
    env: str
    account_id: str
    account_currency: Optional[str] = None
    balance: Optional[float] = None
    instrument_count: Optional[int] = None
    error: Optional[str] = None
    elapsed_seconds: float = 0.0


class _RateLimiter:
    """Minimum-interval gate. Caller calls ``acquire()`` before each request."""

    def __init__(self, rps: float, sleep: Callable[[float], None] = time.sleep) -> None:
        if rps <= 0:
            raise ValueError(f"rps must be positive, got {rps}")
        self._interval = 1.0 / rps
        self._sleep = sleep
        self._last_call = 0.0

    def acquire(self) -> None:
        now = time.monotonic()
        wait = self._interval - (now - self._last_call)
        if wait > 0:
            self._sleep(wait)
        self._last_call = time.monotonic()


class OandaClient:
    """OANDA v20 client with rate limiting and retry-with-backoff.

    All HTTP errors that survive the retry loop raise a subclass of ``OandaError``.
    Token and account ID are never logged; only method + path + status + timing.
    """

    def __init__(
        self,
        config: Optional[OandaConfig] = None,
        session: Optional[requests.Session] = None,
        rate_limit_rps: float = DEFAULT_RATE_LIMIT_RPS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        backoff_cap: float = DEFAULT_BACKOFF_CAP,
        timeout: float = DEFAULT_TIMEOUT,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config or OandaConfig.from_env()
        self._session = session or self._build_session(self.config.token)
        self._rate_limiter = _RateLimiter(rate_limit_rps, sleep=sleep)
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._timeout = timeout
        self._sleep = sleep

    @staticmethod
    def _build_session(token: str) -> requests.Session:
        s = requests.Session()
        s.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept-Datetime-Format": "RFC3339",
            }
        )
        return s

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        url = f"{self.config.base_url}{path}"
        last_error: Optional[str] = None
        for attempt in range(self._max_retries + 1):
            self._rate_limiter.acquire()
            t0 = time.monotonic()
            try:
                resp = self._session.request(
                    method, url, params=params, timeout=self._timeout
                )
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "oanda %s %s attempt=%d network_error=%s",
                    method,
                    path,
                    attempt + 1,
                    type(exc).__name__,
                )
                if attempt >= self._max_retries:
                    raise OandaError(f"network error after {attempt + 1} attempts: {last_error}") from exc
                self._sleep(self._backoff_seconds(attempt))
                continue

            elapsed = time.monotonic() - t0
            status = resp.status_code

            if 200 <= status < 300:
                log.debug("oanda %s %s -> %d (%.2fs)", method, path, status, elapsed)
                try:
                    return resp.json()
                except ValueError as exc:
                    raise OandaError(f"non-JSON response from {path}: {exc}") from exc

            if status in (401, 403):
                raise OandaAuthError(f"auth rejected ({status}) on {path}")

            if status in RETRY_STATUSES and attempt < self._max_retries:
                delay = self._retry_delay(resp, attempt)
                log.warning(
                    "oanda %s %s -> %d attempt=%d retrying in %.1fs",
                    method,
                    path,
                    status,
                    attempt + 1,
                    delay,
                )
                self._sleep(delay)
                continue

            body_preview = resp.text[:200] if resp.text else ""
            if status == 429:
                raise OandaRateLimitError(f"rate-limited after {attempt + 1} attempts: {body_preview}")
            if status >= 500:
                raise OandaServerError(f"server error {status} after {attempt + 1} attempts: {body_preview}")
            raise OandaError(f"HTTP {status} on {path}: {body_preview}")

        raise OandaError(f"exhausted retries on {path} (last_error={last_error})")

    def _backoff_seconds(self, attempt: int) -> float:
        return min(self._backoff_base * (2 ** attempt), self._backoff_cap)

    def _retry_delay(self, resp: requests.Response, attempt: int) -> float:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), self._backoff_base)
            except ValueError:
                pass
        return self._backoff_seconds(attempt)

    # ---- public API -----------------------------------------------------

    def health_check(self) -> HealthReport:
        t0 = time.monotonic()
        try:
            summary = self.get_account_summary()
            instruments = self.list_instruments()
        except OandaError as exc:
            return HealthReport(
                ok=False,
                env=self.config.env,
                account_id=self.config.account_id,
                error=str(exc),
                elapsed_seconds=time.monotonic() - t0,
            )

        account = summary.get("account", {})
        balance_raw = account.get("balance")
        try:
            balance = float(balance_raw) if balance_raw is not None else None
        except (TypeError, ValueError):
            balance = None

        return HealthReport(
            ok=True,
            env=self.config.env,
            account_id=self.config.account_id,
            account_currency=account.get("currency"),
            balance=balance,
            instrument_count=len(instruments),
            elapsed_seconds=time.monotonic() - t0,
        )

    def get_account_summary(self) -> dict[str, Any]:
        return self._request("GET", f"/accounts/{self.config.account_id}/summary")

    def list_instruments(self) -> dict[str, dict[str, Any]]:
        payload = self._request("GET", f"/accounts/{self.config.account_id}/instruments")
        return {item["name"]: item for item in payload.get("instruments", [])}

    def get_candles(
        self,
        instrument: str,
        *,
        granularity: str = "H4",
        count: Optional[int] = None,
        from_time: Optional[str] = None,
        to_time: Optional[str] = None,
        price: str = "BA",
        include_first: Optional[bool] = None,
    ) -> list[dict[str, Any]]:
        """Fetch candles. Returns the raw candle list (``[]`` if none).

        ``from_time`` and ``to_time`` are RFC3339 strings. Per OANDA v20 rules,
        ``count`` cannot be combined with both ``from_time`` and ``to_time``.
        """
        if count is not None and from_time is not None and to_time is not None:
            raise ValueError("cannot combine count with both from_time and to_time")
        params: dict[str, Any] = {"granularity": granularity, "price": price}
        if count is not None:
            params["count"] = count
        if from_time is not None:
            params["from"] = from_time
        if to_time is not None:
            params["to"] = to_time
        if include_first is not None:
            params["includeFirst"] = "true" if include_first else "false"
        payload = self._request("GET", f"/instruments/{instrument}/candles", params=params)
        return payload.get("candles", [])

    def iter_candles_paginated(
        self,
        instrument: str,
        *,
        granularity: str = "H4",
        start: str,
        end: Optional[str] = None,
        price: str = "BA",
        page_size: int = 5000,
    ) -> Iterator[list[dict[str, Any]]]:
        """Yield pages of candles between ``start`` (inclusive) and ``end`` (exclusive).

        Uses OANDA's ``count`` + ``from`` walk forward, keyed on the last
        candle's timestamp. Stops when a page returns fewer than ``page_size``
        candles, or the last candle's time passes ``end``.

        ``end`` is optional; if omitted, walks until OANDA returns fewer than
        ``page_size`` candles (i.e., caught up to the present).
        """
        cursor = start
        seen_last: Optional[str] = None
        while True:
            page = self.get_candles(
                instrument,
                granularity=granularity,
                count=page_size,
                from_time=cursor,
                price=price,
                include_first=(seen_last is None),
            )
            if not page:
                return

            if end is not None:
                trimmed = [c for c in page if c.get("time", "") < end]
                if trimmed:
                    yield trimmed
                if len(trimmed) < len(page):
                    return
            else:
                yield page

            last_time = page[-1].get("time")
            if not last_time or last_time == seen_last:
                return
            seen_last = last_time
            cursor = last_time

            if len(page) < page_size:
                return

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "OandaClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _format_health(report: HealthReport) -> str:
    lines = [
        "== OANDA token health check ==",
        f"  env:              {report.env}",
        f"  account:          {report.account_id}",
        f"  result:           {'OK' if report.ok else 'FAIL'}",
        f"  elapsed:          {report.elapsed_seconds:.2f}s",
    ]
    if report.ok:
        lines.append(f"  account currency: {report.account_currency}")
        lines.append(f"  balance:          {report.balance}")
        lines.append(f"  instrument count: {report.instrument_count}")
    else:
        lines.append(f"  error:            {report.error}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        client = OandaClient()
    except OandaError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 2
    with client:
        report = client.health_check()
    print(_format_health(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
