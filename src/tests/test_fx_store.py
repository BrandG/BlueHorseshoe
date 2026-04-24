"""Tests for bh_ftmo.data.fx_store — DuckDB wrapper for 4h + 1h forex bars."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from bh_ftmo.data.fx_store import (
    Coverage,
    FxStore,
    _parse_rfc3339,
    candle_to_row,
)


def _oanda_candle(
    time_str: str,
    *,
    bid=(1.0, 1.01, 0.99, 1.005),
    ask=(1.001, 1.011, 0.991, 1.006),
    volume: int = 100,
    complete: bool = True,
) -> dict:
    o, h, l, c = bid
    ao, ah, al, ac = ask
    return {
        "time": time_str,
        "bid": {"o": str(o), "h": str(h), "l": str(l), "c": str(c)},
        "ask": {"o": str(ao), "h": str(ah), "l": str(al), "c": str(ac)},
        "volume": volume,
        "complete": complete,
    }


@pytest.fixture
def store(tmp_path: Path) -> FxStore:
    s = FxStore(db_path=tmp_path / "test.duckdb")
    yield s
    s.close()


# ---- timestamp parsing -------------------------------------------------


def test_parse_rfc3339_with_z():
    dt = _parse_rfc3339("2020-01-01T22:00:00Z")
    assert dt == datetime(2020, 1, 1, 22, 0, 0)
    assert dt.tzinfo is None


def test_parse_rfc3339_with_nanoseconds():
    dt = _parse_rfc3339("2020-01-01T22:00:00.000000000Z")
    assert dt == datetime(2020, 1, 1, 22, 0, 0)


def test_parse_rfc3339_with_microseconds():
    dt = _parse_rfc3339("2020-01-01T22:00:00.123456Z")
    assert dt == datetime(2020, 1, 1, 22, 0, 0, 123456)


def test_parse_rfc3339_aware_input_returns_utc_naive():
    dt = _parse_rfc3339("2020-01-01T18:00:00-04:00")
    assert dt == datetime(2020, 1, 1, 22, 0, 0)
    assert dt.tzinfo is None


# ---- candle_to_row -----------------------------------------------------


def test_candle_to_row_happy_path():
    candle = _oanda_candle("2020-01-01T22:00:00Z", volume=500)
    row = candle_to_row(candle, symbol="EUR_USD")
    assert row["symbol"] == "EUR_USD"
    assert row["timestamp"] == datetime(2020, 1, 1, 22, 0, 0)
    assert row["open_bid"] == 1.0
    assert row["close_ask"] == 1.006
    assert row["tick_volume"] == 500
    assert row["is_complete"] is True
    assert row["provider"] == "oanda"


def test_candle_to_row_missing_bid_raises():
    candle = {"time": "2020-01-01T22:00:00Z", "ask": {"o": "1", "h": "1", "l": "1", "c": "1"}}
    with pytest.raises(ValueError, match="bid/ask"):
        candle_to_row(candle, symbol="EUR_USD")


def test_candle_to_row_respects_complete_flag():
    candle = _oanda_candle("2020-01-01T22:00:00Z", complete=False)
    row = candle_to_row(candle, symbol="EUR_USD")
    assert row["is_complete"] is False


# ---- schema / lifecycle ------------------------------------------------


def test_init_creates_both_tables(tmp_path):
    path = tmp_path / "x.duckdb"
    s = FxStore(db_path=path)
    tables = s._con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name"
    ).fetchall()
    names = {row[0] for row in tables}
    assert "ohlcv_4h" in names
    assert "ohlcv_1h" in names
    s.close()


def test_read_only_mode_refuses_writes(tmp_path):
    path = tmp_path / "y.duckdb"
    FxStore(db_path=path).close()  # create schema first
    s = FxStore(db_path=path, read_only=True)
    try:
        with pytest.raises(RuntimeError, match="read-only"):
            s.save_rows([], granularity="H4")
    finally:
        s.close()


def test_rejects_invalid_granularity(store):
    with pytest.raises(ValueError, match="granularity"):
        store.save_rows([], granularity="H8")  # type: ignore[arg-type]


# ---- save_candles + load round-trip -----------------------------------


def test_save_candles_and_load_round_trip(store):
    candles = [
        _oanda_candle("2020-01-01T22:00:00Z"),
        _oanda_candle("2020-01-02T02:00:00Z"),
        _oanda_candle("2020-01-02T06:00:00Z"),
    ]
    written = store.save_candles("EUR_USD", candles, granularity="H4")
    assert written == 3

    df = store.load("EUR_USD", granularity="H4")
    assert len(df) == 3
    assert list(df["timestamp"]) == [
        pd.Timestamp("2020-01-01 22:00:00"),
        pd.Timestamp("2020-01-02 02:00:00"),
        pd.Timestamp("2020-01-02 06:00:00"),
    ]


def test_save_candles_skips_incomplete_by_default(store):
    candles = [
        _oanda_candle("2020-01-01T22:00:00Z", complete=True),
        _oanda_candle("2020-01-02T02:00:00Z", complete=False),
    ]
    written = store.save_candles("EUR_USD", candles, granularity="H4")
    assert written == 1
    df = store.load("EUR_USD", granularity="H4")
    assert len(df) == 1
    assert df["is_complete"].iloc[0] is True or df["is_complete"].iloc[0] == True  # noqa: E712


def test_save_candles_include_incomplete_flag(store):
    candles = [
        _oanda_candle("2020-01-01T22:00:00Z", complete=True),
        _oanda_candle("2020-01-02T02:00:00Z", complete=False),
    ]
    written = store.save_candles("EUR_USD", candles, granularity="H4", include_incomplete=True)
    assert written == 2
    df = store.load("EUR_USD", granularity="H4", include_incomplete=True)
    assert len(df) == 2
    df_complete_only = store.load("EUR_USD", granularity="H4", include_incomplete=False)
    assert len(df_complete_only) == 1


def test_save_candles_upsert_replaces_existing_row(store):
    original = _oanda_candle("2020-01-01T22:00:00Z", bid=(1.0, 1.0, 1.0, 1.0), ask=(1.001, 1.001, 1.001, 1.001))
    store.save_candles("EUR_USD", [original], granularity="H4")

    replacement = _oanda_candle("2020-01-01T22:00:00Z", bid=(2.0, 2.1, 1.9, 2.05), ask=(2.001, 2.101, 1.901, 2.051))
    store.save_candles("EUR_USD", [replacement], granularity="H4")

    df = store.load("EUR_USD", granularity="H4")
    assert len(df) == 1
    assert df["close_bid"].iloc[0] == 2.05


def test_save_candles_dedupes_within_batch(store):
    """Two candles with the same timestamp in one call: last-write-wins."""
    first = _oanda_candle("2020-01-01T22:00:00Z", bid=(1.0, 1.0, 1.0, 1.0))
    dup = _oanda_candle("2020-01-01T22:00:00Z", bid=(2.0, 2.0, 2.0, 2.05))
    written = store.save_candles("EUR_USD", [first, dup], granularity="H4")
    assert written == 1
    df = store.load("EUR_USD", granularity="H4")
    assert len(df) == 1
    assert df["close_bid"].iloc[0] == 2.05


def test_save_candles_different_symbols_coexist(store):
    store.save_candles("EUR_USD", [_oanda_candle("2020-01-01T22:00:00Z")], granularity="H4")
    store.save_candles("USD_JPY", [_oanda_candle("2020-01-01T22:00:00Z")], granularity="H4")
    df_eur = store.load("EUR_USD", granularity="H4")
    df_jpy = store.load("USD_JPY", granularity="H4")
    assert len(df_eur) == 1
    assert len(df_jpy) == 1


def test_granularity_tables_are_isolated(store):
    store.save_candles("EUR_USD", [_oanda_candle("2020-01-01T22:00:00Z")], granularity="H4")
    store.save_candles("EUR_USD", [_oanda_candle("2020-01-01T22:00:00Z")], granularity="H1")
    assert store.row_count(granularity="H4", symbol="EUR_USD") == 1
    assert store.row_count(granularity="H1", symbol="EUR_USD") == 1
    # Writing to one doesn't affect the other
    store.save_candles(
        "EUR_USD",
        [_oanda_candle("2020-01-01T23:00:00Z")],
        granularity="H1",
    )
    assert store.row_count(granularity="H4", symbol="EUR_USD") == 1
    assert store.row_count(granularity="H1", symbol="EUR_USD") == 2


# ---- date-range filter -------------------------------------------------


def test_load_filters_by_start_and_end(store):
    for d in ["2020-01-01T22:00:00Z", "2020-01-02T22:00:00Z", "2020-01-03T22:00:00Z"]:
        store.save_candles("EUR_USD", [_oanda_candle(d)], granularity="H4")

    df = store.load(
        "EUR_USD",
        granularity="H4",
        start=datetime(2020, 1, 2),
        end=datetime(2020, 1, 3),
    )
    assert len(df) == 1
    assert df["timestamp"].iloc[0] == pd.Timestamp("2020-01-02 22:00:00")


def test_load_empty_returns_empty_df(store):
    df = store.load("NONEXISTENT", granularity="H4")
    assert len(df) == 0


# ---- latest_timestamp --------------------------------------------------


def test_latest_timestamp_none_when_empty(store):
    assert store.latest_timestamp("EUR_USD", granularity="H4") is None


def test_latest_timestamp_returns_max(store):
    for d in ["2020-01-01T22:00:00Z", "2020-01-02T22:00:00Z", "2020-01-01T18:00:00Z"]:
        store.save_candles("EUR_USD", [_oanda_candle(d)], granularity="H4")
    got = store.latest_timestamp("EUR_USD", granularity="H4")
    assert got == datetime(2020, 1, 2, 22, 0, 0)


def test_latest_timestamp_only_complete(store):
    store.save_candles(
        "EUR_USD",
        [_oanda_candle("2020-01-01T22:00:00Z", complete=True)],
        granularity="H4",
    )
    store.save_candles(
        "EUR_USD",
        [_oanda_candle("2020-01-02T22:00:00Z", complete=False)],
        granularity="H4",
        include_incomplete=True,
    )
    latest_all = store.latest_timestamp("EUR_USD", granularity="H4", only_complete=False)
    latest_complete = store.latest_timestamp("EUR_USD", granularity="H4", only_complete=True)
    assert latest_all == datetime(2020, 1, 2, 22, 0, 0)
    assert latest_complete == datetime(2020, 1, 1, 22, 0, 0)


# ---- coverage ----------------------------------------------------------


def test_coverage_per_symbol(store):
    store.save_candles("EUR_USD", [_oanda_candle("2020-01-01T22:00:00Z")], granularity="H4")
    store.save_candles("EUR_USD", [_oanda_candle("2020-02-01T22:00:00Z")], granularity="H4")
    store.save_candles("USD_JPY", [_oanda_candle("2020-03-01T22:00:00Z")], granularity="H4")
    cov = store.coverage(granularity="H4")
    assert set(cov.keys()) == {"EUR_USD", "USD_JPY"}
    eur = cov["EUR_USD"]
    assert isinstance(eur, Coverage)
    assert eur.min_timestamp == datetime(2020, 1, 1, 22, 0)
    assert eur.max_timestamp == datetime(2020, 2, 1, 22, 0)
    assert eur.row_count == 2


def test_symbols_returns_sorted_distinct(store):
    store.save_candles("USD_JPY", [_oanda_candle("2020-01-01T22:00:00Z")], granularity="H4")
    store.save_candles("EUR_USD", [_oanda_candle("2020-01-01T22:00:00Z")], granularity="H4")
    assert store.symbols(granularity="H4") == ["EUR_USD", "USD_JPY"]


# ---- utility ----------------------------------------------------------


def test_context_manager_closes_connection(tmp_path):
    path = tmp_path / "ctx.duckdb"
    with FxStore(db_path=path) as s:
        s.save_candles("EUR_USD", [_oanda_candle("2020-01-01T22:00:00Z")], granularity="H4")
    # Re-open to verify data persisted
    with FxStore(db_path=path) as s2:
        assert s2.row_count(granularity="H4", symbol="EUR_USD") == 1
