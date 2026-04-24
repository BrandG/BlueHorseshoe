"""Tests for bh_ftmo.data.validate — candle + stored-bar validators."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.data.validate import (
    IssueKind,
    ValidationIssue,
    summarize_issues,
    validate_candles,
    validate_stored,
)

NY = ZoneInfo("America/New_York")


def _candle(
    time_str: str,
    *,
    bid=(1.0, 1.01, 0.99, 1.005),
    ask=(1.001, 1.011, 0.991, 1.006),
    volume: int = 100,
    complete: bool = True,
    include_bid: bool = True,
    include_ask: bool = True,
) -> dict:
    c = {"time": time_str, "volume": volume, "complete": complete}
    if include_bid:
        c["bid"] = {"o": str(bid[0]), "h": str(bid[1]), "l": str(bid[2]), "c": str(bid[3])}
    if include_ask:
        c["ask"] = {"o": str(ask[0]), "h": str(ask[1]), "l": str(ask[2]), "c": str(ask[3])}
    return c


def _ny(*args) -> datetime:
    return datetime(*args, tzinfo=NY).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


# ---- validate_candles: happy path ---------------------------------------


def test_validate_candles_clean_input_is_empty():
    candles = [
        _candle("2020-01-01T22:00:00Z"),
        _candle("2020-01-02T02:00:00Z"),
        _candle("2020-01-02T06:00:00Z"),
    ]
    assert validate_candles(candles, symbol="EUR_USD") == []


# ---- validate_candles: duplicates + order -----------------------------


def test_validate_candles_detects_duplicate_timestamp():
    candles = [
        _candle("2020-01-01T22:00:00Z"),
        _candle("2020-01-01T22:00:00Z"),
    ]
    issues = validate_candles(candles, symbol="EUR_USD")
    kinds = [i.kind for i in issues]
    assert IssueKind.DUPLICATE in kinds


def test_validate_candles_detects_out_of_order():
    candles = [
        _candle("2020-01-02T02:00:00Z"),
        _candle("2020-01-01T22:00:00Z"),
    ]
    issues = validate_candles(candles, symbol="EUR_USD")
    assert any(i.kind == IssueKind.OUT_OF_ORDER for i in issues)


# ---- validate_candles: OHLC + spread -----------------------------------


def test_validate_candles_flags_high_below_low():
    candles = [_candle("2020-01-01T22:00:00Z", bid=(1.0, 0.5, 0.9, 1.0))]
    issues = validate_candles(candles, symbol="EUR_USD")
    assert any(i.kind == IssueKind.INVALID_OHLC and "bid" in i.detail for i in issues)


def test_validate_candles_flags_high_below_open():
    # h < o — clearly corrupt
    candles = [_candle("2020-01-01T22:00:00Z", bid=(2.0, 1.5, 1.0, 1.8))]
    issues = validate_candles(candles, symbol="EUR_USD")
    assert any(i.kind == IssueKind.INVALID_OHLC for i in issues)


def test_validate_candles_flags_ask_below_bid():
    candles = [
        _candle(
            "2020-01-01T22:00:00Z",
            bid=(1.005, 1.01, 1.0, 1.007),
            ask=(1.000, 1.005, 0.995, 1.002),  # ask < bid everywhere
        )
    ]
    issues = validate_candles(candles, symbol="EUR_USD")
    assert any(i.kind == IssueKind.INVERTED_SPREAD for i in issues)


# ---- validate_candles: missing / non-numeric ---------------------------


def test_validate_candles_missing_ask_flagged():
    candles = [_candle("2020-01-01T22:00:00Z", include_ask=False)]
    issues = validate_candles(candles, symbol="EUR_USD")
    assert any(i.kind == IssueKind.MISSING_BID_ASK for i in issues)


def test_validate_candles_missing_time_flagged():
    candles = [{"bid": {"o": "1", "h": "1", "l": "1", "c": "1"}, "ask": {"o": "1", "h": "1", "l": "1", "c": "1"}}]
    issues = validate_candles(candles, symbol="EUR_USD")
    assert any(i.kind == IssueKind.MISSING_BID_ASK for i in issues)


def test_validate_candles_nonnumeric_price_flagged():
    candle = _candle("2020-01-01T22:00:00Z")
    candle["bid"]["o"] = "NaN"  # unparseable
    issues = validate_candles([candle], symbol="EUR_USD")
    # NaN parses as float, but the sanity check may or may not catch it.
    # Use a clearly unparseable value instead:
    candle["bid"]["o"] = "not-a-number"
    issues = validate_candles([candle], symbol="EUR_USD")
    assert any(i.kind == IssueKind.MISSING_BID_ASK for i in issues)


# ---- validate_stored ---------------------------------------------------


@pytest.fixture
def populated_store(tmp_path: Path) -> FxStore:
    store = FxStore(db_path=tmp_path / "val.duckdb")
    # Populate one full Mon-Fri week H4 starting Sun 5pm NY 2025-03-09
    candles = []
    # Use NY-local anchor times to generate expected bars: every 4h from Sun 5pm NY.
    import pandas as pd

    # Simplified: generate a handful of bars in EDT UTC grid for Sun 5pm NY start
    for bar_utc in [
        "2025-03-09T21:00:00Z",  # Sun 5pm NY EDT
        "2025-03-10T01:00:00Z",  # Sun 9pm NY
        "2025-03-10T05:00:00Z",  # Mon 1am NY
        "2025-03-10T09:00:00Z",  # Mon 5am NY
        "2025-03-10T13:00:00Z",  # Mon 9am NY
        "2025-03-10T17:00:00Z",  # Mon 1pm NY
    ]:
        candles.append(_candle(bar_utc))
    store.save_candles("EUR_USD", candles, granularity="H4")
    yield store
    store.close()


def test_validate_stored_clean_returns_empty(populated_store):
    issues = validate_stored(
        populated_store,
        symbol="EUR_USD",
        granularity="H4",
        start=datetime(2025, 3, 9, 21, 0),
        end=datetime(2025, 3, 10, 21, 0),  # Mon 5pm NY EDT = 21:00 UTC
    )
    assert issues == []


def test_validate_stored_detects_data_gap(populated_store):
    # Extend the end past the populated range — exposes missing bars
    issues = validate_stored(
        populated_store,
        symbol="EUR_USD",
        granularity="H4",
        start=datetime(2025, 3, 9, 21, 0),
        end=datetime(2025, 3, 11, 5, 0),  # extends ~8h past the last stored bar
    )
    data_gaps = [i for i in issues if i.kind == IssueKind.DATA_GAP]
    assert len(data_gaps) >= 1


def test_validate_stored_excludes_holiday_gaps_by_default(tmp_path):
    store = FxStore(db_path=tmp_path / "holiday.duckdb")
    # Store zero bars for a range covering Thanksgiving 2025 (Thu Nov 27)
    # Range: Thu 12:00 UTC → Thu 17:00 UTC (one H4 bar expected at Thu NY 9am = 14:00 UTC EST)
    issues_default = validate_stored(
        store,
        symbol="EUR_USD",
        granularity="H4",
        start=datetime(2025, 11, 27, 14, 0),
        end=datetime(2025, 11, 27, 18, 0),
    )
    assert all(i.kind != IssueKind.US_HOLIDAY_GAP for i in issues_default)

    issues_with = validate_stored(
        store,
        symbol="EUR_USD",
        granularity="H4",
        start=datetime(2025, 11, 27, 14, 0),
        end=datetime(2025, 11, 27, 18, 0),
        include_holiday_gaps=True,
    )
    assert any(i.kind == IssueKind.US_HOLIDAY_GAP for i in issues_with)
    store.close()


def test_validate_stored_does_not_emit_weekend_gaps(tmp_path):
    store = FxStore(db_path=tmp_path / "weekend.duckdb")
    # Range: Fri 5pm NY → Sun 5pm NY (entirely weekend, market closed)
    # In EDT: Fri 21:00 UTC → Sun 21:00 UTC
    issues = validate_stored(
        store,
        symbol="EUR_USD",
        granularity="H4",
        start=datetime(2025, 3, 7, 21, 0),
        end=datetime(2025, 3, 9, 21, 0),
        include_holiday_gaps=True,
    )
    assert issues == []
    store.close()


# ---- summarize_issues --------------------------------------------------


def test_summarize_issues_counts_by_kind():
    issues = [
        ValidationIssue(IssueKind.DATA_GAP, "X", None, "a"),
        ValidationIssue(IssueKind.DATA_GAP, "X", None, "b"),
        ValidationIssue(IssueKind.INVALID_OHLC, "X", None, "c"),
    ]
    counts = summarize_issues(issues)
    assert counts == {IssueKind.DATA_GAP: 2, IssueKind.INVALID_OHLC: 1}
