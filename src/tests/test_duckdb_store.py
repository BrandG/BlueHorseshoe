"""
Unit tests for DuckDBStore — in-memory, no file I/O.
"""
import pytest
import pandas as pd
from bluehorseshoe.data.duckdb_store import DuckDBStore


@pytest.fixture
def store():
    """Create an in-memory DuckDB store for each test."""
    s = DuckDBStore(":memory:")
    yield s
    s.close()


def _make_df(dates, close_start=100.0, symbol=None):
    """Helper to build a small OHLCV DataFrame."""
    rows = []
    for i, d in enumerate(dates):
        c = close_start + i
        rows.append({
            "date": d,
            "open": c - 0.5,
            "high": c + 1.0,
            "low": c - 1.0,
            "close": c,
            "volume": 1_000_000.0 + i * 1000,
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------
# Basic save / load roundtrip
# ------------------------------------------------------------------
class TestSaveLoad:
    def test_save_and_load_roundtrip(self, store):
        dates = ["2025-01-02", "2025-01-03", "2025-01-06"]
        df = _make_df(dates)
        store.save_symbol("AAPL", df, full_name="Apple Inc.")

        loaded = store.load_symbol("AAPL")
        assert loaded is not None
        assert len(loaded) == 3
        assert list(loaded["date"]) == dates
        assert loaded["close"].iloc[0] == 100.0

    def test_load_nonexistent_returns_none(self, store):
        assert store.load_symbol("NOPE") is None

    def test_load_symbol_dict_format(self, store):
        df = _make_df(["2025-01-02", "2025-01-03"])
        store.save_symbol("MSFT", df, full_name="Microsoft Corp.")

        result = store.load_symbol_dict("MSFT")
        assert "days" in result
        assert "full_name" in result
        assert result["full_name"] == "Microsoft Corp."
        assert len(result["days"]) == 2
        assert result["days"][0]["date"] == "2025-01-02"

    def test_load_symbol_dict_empty(self, store):
        result = store.load_symbol_dict("NOPE")
        assert result == {}


# ------------------------------------------------------------------
# Upsert behaviour
# ------------------------------------------------------------------
class TestUpsert:
    def test_upsert_replaces_existing_rows(self, store):
        df1 = _make_df(["2025-01-02", "2025-01-03"], close_start=100.0)
        store.save_symbol("AAPL", df1)

        # Update with different close prices
        df2 = _make_df(["2025-01-02", "2025-01-03"], close_start=200.0)
        store.save_symbol("AAPL", df2)

        loaded = store.load_symbol("AAPL")
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded["close"].iloc[0] == 200.0

    def test_upsert_appends_new_dates(self, store):
        df1 = _make_df(["2025-01-02"])
        store.save_symbol("AAPL", df1)

        df2 = _make_df(["2025-01-03"], close_start=110.0)
        store.save_symbol("AAPL", df2)

        loaded = store.load_symbol("AAPL")
        assert loaded is not None
        assert len(loaded) == 2


# ------------------------------------------------------------------
# Date filtering
# ------------------------------------------------------------------
class TestDateFilter:
    def test_start_date_filter(self, store):
        dates = ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]
        store.save_symbol("AAPL", _make_df(dates))

        loaded = store.load_symbol("AAPL", start_date="2025-01-06")
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded["date"].iloc[0] == "2025-01-06"

    def test_end_date_filter(self, store):
        dates = ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]
        store.save_symbol("AAPL", _make_df(dates))

        loaded = store.load_symbol("AAPL", end_date="2025-01-03")
        assert loaded is not None
        assert len(loaded) == 2

    def test_date_range_filter(self, store):
        dates = ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]
        store.save_symbol("AAPL", _make_df(dates))

        loaded = store.load_symbol("AAPL", start_date="2025-01-03", end_date="2025-01-06")
        assert loaded is not None
        assert len(loaded) == 2


# ------------------------------------------------------------------
# Bulk load
# ------------------------------------------------------------------
class TestBulkLoad:
    def test_load_symbols_bulk(self, store):
        store.save_symbol("AAPL", _make_df(["2025-01-02", "2025-01-03"]))
        store.save_symbol("MSFT", _make_df(["2025-01-02", "2025-01-03"], close_start=200.0))
        store.save_symbol("GOOG", _make_df(["2025-01-02", "2025-01-03"], close_start=300.0))

        result = store.load_symbols_bulk(["AAPL", "MSFT"])
        assert len(result) == 2
        assert "AAPL" in result
        assert "MSFT" in result
        assert "GOOG" not in result

    def test_bulk_with_start_date(self, store):
        dates = ["2025-01-02", "2025-01-03", "2025-01-06"]
        store.save_symbol("AAPL", _make_df(dates))

        result = store.load_symbols_bulk(["AAPL"], start_date="2025-01-03")
        assert "AAPL" in result
        # start_date uses > (not >=), so only 2025-01-06
        assert len(result["AAPL"]) == 1

    def test_bulk_empty_list(self, store):
        assert store.load_symbols_bulk([]) == {}


