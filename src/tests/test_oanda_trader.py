"""Tests for bh_ftmo.trading.oanda_trader order placement handling."""
# pylint: disable=missing-function-docstring,protected-access,too-few-public-methods
# pylint: disable=too-many-arguments,too-many-positional-arguments

from __future__ import annotations

from typing import Any, Optional

import pytest

from bh_ftmo.trading.oanda_trader import OandaTrader, OandaTraderConfig, OandaTraderError


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        json_data: Optional[dict[str, Any]] = None,
        text: str = "",
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text or ("" if json_data is None else "{}")
        self.headers = headers or {}

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no json")
        return self._json


class _ScriptedSession:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}

    def request(
        self,
        method: str,
        url: str,
        json: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> _FakeResponse:
        self.calls.append({
            "method": method,
            "url": url,
            "json": json,
            "params": params,
            "timeout": timeout,
        })
        if not self.responses:
            raise AssertionError(f"no scripted response left for {method} {url}")
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    def close(self) -> None:
        pass


def _make_trader(payload: dict[str, Any]) -> tuple[OandaTrader, _ScriptedSession]:
    session = _ScriptedSession([_FakeResponse(201, payload)])
    trader = OandaTrader(
        OandaTraderConfig(token="fake-token", account_id="000-000-0-000"),
        rate_limit_rps=1000.0,
    )
    trader._session = session  # type: ignore[assignment]
    return trader, session


def _create_response() -> dict[str, Any]:
    return {
        "orderCreateTransaction": {
            "id": "104",
            "type": "MARKET_ORDER",
            "instrument": "EUR_USD",
            "units": "1000",
        }
    }


def _fill_response() -> dict[str, Any]:
    return {
        **_create_response(),
        "orderFillTransaction": {
            "id": "105",
            "type": "ORDER_FILL",
            "orderID": "104",
            "instrument": "EUR_USD",
            "units": "1000",
        },
    }


def _cancel_response() -> dict[str, Any]:
    return {
        **_create_response(),
        "orderCancelTransaction": {
            "id": "105",
            "type": "ORDER_CANCEL",
            "orderID": "104",
            "reason": "MARKET_HALTED",
        },
    }


def _reject_response() -> dict[str, Any]:
    return {
        "orderRejectTransaction": {
            "id": "104",
            "type": "MARKET_ORDER_REJECT",
            "instrument": "EUR_USD",
            "units": "1000",
            "rejectReason": "INSUFFICIENT_MARGIN",
        }
    }


def test_market_order_fill_returns_response():
    payload = _fill_response()
    trader, session = _make_trader(payload)

    result = trader.create_market_order_with_bracket(
        instrument="EUR_USD",
        units=1000,
        stop_loss_price=1.1000,
        take_profit_price=1.1200,
    )

    assert result == payload
    order = session.calls[0]["json"]["order"]
    assert order["type"] == "MARKET"
    assert order["timeInForce"] == "FOK"


def test_market_order_cancelled_at_create_raises():
    trader, _ = _make_trader(_cancel_response())

    with pytest.raises(OandaTraderError, match="MARKET_HALTED"):
        trader.create_market_order_with_bracket(
            instrument="EUR_USD",
            units=1000,
            stop_loss_price=1.1000,
            take_profit_price=1.1200,
        )


def test_market_order_rejected_at_create_raises():
    trader, _ = _make_trader(_reject_response())

    with pytest.raises(OandaTraderError, match="INSUFFICIENT_MARGIN"):
        trader.create_market_order_with_bracket(
            instrument="EUR_USD",
            units=1000,
            stop_loss_price=1.1000,
            take_profit_price=1.1200,
        )


def test_limit_order_fill_returns_response():
    payload = _fill_response()
    trader, session = _make_trader(payload)

    result = trader.create_limit_order_with_bracket(
        instrument="EUR_USD",
        units=1000,
        limit_price=1.1050,
        stop_loss_price=1.1000,
        take_profit_price=1.1200,
    )

    assert result == payload
    order = session.calls[0]["json"]["order"]
    assert order["type"] == "LIMIT"
    assert order["timeInForce"] == "GTC"


def test_limit_order_cancelled_at_create_raises():
    trader, _ = _make_trader(_cancel_response())

    with pytest.raises(OandaTraderError, match="MARKET_HALTED"):
        trader.create_limit_order_with_bracket(
            instrument="EUR_USD",
            units=1000,
            limit_price=1.1050,
            stop_loss_price=1.1000,
            take_profit_price=1.1200,
        )


def test_limit_order_rejected_at_create_raises():
    trader, _ = _make_trader(_reject_response())

    with pytest.raises(OandaTraderError, match="INSUFFICIENT_MARGIN"):
        trader.create_limit_order_with_bracket(
            instrument="EUR_USD",
            units=1000,
            limit_price=1.1050,
            stop_loss_price=1.1000,
            take_profit_price=1.1200,
        )
