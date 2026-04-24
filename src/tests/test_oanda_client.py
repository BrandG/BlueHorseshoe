"""Tests for bh_ftmo.data.oanda_client — mocked unit tests + opt-in live check."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import pytest
import requests

from bh_ftmo.data.oanda_client import (
    DEFAULT_BACKOFF_BASE,
    HealthReport,
    OandaAuthError,
    OandaClient,
    OandaConfig,
    OandaError,
    OandaRateLimitError,
    OandaServerError,
    _format_health,
    _RateLimiter,
)


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
        self.text = text or ("" if json_data is None else "")
        self.headers = headers or {}

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no json")
        return self._json


class _ScriptedSession:
    """Request-by-request scripted session. Each call pops the next scripted response."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}

    def request(self, method: str, url: str, params=None, timeout=None) -> _FakeResponse:
        self.calls.append({"method": method, "url": url, "params": params, "timeout": timeout})
        if not self.responses:
            raise AssertionError(f"no scripted response left for {method} {url}")
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    def close(self) -> None:
        pass


class _FakeSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _make_config() -> OandaConfig:
    return OandaConfig(
        token="fake-token",
        account_id="000-000-0-000",
        env="practice",
        base_url="https://api-fxpractice.oanda.com/v3",
    )


def _make_client(responses: list[Any], *, max_retries: int = 3) -> tuple[OandaClient, _ScriptedSession, _FakeSleep]:
    session = _ScriptedSession(responses)
    sleep = _FakeSleep()
    client = OandaClient(
        config=_make_config(),
        session=session,  # type: ignore[arg-type]
        rate_limit_rps=1000.0,
        max_retries=max_retries,
        backoff_base=DEFAULT_BACKOFF_BASE,
        backoff_cap=4.0,
        sleep=sleep,
    )
    return client, session, sleep


# ---- OandaConfig ---------------------------------------------------------


def test_config_from_env_reads_environment(monkeypatch):
    monkeypatch.setenv("OANDA_API_TOKEN", "env-token")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "001-002-003-004")
    monkeypatch.setenv("OANDA_ENV", "practice")
    cfg = OandaConfig.from_env(env_path=Path("/nonexistent"))
    assert cfg.token == "env-token"
    assert cfg.account_id == "001-002-003-004"
    assert cfg.env == "practice"
    assert cfg.base_url == "https://api-fxpractice.oanda.com/v3"


def test_config_from_env_falls_back_to_env_file(monkeypatch, tmp_path):
    monkeypatch.delenv("OANDA_API_TOKEN", raising=False)
    monkeypatch.delenv("OANDA_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("OANDA_ENV", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OANDA_API_TOKEN=file-token\n"
        'OANDA_ACCOUNT_ID="999-888-7-666"\n'
        "OANDA_ENV=live\n",
        encoding="utf-8",
    )
    cfg = OandaConfig.from_env(env_path=env_file)
    assert cfg.token == "file-token"
    assert cfg.account_id == "999-888-7-666"
    assert cfg.env == "live"
    assert cfg.base_url == "https://api-fxtrade.oanda.com/v3"


def test_config_missing_token_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("OANDA_API_TOKEN", raising=False)
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "x")
    with pytest.raises(OandaError, match="OANDA_API_TOKEN"):
        OandaConfig.from_env(env_path=tmp_path / "does-not-exist")


def test_config_invalid_env_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("OANDA_API_TOKEN", "t")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "a")
    monkeypatch.setenv("OANDA_ENV", "staging")
    with pytest.raises(OandaError, match="OANDA_ENV"):
        OandaConfig.from_env(env_path=tmp_path / "missing")


# ---- RateLimiter ---------------------------------------------------------


def test_rate_limiter_sleeps_on_consecutive_calls():
    sleep = _FakeSleep()
    limiter = _RateLimiter(rps=2.0, sleep=sleep)
    limiter.acquire()
    limiter.acquire()
    # First call: no sleep (or ~0). Second call: should sleep ~0.5s.
    assert any(s > 0 for s in sleep.calls)


def test_rate_limiter_rejects_nonpositive_rps():
    with pytest.raises(ValueError):
        _RateLimiter(rps=0)


