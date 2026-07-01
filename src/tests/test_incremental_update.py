"""Tests for bh_ftmo.data.incremental_update."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterator, Optional
from unittest.mock import MagicMock

import pytest

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.data.incremental_update import (
    PairResult,
    RunSummary,
    _format_failure_body,
    run,
    send_failure_email,
    update_one,
)
from bh_ftmo.data.oanda_client import OandaAuthError, OandaError


def _candle(time_str: str, *, complete: bool = True) -> dict:
    return {
        "time": time_str,
        "bid": {"o": "1.0", "h": "1.01", "l": "0.99", "c": "1.005"},
        "ask": {"o": "1.001", "h": "1.011", "l": "0.991", "c": "1.006"},
        "volume": 100,
        "complete": complete,
    }


class _FakeClient:
    """Scripts iter_candles_paginated responses per call + optional exception."""

    def __init__(self, pages: list[list[dict]] | None = None, exc: Exception | None = None):
        self.pages = pages or []
        self.exc = exc
        self.calls: list[dict[str, Any]] = []

    def iter_candles_paginated(
        self,
        instrument: str,
        *,
        granularity: str = "H4",
        start: str,
        end: Optional[str] = None,
        price: str = "BA",
        page_size: int = 5000,
    ) -> Iterator[list[dict]]:
        self.calls.append({"instrument": instrument, "granularity": granularity, "start": start, "end": end})
        if self.exc:
            raise self.exc
        for p in self.pages:
            yield p


@pytest.fixture
def store(tmp_path) -> FxStore:
    s = FxStore(db_path=tmp_path / "incr.duckdb")
    yield s
    s.close()


def _seed(store: FxStore, *, symbol: str, granularity: str, timestamps: list[str]) -> None:
    store.save_candles(symbol, [_candle(t) for t in timestamps], granularity=granularity)


# ---- update_one: happy paths -------------------------------------------


def test_update_one_no_bars_to_fetch(store):
    _seed(store, symbol="EUR_USD", granularity="H4", timestamps=["2025-01-01T22:00:00Z"])
    # now_utc before latest → nothing to fetch
    client = _FakeClient(pages=[])
    r = update_one(
        client, store,
        symbol="EUR_USD", granularity="H4",
        now_utc=datetime(2025, 1, 1, 22, 0),  # equal to latest
    )
    assert r.bars_saved == 0
    assert r.error is None
    # Client should NOT have been called
    assert client.calls == []


def test_update_one_fetches_new_bars(store):
    _seed(store, symbol="EUR_USD", granularity="H4", timestamps=["2025-01-01T22:00:00Z"])
    new_bars = [_candle("2025-01-02T02:00:00Z"), _candle("2025-01-02T06:00:00Z")]
    client = _FakeClient(pages=[new_bars])
    r = update_one(
        client, store,
        symbol="EUR_USD", granularity="H4",
        now_utc=datetime(2025, 1, 2, 10, 0),
    )
    assert r.error is None
    assert r.bars_saved == 2
    assert store.row_count(granularity="H4", symbol="EUR_USD") == 3
    # start param should be latest + 1s
    assert client.calls[0]["start"].startswith("2025-01-01T22:00:01")


def test_update_one_empty_store_reports_error(store):
    client = _FakeClient()
    r = update_one(client, store, symbol="NEVER_BACKFILLED", granularity="H4")
    assert r.error is not None
    assert "no bars in store" in r.error
    # No fetch attempted
    assert client.calls == []


def test_update_one_skips_incomplete_bars(store):
    _seed(store, symbol="EUR_USD", granularity="H4", timestamps=["2025-01-01T22:00:00Z"])
    # OANDA returns one complete + one incomplete bar
    new_bars = [
        _candle("2025-01-02T02:00:00Z", complete=True),
        _candle("2025-01-02T06:00:00Z", complete=False),
    ]
    client = _FakeClient(pages=[new_bars])
    r = update_one(
        client, store,
        symbol="EUR_USD", granularity="H4",
        now_utc=datetime(2025, 1, 2, 7, 0),
    )
    assert r.bars_saved == 1


# ---- update_one: error paths --------------------------------------------


def test_update_one_isolates_oanda_error(store):
    _seed(store, symbol="EUR_USD", granularity="H4", timestamps=["2025-01-01T22:00:00Z"])
    client = _FakeClient(exc=OandaError("network fault"))
    r = update_one(
        client, store,
        symbol="EUR_USD", granularity="H4",
        now_utc=datetime(2025, 1, 2, 10, 0),
    )
    assert r.bars_saved == 0
    assert r.error is not None
    assert "network fault" in r.error


def test_update_one_propagates_auth_error(store):
    _seed(store, symbol="EUR_USD", granularity="H4", timestamps=["2025-01-01T22:00:00Z"])
    client = _FakeClient(exc=OandaAuthError("bad token"))
    with pytest.raises(OandaAuthError):
        update_one(
            client, store,
            symbol="EUR_USD", granularity="H4",
            now_utc=datetime(2025, 1, 2, 10, 0),
        )


# ---- run orchestrator --------------------------------------------------


def test_run_handles_mixed_success_and_failure(store):
    _seed(store, symbol="EUR_USD", granularity="H4", timestamps=["2025-01-01T22:00:00Z"])
    _seed(store, symbol="EUR_USD", granularity="H1", timestamps=["2025-01-01T23:00:00Z"])
    # USD_JPY has no bars → should fail with "no bars in store"

    # Client returns one new bar for any call
    def make_client():
        return _FakeClient(pages=[[_candle("2025-01-02T02:00:00Z")]])

    # We need per-call control: build a client that always returns one bar
    client = make_client()

    summary, results = run(
        client, store,
        symbols=["EUR_USD", "USD_JPY"],
        granularities=["H4", "H1"],
        now_utc=datetime(2025, 1, 2, 10, 0),
    )
    assert summary.total == 4
    # USD_JPY (H4 + H1) fail; EUR_USD both succeed
    assert summary.succeeded == 2
    assert len(summary.failed_pairs) == 2
    for p in summary.failed_pairs:
        assert p.symbol == "USD_JPY"
        assert "no bars in store" in (p.error or "")


def test_run_halts_on_auth_failure(store):
    _seed(store, symbol="EUR_USD", granularity="H4", timestamps=["2025-01-01T22:00:00Z"])
    _seed(store, symbol="USD_JPY", granularity="H4", timestamps=["2025-01-01T22:00:00Z"])
    client = _FakeClient(exc=OandaAuthError("bad token"))
    summary, results = run(
        client, store,
        symbols=["EUR_USD", "USD_JPY"],
        granularities=["H4"],
        now_utc=datetime(2025, 1, 2, 10, 0),
    )
    assert summary.auth_failure is True
    # Halts immediately — USD_JPY was never processed
    assert summary.succeeded == 0
    assert len(summary.failed_pairs) >= 1


def test_run_all_success(store):
    _seed(store, symbol="EUR_USD", granularity="H4", timestamps=["2025-01-01T22:00:00Z"])
    client = _FakeClient(pages=[[_candle("2025-01-02T02:00:00Z")]])
    summary, results = run(
        client, store,
        symbols=["EUR_USD"],
        granularities=["H4"],
        now_utc=datetime(2025, 1, 2, 10, 0),
    )
    assert summary.total == 1
    assert summary.succeeded == 1
    assert summary.failed_pairs == []
    assert summary.bars_saved_total == 1


# ---- format_failure_body ----------------------------------------------


def test_format_failure_body_includes_failed_pairs():
    summary = RunSummary(
        total=3,
        succeeded=1,
        failed_pairs=[
            PairResult(symbol="X", granularity="H4", error="boom"),
            PairResult(symbol="Y", granularity="H1", error="kaboom"),
        ],
        bars_saved_total=5,
    )
    body = _format_failure_body(summary, results=[])
    assert "X H4: boom" in body
    assert "Y H1: kaboom" in body
    assert "Succeeded:  1" in body
    assert "Failed:     2" in body


def test_format_failure_body_flags_auth_failure():
    summary = RunSummary(
        total=1, succeeded=0, failed_pairs=[PairResult("X", "H4", error="auth")],
        bars_saved_total=0, auth_failure=True,
    )
    body = _format_failure_body(summary, results=[])
    assert "auth rejected" in body.lower()


# ---- send_failure_email ------------------------------------------------


def test_send_failure_email_returns_false_when_unconfigured(monkeypatch):
    import bluehorseshoe.core.email_service as es
    monkeypatch.setattr(es, "EmailService", lambda: MagicMock(**{"send.return_value": None}))
    assert send_failure_email("subj", "body") is False


def test_send_failure_email_happy_path(monkeypatch):
    import bluehorseshoe.core.email_service as es
    fake = MagicMock(**{"send.return_value": "guid-123"})
    monkeypatch.setattr(es, "EmailService", lambda: fake)

    ok = send_failure_email("my subject", "my body")
    assert ok is True
    kwargs = fake.send.call_args.kwargs
    assert "my subject" in kwargs["subject"] and kwargs["text_body"] == "my body"


def test_send_failure_email_swallows_errors(monkeypatch):
    import bluehorseshoe.core.email_service as es
    fake = MagicMock()
    fake.send.side_effect = ConnectionError("relay refused")
    monkeypatch.setattr(es, "EmailService", lambda: fake)
    assert send_failure_email("subj", "body") is False  # doesn't crash
