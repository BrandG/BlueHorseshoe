"""OANDA v20 REST client for paper-trading order placement.

Separate from ``bh_ftmo.data.oanda_client`` so that live-data credentials and
demo-trading credentials cannot accidentally cross. This class refuses to
operate against a live ``OANDA_ENV`` — it always uses the practice base URL.

Environment:
  OANDA_DEMO_TOKEN       practice account API token (required)
  OANDA_DEMO_ACCOUNT_ID  practice account ID, e.g. 101-001-XXXXXXX-001 (required)

Methods:
  - get_account_summary() — current balance, NAV, margin
  - get_open_positions()  — positions currently open (per-instrument)
  - create_market_order_with_bracket() — open a position with stop + target
  - close_position()      — flatten one instrument's position
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

REPO_ROOT = Path(__file__).resolve().parents[3]
PRACTICE_BASE_URL = "https://api-fxpractice.oanda.com/v3"

DEFAULT_RATE_LIMIT_RPS = 10.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_CAP = 16.0
DEFAULT_TIMEOUT = 20.0
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

log = logging.getLogger("bh_ftmo.trading.oanda_trader")


class OandaTraderError(RuntimeError):
    """Base class for OandaTrader errors."""


class OandaTraderAuthError(OandaTraderError):
    """Token rejected (401/403). Does not retry."""


@dataclass(frozen=True)
class OandaTraderConfig:
    token: str
    account_id: str

    @classmethod
    def from_env(cls, env_path: Optional[Path] = None) -> "OandaTraderConfig":
        token = os.environ.get("OANDA_DEMO_TOKEN")
        account = os.environ.get("OANDA_DEMO_ACCOUNT_ID")

        if (not token or not account) and env_path is None:
            env_path = REPO_ROOT / ".env"
        if (not token or not account) and env_path is not None and env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k == "OANDA_DEMO_TOKEN" and not token:
                    token = v
                elif k == "OANDA_DEMO_ACCOUNT_ID" and not account:
                    account = v

        if not token:
            raise OandaTraderError(
                "OANDA_DEMO_TOKEN is not set. Generate a v20 API token in the "
                "OANDA practice portal and add it to .env."
            )
        if not account:
            raise OandaTraderError("OANDA_DEMO_ACCOUNT_ID is not set.")

        return cls(token=token, account_id=account)


class OandaTrader:
    """Place and manage orders on an OANDA practice (demo) account."""

    def __init__(
        self,
        config: OandaTraderConfig,
        *,
        rate_limit_rps: float = DEFAULT_RATE_LIMIT_RPS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.config = config
        self._max_retries = max_retries
        self._backoff_base = DEFAULT_BACKOFF_BASE
        self._backoff_cap = DEFAULT_BACKOFF_CAP
        self._timeout = timeout
        self._min_interval = 1.0 / max(rate_limit_rps, 0.001)
        self._last_call = 0.0
        self._session = self._build_session(config.token)

    @staticmethod
    def _build_session(token: str) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept-Datetime-Format": "RFC3339",
            "Content-Type": "application/json",
        })
        return s

    def _rate_limit(self) -> None:
        now = time.monotonic()
        wait = self._min_interval - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        url = f"{PRACTICE_BASE_URL}{path}"
        last_error: Optional[str] = None
        for attempt in range(self._max_retries + 1):
            self._rate_limit()
            try:
                resp = self._session.request(
                    method, url, json=json_body, params=params, timeout=self._timeout
                )
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning("oanda_trader %s %s attempt=%d net_err=%s", method, path, attempt + 1, type(exc).__name__)
                if attempt >= self._max_retries:
                    raise OandaTraderError(f"network error after {attempt+1} attempts: {last_error}") from exc
                time.sleep(min(self._backoff_base * (2 ** attempt), self._backoff_cap))
                continue

            status = resp.status_code
            # OANDA returns 200 for queries, 201 for accepted orders, 204 for close (no content)
            if 200 <= status < 300:
                if status == 204 or not resp.text:
                    return {}
                try:
                    return resp.json()
                except ValueError as exc:
                    raise OandaTraderError(f"non-JSON response from {path}: {exc}") from exc

            if status in (401, 403):
                raise OandaTraderAuthError(f"auth rejected ({status}) on {path}")

            if status in RETRY_STATUSES and attempt < self._max_retries:
                delay = min(self._backoff_base * (2 ** attempt), self._backoff_cap)
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = max(float(retry_after), self._backoff_base)
                    except ValueError:
                        pass
                log.warning("oanda_trader %s %s -> %d retry in %.1fs", method, path, status, delay)
                time.sleep(delay)
                continue

            body_preview = resp.text[:300] if resp.text else ""
            raise OandaTraderError(f"HTTP {status} on {path}: {body_preview}")

        raise OandaTraderError(f"exhausted retries on {path} (last_error={last_error})")

    # ---- public API -----------------------------------------------------

    def get_account_summary(self) -> dict[str, Any]:
        """Return account balance, NAV, margin, currency."""
        path = f"/accounts/{self.config.account_id}/summary"
        payload = self._request("GET", path)
        return payload.get("account", {})

    def get_open_positions(self) -> list[dict[str, Any]]:
        """Return list of currently-open positions (one per instrument that has units)."""
        path = f"/accounts/{self.config.account_id}/openPositions"
        payload = self._request("GET", path)
        return list(payload.get("positions", []))

    def get_open_trades(self) -> list[dict[str, Any]]:
        """Return list of currently-open trades (each trade is one fill, may have bracket attached)."""
        path = f"/accounts/{self.config.account_id}/openTrades"
        payload = self._request("GET", path)
        return list(payload.get("trades", []))

    def _raise_if_rejected(self, response: dict[str, Any]) -> None:
        """Surface OANDA create-time rejects that arrive in otherwise-successful responses."""
        cancel = response.get("orderCancelTransaction")
        reject = response.get("orderRejectTransaction")
        if cancel:
            reason = cancel.get("reason", "UNKNOWN")
            raise OandaTraderError(f"OANDA cancelled order at create: {reason}")
        if reject:
            reason = reject.get("rejectReason") or reject.get("reason", "UNKNOWN")
            raise OandaTraderError(f"OANDA rejected order at create: {reason}")

    def create_market_order_with_bracket(
        self,
        instrument: str,
        units: int,
        stop_loss_price: float,
        take_profit_price: float,
        *,
        price_precision: int = 5,
        client_tag: Optional[str] = None,
    ) -> dict[str, Any]:
        """Submit a MARKET order with attached stop-loss and take-profit.

        ``units`` is signed: positive = long, negative = short.
        ``price_precision`` controls the decimals in stopLossOnFill/takeProfitOnFill.
        Returns the OANDA order-creation response.
        """
        if units == 0:
            raise OandaTraderError("units must be non-zero")

        order: dict[str, Any] = {
            "type": "MARKET",
            "instrument": instrument,
            "units": str(units),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
            "stopLossOnFill": {
                "price": f"{stop_loss_price:.{price_precision}f}",
                "timeInForce": "GTC",
            },
            "takeProfitOnFill": {
                "price": f"{take_profit_price:.{price_precision}f}",
                "timeInForce": "GTC",
            },
        }
        if client_tag is not None:
            order["clientExtensions"] = {"tag": str(client_tag)[:128]}

        path = f"/accounts/{self.config.account_id}/orders"
        response = self._request("POST", path, json_body={"order": order})
        self._raise_if_rejected(response)
        return response

    def create_limit_order_with_bracket(
        self,
        instrument: str,
        units: int,
        limit_price: float,
        stop_loss_price: float,
        take_profit_price: float,
        *,
        gtd_time: Optional[datetime] = None,
        price_precision: int = 5,
        client_tag: Optional[str] = None,
    ) -> dict[str, Any]:
        """Submit a LIMIT order with attached stop-loss and take-profit.

        ``units`` is signed: positive = long, negative = short.
        ``limit_price`` is the limit fill price.
        ``gtd_time`` (if given) sets timeInForce=GTD and the order auto-cancels
        at that absolute UTC time. If omitted, the order is GTC. For v2-cell
        deployments, callers typically pass the next H4 bar's close so the
        order matches the simulator's 1-bar fill window.
        Returns the OANDA order-creation response.
        """
        if units == 0:
            raise OandaTraderError("units must be non-zero")

        order: dict[str, Any] = {
            "type": "LIMIT",
            "instrument": instrument,
            "units": str(units),
            "price": f"{limit_price:.{price_precision}f}",
            "positionFill": "DEFAULT",
            "stopLossOnFill": {
                "price": f"{stop_loss_price:.{price_precision}f}",
                "timeInForce": "GTC",
            },
            "takeProfitOnFill": {
                "price": f"{take_profit_price:.{price_precision}f}",
                "timeInForce": "GTC",
            },
        }
        if gtd_time is not None:
            if gtd_time.tzinfo is None:
                gtd_time = gtd_time.replace(tzinfo=timezone.utc)
            order["timeInForce"] = "GTD"
            order["gtdTime"] = (gtd_time.astimezone(timezone.utc)
                                .strftime("%Y-%m-%dT%H:%M:%S.000000000Z"))
        else:
            order["timeInForce"] = "GTC"
        if client_tag is not None:
            order["clientExtensions"] = {"tag": str(client_tag)[:128]}

        path = f"/accounts/{self.config.account_id}/orders"
        response = self._request("POST", path, json_body={"order": order})
        self._raise_if_rejected(response)
        return response

    def close_position(self, instrument: str, *, side: str = "all") -> dict[str, Any]:
        """Flatten an open position. side ∈ {"all", "long", "short"}."""
        path = f"/accounts/{self.config.account_id}/positions/{instrument}/close"
        if side == "all":
            body = {"longUnits": "ALL", "shortUnits": "ALL"}
        elif side == "long":
            body = {"longUnits": "ALL"}
        elif side == "short":
            body = {"shortUnits": "ALL"}
        else:
            raise OandaTraderError(f"side must be 'all'|'long'|'short', got {side!r}")
        return self._request("PUT", path, json_body=body)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "OandaTrader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def health_check_cli() -> int:
    """Standalone CLI: verify OANDA_DEMO_TOKEN works and print account summary."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        config = OandaTraderConfig.from_env()
    except OandaTraderError as exc:
        print(f"ERROR: {exc}")
        return 2
    with OandaTrader(config) as trader:
        try:
            summary = trader.get_account_summary()
        except OandaTraderError as exc:
            print(f"ERROR: {exc}")
            return 1
        print(f"Account ID:       {summary.get('id')}")
        print(f"Currency:         {summary.get('currency')}")
        print(f"Balance:          {summary.get('balance')}")
        print(f"NAV:              {summary.get('NAV')}")
        print(f"Open trade count: {summary.get('openTradeCount')}")
        print(f"Margin used:      {summary.get('marginUsed')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(health_check_cli())