# ---- OandaClient happy paths ---------------------------------------------


def test_list_instruments_parses_payload():
    payload = {
        "instruments": [
            {"name": "EUR_USD", "type": "CURRENCY"},
            {"name": "USD_JPY", "type": "CURRENCY"},
        ]
    }
    client, session, _ = _make_client([_FakeResponse(200, payload)])
    result = client.list_instruments()
    assert set(result.keys()) == {"EUR_USD", "USD_JPY"}
    assert result["EUR_USD"]["type"] == "CURRENCY"
    assert session.calls[0]["url"].endswith("/accounts/000-000-0-000/instruments")


def test_get_candles_passes_expected_params():
    payload = {"candles": [{"time": "2020-01-01T00:00:00Z"}]}
    client, session, _ = _make_client([_FakeResponse(200, payload)])
    result = client.get_candles("EUR_USD", granularity="H4", count=10, price="BA")
    assert result == payload["candles"]
    call = session.calls[0]
    assert call["params"] == {"granularity": "H4", "price": "BA", "count": 10}
    assert call["url"].endswith("/instruments/EUR_USD/candles")


def test_get_candles_rejects_count_with_from_and_to():
    client, _, _ = _make_client([])
    with pytest.raises(ValueError, match="count"):
        client.get_candles(
            "EUR_USD",
            count=100,
            from_time="2020-01-01T00:00:00Z",
            to_time="2020-01-02T00:00:00Z",
        )


def test_get_account_summary_returns_payload():
    payload = {"account": {"id": "000", "balance": "50000.00", "currency": "USD"}}
    client, _, _ = _make_client([_FakeResponse(200, payload)])
    result = client.get_account_summary()
    assert result["account"]["balance"] == "50000.00"


# ---- Retry / backoff -----------------------------------------------------


def test_429_retries_then_succeeds():
    payload = {"instruments": []}
    client, session, sleep = _make_client(
        [
            _FakeResponse(429, text="rate limit"),
            _FakeResponse(429, text="rate limit"),
            _FakeResponse(200, payload),
        ],
        max_retries=3,
    )
    result = client.list_instruments()
    assert result == {}
    assert len(session.calls) == 3
    assert len(sleep.calls) >= 2


def test_429_honors_retry_after_header():
    client, session, sleep = _make_client(
        [
            _FakeResponse(429, headers={"Retry-After": "7"}),
            _FakeResponse(200, {"instruments": []}),
        ],
        max_retries=3,
    )
    client.list_instruments()
    # At least one sleep call of >= 7s (the Retry-After value)
    assert any(s >= 7 for s in sleep.calls)


def test_429_exhausts_retries():
    client, _, _ = _make_client(
        [_FakeResponse(429) for _ in range(5)],
        max_retries=2,
    )
    with pytest.raises(OandaRateLimitError):
        client.list_instruments()


def test_500_retries_then_succeeds():
    client, session, _ = _make_client(
        [
            _FakeResponse(500, text="oops"),
            _FakeResponse(200, {"instruments": []}),
        ],
        max_retries=3,
    )
    client.list_instruments()
    assert len(session.calls) == 2


def test_5xx_exhausts_retries():
    client, _, _ = _make_client(
        [_FakeResponse(503) for _ in range(5)],
        max_retries=2,
    )
    with pytest.raises(OandaServerError):
        client.list_instruments()


def test_401_raises_auth_error_without_retry():
    client, session, sleep = _make_client(
        [_FakeResponse(401, text="bad token")],
        max_retries=5,
    )
    with pytest.raises(OandaAuthError):
        client.list_instruments()
    assert len(session.calls) == 1  # no retry on auth failure
    assert sleep.calls == [] or all(s == 0 for s in sleep.calls)


def test_network_error_retries():
    client, session, _ = _make_client(
        [
            requests.ConnectionError("boom"),
            _FakeResponse(200, {"instruments": []}),
        ],
        max_retries=3,
    )
    client.list_instruments()
    assert len(session.calls) == 2


# ---- Pagination ----------------------------------------------------------