# ------------------------------------------------------------------
# Universe snapshot
# ------------------------------------------------------------------
class TestUniverseSnapshot:
    def test_snapshot_for_date(self, store):
        store.save_symbol("AAPL", _make_df(["2025-01-02"], close_start=150.0))
        store.save_symbol("MSFT", _make_df(["2025-01-02"], close_start=300.0))
        store.save_symbol("PENNY", _make_df(["2025-01-02"], close_start=0.5))

        result = store.load_universe_snapshot("2025-01-02", min_price=1.0)
        symbols = [r["symbol"] for r in result]
        assert "AAPL" in symbols
        assert "MSFT" in symbols
        assert "PENNY" not in symbols

    def test_snapshot_no_data(self, store):
        assert store.load_universe_snapshot("2025-01-02") == []


# ------------------------------------------------------------------
# Metadata / utility
# ------------------------------------------------------------------
class TestMetadata:
    def test_get_latest_date(self, store):
        store.save_symbol("AAPL", _make_df(["2025-01-02", "2025-01-03"]))
        store.save_symbol("MSFT", _make_df(["2025-01-06"]))

        assert store.get_latest_date() == "2025-01-06"

    def test_get_latest_date_empty(self, store):
        assert store.get_latest_date() is None

    def test_get_symbol_dates(self, store):
        dates = ["2025-01-02", "2025-01-03", "2025-01-06"]
        store.save_symbol("AAPL", _make_df(dates))

        assert store.get_symbol_dates("AAPL") == dates
        assert store.get_symbol_dates("NOPE") == []

    def test_get_metadata(self, store):
        store.save_symbol("AAPL", _make_df(["2025-01-02"]), full_name="Apple Inc.")

        meta = store.get_metadata("AAPL")
        assert meta is not None
        assert meta["full_name"] == "Apple Inc."
        assert meta["last_updated"] is not None

    def test_symbol_count(self, store):
        assert store.symbol_count() == 0
        store.save_symbol("AAPL", _make_df(["2025-01-02"]))
        store.save_symbol("MSFT", _make_df(["2025-01-02"]))
        assert store.symbol_count() == 2

    def test_row_count(self, store):
        store.save_symbol("AAPL", _make_df(["2025-01-02", "2025-01-03"]))
        assert store.row_count() == 2
        assert store.row_count("AAPL") == 2
        assert store.row_count("NOPE") == 0


# ------------------------------------------------------------------
# Symbol coverage
# ------------------------------------------------------------------
class TestSymbolCoverage:
    def test_coverage_empty_store(self, store):
        assert store.get_symbol_coverage() == {}

    def test_coverage_multiple_symbols(self, store):
        store.save_symbol("AAPL", _make_df(["2020-01-02", "2020-01-03", "2020-01-06"]))
        store.save_symbol("MSFT", _make_df(["2021-06-01", "2021-06-02"], close_start=200.0))

        cov = store.get_symbol_coverage()
        assert len(cov) == 2

        assert cov["AAPL"]["min_date"] == "2020-01-02"
        assert cov["AAPL"]["max_date"] == "2020-01-06"
        assert cov["AAPL"]["row_count"] == 3

        assert cov["MSFT"]["min_date"] == "2021-06-01"
        assert cov["MSFT"]["max_date"] == "2021-06-02"
        assert cov["MSFT"]["row_count"] == 2

    def test_coverage_single_row(self, store):
        store.save_symbol("TSLA", _make_df(["2025-03-01"]))
        cov = store.get_symbol_coverage()
        assert cov["TSLA"]["min_date"] == "2025-03-01"
        assert cov["TSLA"]["max_date"] == "2025-03-01"
        assert cov["TSLA"]["row_count"] == 1


# ------------------------------------------------------------------
# Column filtering (only OHLCV persisted)
# ------------------------------------------------------------------
class TestColumnFiltering:
    def test_indicator_columns_dropped(self, store):
        """Indicator columns in the input DataFrame are silently dropped."""
        df = _make_df(["2025-01-02"])
        df["rsi_14"] = 55.0
        df["custom_indicator"] = 42.0
        store.save_symbol("AAPL", df)

        loaded = store.load_symbol("AAPL")
        assert loaded is not None
        # Core OHLCV columns present
        assert "close" in loaded.columns
        assert "volume" in loaded.columns
        # Indicator columns NOT present
        assert "rsi_14" not in loaded.columns
        assert "custom_indicator" not in loaded.columns

    def test_save_empty_df_is_noop(self, store):
        store.save_symbol("AAPL", pd.DataFrame())
        assert store.load_symbol("AAPL") is None

    def test_save_none_is_noop(self, store):
        store.save_symbol("AAPL", None)
        assert store.load_symbol("AAPL") is None
