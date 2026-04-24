"""Tests for bh_ftmo.data.backfill — CheckpointStore + per-symbol backfill."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

import pytest

from bh_ftmo.data.backfill import (
    BackfillResult,
    CheckpointStore,
    backfill_all,
    backfill_symbol,
    _fmt_rfc3339,
    _year_bounds_utc,
)
from bh_ftmo.data.fx_store import FxStore


def _candle(time_str: str, *, complete: bool = True) -> dict:
    return {
        "time": time_str,
        "bid": {"o": "1.0", "h": "1.01", "l": "0.99", "c": "1.005"},
        "ask": {"o": "1.001", "h": "1.011", "l": "0.991", "c": "1.006"},
        "volume": 100,
        "complete": complete,
    }


class _FakeClient:
    """Captures calls to iter_candles_paginated and returns scripted pages."""

    def __init__(self, responses_by_year: dict[int, list[list[dict]]]) -> None:
        self.responses = responses_by_year
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
        self.calls.append({
            "instrument": instrument,
            "granularity": granularity,
            "start": start,
            "end": end,
        })
        # Determine year from start
        year = int(start[:4])
        for page in self.responses.get(year, []):
            yield page


@pytest.fixture
def store(tmp_path) -> FxStore:
    s = FxStore(db_path=tmp_path / "bf.duckdb")
    yield s
    s.close()


@pytest.fixture
def checkpoint(tmp_path) -> CheckpointStore:
    return CheckpointStore(tmp_path / "cp.json")


# ---- CheckpointStore ---------------------------------------------------


def test_checkpoint_empty_load(tmp_path):
    cp = CheckpointStore(tmp_path / "new.json")
    assert cp.get_completed_years("EUR_USD", "H4") == set()
    assert cp.get_latest_saved("EUR_USD", "H4") is None


def test_checkpoint_add_and_persist(tmp_path):
    path = tmp_path / "cp.json"
    cp = CheckpointStore(path)
    cp.add_completed_year("EUR_USD", "H4", 2020)
    cp.add_completed_year("EUR_USD", "H4", 2021)
    cp.update_latest_saved("EUR_USD", "H4", datetime(2022, 3, 5, 17, 0))
    cp.save()

    # Re-load from disk
    cp2 = CheckpointStore(path)
    assert cp2.get_completed_years("EUR_USD", "H4") == {2020, 2021}
    assert cp2.get_latest_saved("EUR_USD", "H4") == datetime(2022, 3, 5, 17, 0)


def test_checkpoint_ignores_corrupt_file(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("not json at all", encoding="utf-8")
    cp = CheckpointStore(path)
    assert cp.get_completed_years("X", "H4") == set()


def test_checkpoint_atomic_write_via_tmp_file(tmp_path):
    path = tmp_path / "atomic.json"
    cp = CheckpointStore(path)
    cp.add_completed_year("Y", "H1", 2023)
    cp.save()
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["Y"]["H1"]["completed_years"] == [2023]


# ---- _year_bounds_utc / _fmt_rfc3339 ----------------------------------


def test_year_bounds_utc():
    s, e = _year_bounds_utc(2023)
    assert s == datetime(2023, 1, 1)
    assert e == datetime(2024, 1, 1)


def test_fmt_rfc3339_naive():
    assert _fmt_rfc3339(datetime(2023, 1, 1, 12, 0)) == "2023-01-01T12:00:00Z"


# ---- backfill_symbol: single-year completion --------------------------


def test_backfill_single_closed_year_marks_complete(store, checkpoint):
    client = _FakeClient(
        {2023: [[_candle("2023-01-01T22:00:00Z"), _candle("2023-01-02T02:00:00Z")]]}
    )
    result = backfill_symbol(
        client,
        store,
        symbol="EUR_USD",
        granularity="H4",
        start=datetime(2023, 1, 1),
        end=datetime(2024, 1, 1),
        checkpoint=checkpoint,
    )
    assert result.bars_saved == 2
    assert result.years_processed == [2023]
    assert 2023 in checkpoint.get_completed_years("EUR_USD", "H4")
    assert store.row_count(granularity="H4", symbol="EUR_USD") == 2


def test_backfill_partial_year_does_not_mark_complete(store, checkpoint):
    """End inside a year → that year must NOT be added to completed_years."""
    client = _FakeClient({2023: [[_candle("2023-06-15T22:00:00Z")]]})
    result = backfill_symbol(
        client,
        store,
        symbol="EUR_USD",
        granularity="H4",
        start=datetime(2023, 1, 1),
        end=datetime(2023, 7, 1),  # partial year
        checkpoint=checkpoint,
    )
    assert result.bars_saved == 1
    assert 2023 not in checkpoint.get_completed_years("EUR_USD", "H4")
    assert result.years_processed == []


def test_backfill_multi_year(store, checkpoint):
    client = _FakeClient({
        2022: [[_candle("2022-06-01T22:00:00Z")]],
        2023: [[_candle("2023-06-01T22:00:00Z")]],
        2024: [[_candle("2024-06-01T22:00:00Z")]],
    })
    result = backfill_symbol(
        client,
        store,
        symbol="EUR_USD",
        granularity="H4",
        start=datetime(2022, 1, 1),
        end=datetime(2025, 1, 1),
        checkpoint=checkpoint,
    )
    assert result.bars_saved == 3
    assert set(result.years_processed) == {2022, 2023, 2024}
    assert checkpoint.get_completed_years("EUR_USD", "H4") == {2022, 2023, 2024}


# ---- backfill_symbol: resume semantics --------------------------------


def test_backfill_skips_checkpointed_years(store, checkpoint):
    checkpoint.add_completed_year("EUR_USD", "H4", 2022)
    client = _FakeClient({
        2023: [[_candle("2023-06-01T22:00:00Z")]],
    })
    result = backfill_symbol(
        client,
        store,
        symbol="EUR_USD",
        granularity="H4",
        start=datetime(2022, 1, 1),
        end=datetime(2024, 1, 1),
        checkpoint=checkpoint,
    )
    # 2022 skipped — client not called for it (no entry in responses)
    assert result.years_skipped == [2022]
    assert result.years_processed == [2023]
    # No 2022 calls made
    assert all(c["start"][:4] != "2022" for c in client.calls)


def test_backfill_idempotent_rerun_does_nothing(store, checkpoint):
    client1 = _FakeClient({2023: [[_candle("2023-06-01T22:00:00Z")]]})
    backfill_symbol(
        client1, store,
        symbol="EUR_USD", granularity="H4",
        start=datetime(2023, 1, 1), end=datetime(2024, 1, 1),
        checkpoint=checkpoint,
    )
    initial_rows = store.row_count(granularity="H4", symbol="EUR_USD")

    # Second run: client MUST NOT be called (year is complete in checkpoint)
    client2 = _FakeClient({})  # empty — would raise if accessed
    result = backfill_symbol(
        client2, store,
        symbol="EUR_USD", granularity="H4",
        start=datetime(2023, 1, 1), end=datetime(2024, 1, 1),
        checkpoint=checkpoint,
    )
    assert client2.calls == []
    assert result.bars_saved == 0
    assert result.years_skipped == [2023]
    assert store.row_count(granularity="H4", symbol="EUR_USD") == initial_rows


# ---- backfill_symbol: no checkpoint -----------------------------------


def test_backfill_without_checkpoint_still_saves(store):
    client = _FakeClient({2023: [[_candle("2023-06-01T22:00:00Z")]]})
    result = backfill_symbol(
        client, store,
        symbol="EUR_USD", granularity="H4",
        start=datetime(2023, 1, 1), end=datetime(2024, 1, 1),
        checkpoint=None,
    )
    assert result.bars_saved == 1


# ---- validation path ---------------------------------------------------


def test_backfill_collects_validation_issues(store, checkpoint):
    """A duplicate timestamp in a page → captured in result.issues."""
    client = _FakeClient({
        2023: [[
            _candle("2023-01-01T22:00:00Z"),
            _candle("2023-01-01T22:00:00Z"),  # duplicate
        ]],
    })
    result = backfill_symbol(
        client, store,
        symbol="EUR_USD", granularity="H4",
        start=datetime(2023, 1, 1), end=datetime(2024, 1, 1),
        checkpoint=checkpoint,
        validate=True,
    )
    assert len(result.issues) >= 1
    assert any(i.kind.value == "duplicate" for i in result.issues)


def test_backfill_validate_false_skips_checks(store, checkpoint):
    client = _FakeClient({
        2023: [[_candle("2023-01-01T22:00:00Z"), _candle("2023-01-01T22:00:00Z")]],
    })
    result = backfill_symbol(
        client, store,
        symbol="EUR_USD", granularity="H4",
        start=datetime(2023, 1, 1), end=datetime(2024, 1, 1),
        checkpoint=checkpoint,
        validate=False,
    )
    assert result.issues == []


# ---- backfill_all orchestrator ----------------------------------------


def test_backfill_all_covers_symbol_granularity_matrix(store, checkpoint):
    responses = {2023: [[_candle("2023-06-01T22:00:00Z")]]}
    client = _FakeClient(responses)
    # All four (symbol, granularity) combos use the same responses
    progress_lines: list[str] = []
    results = backfill_all(
        client, store,
        symbols=["EUR_USD", "USD_JPY"],
        granularities=["H4", "H1"],
        start=datetime(2023, 1, 1),
        end=datetime(2024, 1, 1),
        checkpoint=checkpoint,
        progress=progress_lines.append,
    )
    assert len(results) == 4  # 2 symbols × 2 granularities
    assert sum(r.bars_saved for r in results) == 4
    assert any("EUR_USD H4" in line for line in progress_lines)
    assert any("USD_JPY H1" in line for line in progress_lines)


# ---- OANDA error propagation ------------------------------------------


def test_backfill_captures_oanda_error_in_result(store, checkpoint):
    from bh_ftmo.data.oanda_client import OandaError

    class _BoomClient:
        def iter_candles_paginated(self, instrument, **kwargs):
            raise OandaError("simulated network fault")
            yield  # unreachable — makes this a generator for type purposes

    result = backfill_symbol(
        _BoomClient(), store,
        symbol="EUR_USD", granularity="H4",
        start=datetime(2023, 1, 1), end=datetime(2024, 1, 1),
        checkpoint=checkpoint,
    )
    assert result.error is not None
    assert "simulated network fault" in result.error
    assert 2023 not in checkpoint.get_completed_years("EUR_USD", "H4")