def test_iter_candles_paginated_walks_forward():
    page_a = {"candles": [{"time": "2020-01-01T00:00:00Z"}, {"time": "2020-01-02T00:00:00Z"}]}
    page_b = {"candles": [{"time": "2020-01-02T00:00:00Z"}, {"time": "2020-01-03T00:00:00Z"}]}
    page_c = {"candles": [{"time": "2020-01-03T00:00:00Z"}]}  # short page -> stop
    client, session, _ = _make_client(
        [_FakeResponse(200, page_a), _FakeResponse(200, page_b), _FakeResponse(200, page_c)],
    )
    pages = list(
        client.iter_candles_paginated(
            "EUR_USD",
            granularity="H4",
            start="2020-01-01T00:00:00Z",
            page_size=2,
        )
    )
    assert len(pages) == 3
    # Second call should use the last time of page_a as cursor
    second_params = session.calls[1]["params"]
    assert second_params["from"] == "2020-01-02T00:00:00Z"
    assert second_params["includeFirst"] == "false"


def test_iter_candles_paginated_trims_at_end():
    page = {
        "candles": [
            {"time": "2020-01-01T00:00:00Z"},
            {"time": "2020-01-02T00:00:00Z"},
            {"time": "2020-01-03T00:00:00Z"},
        ]
    }
    client, _, _ = _make_client([_FakeResponse(200, page)])
    pages = list(
        client.iter_candles_paginated(
            "EUR_USD",
            start="2020-01-01T00:00:00Z",
            end="2020-01-03T00:00:00Z",
            page_size=10,
        )
    )
    assert len(pages) == 1
    assert [c["time"] for c in pages[0]] == [
        "2020-01-01T00:00:00Z",
        "2020-01-02T00:00:00Z",
    ]


def test_iter_candles_paginated_empty_page_stops():
    client, _, _ = _make_client([_FakeResponse(200, {"candles": []})])
    pages = list(
        client.iter_candles_paginated("EUR_USD", start="2020-01-01T00:00:00Z", page_size=10)
    )
    assert pages == []


# ---- health_check --------------------------------------------------------


def test_health_check_ok():
    summary = {"account": {"id": "x", "balance": "50000.00", "currency": "USD"}}
    instruments = {"instruments": [{"name": "EUR_USD"}, {"name": "USD_JPY"}]}
    client, _, _ = _make_client([_FakeResponse(200, summary), _FakeResponse(200, instruments)])
    report = client.health_check()
    assert report.ok is True
    assert report.account_currency == "USD"
    assert report.balance == 50000.0
    assert report.instrument_count == 2
    assert report.error is None


def test_health_check_fails_on_auth_error():
    client, _, _ = _make_client([_FakeResponse(401, text="bad token")])
    report = client.health_check()
    assert report.ok is False
    assert "auth rejected" in (report.error or "")


def test_format_health_redacts_nothing_sensitive():
    report = HealthReport(
        ok=True,
        env="practice",
        account_id="000-000-0-000",
        account_currency="USD",
        balance=50000.0,
        instrument_count=40,
        elapsed_seconds=1.5,
    )
    out = _format_health(report)
    assert "fake-token" not in out
    assert "OK" in out
    assert "practice" in out


# ---- Token-free CLI guard ------------------------------------------------


def test_logger_does_not_emit_token(monkeypatch, caplog):
    """A 500 then 200 sequence must never log the bearer token."""
    import logging

    caplog.set_level(logging.DEBUG, logger="bh_ftmo.data.oanda_client")
    client, _, _ = _make_client(
        [_FakeResponse(500, text="oops"), _FakeResponse(200, {"instruments": []})],
    )
    client.list_instruments()
    joined = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "fake-token" not in joined


# ---- Opt-in live smoke test ----------------------------------------------


@pytest.mark.skipif(
    os.environ.get("OANDA_LIVE_TESTS") != "1",
    reason="live OANDA test skipped (set OANDA_LIVE_TESTS=1 to enable)",
)
def test_live_health_check():
    client = OandaClient()
    with client:
        report = client.health_check()
    assert report.ok, f"live health check failed: {report.error}"
    assert report.instrument_count is not None and report.instrument_count > 0
