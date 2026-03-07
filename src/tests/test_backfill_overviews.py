"""
Tests for backfill_overviews in symbols.py.
"""
from unittest.mock import patch, MagicMock, call

from bluehorseshoe.core.symbols import backfill_overviews


def _make_mock_db(existing_symbols, candidate_docs):
    """
    Build a mock database where:
      - symbol_overviews.find() returns existing_symbols
      - symbols.find().sort() returns candidate_docs
    """
    mock_db = MagicMock()

    mock_overviews = MagicMock()
    mock_overviews.find.return_value = [{"symbol": s} for s in existing_symbols]

    mock_symbols_cursor = MagicMock()
    mock_symbols_cursor.sort.return_value = candidate_docs

    mock_symbols = MagicMock()
    mock_symbols.find.return_value = mock_symbols_cursor

    def getitem(name):
        if name == "symbol_overviews":
            return mock_overviews
        if name == "symbols":
            return mock_symbols
        return MagicMock()

    mock_db.__getitem__ = MagicMock(side_effect=getitem)
    return mock_db


@patch("bluehorseshoe.core.symbols.upsert_overview_to_mongo")
@patch("bluehorseshoe.core.symbols.fetch_overview_from_net")
def test_backfill_skips_existing(mock_fetch, mock_upsert):
    """Symbols already in symbol_overviews should not be fetched."""
    mock_db = _make_mock_db(
        existing_symbols=["AAPL", "MSFT"],
        candidate_docs=[{"symbol": "GOOG"}],  # Only GOOG is missing
    )
    mock_fetch.return_value = {"Symbol": "GOOG", "MarketCapitalization": "1000000000"}

    result = backfill_overviews(mock_db)

    # Should only fetch GOOG, not AAPL or MSFT
    mock_fetch.assert_called_once_with("GOOG")
    mock_upsert.assert_called_once()
    assert result == 1


@patch("bluehorseshoe.core.symbols.upsert_overview_to_mongo")
@patch("bluehorseshoe.core.symbols.fetch_overview_from_net")
def test_backfill_skips_nyse_arca(mock_fetch, mock_upsert):
    """NYSE ARCA symbols should be excluded by the DB query filter."""
    mock_db = _make_mock_db(
        existing_symbols=[],
        candidate_docs=[{"symbol": "GOOG"}],  # NYSE ARCA excluded by query
    )

    # Verify the query passed to symbols.find() excludes NYSE ARCA
    mock_fetch.return_value = {"Symbol": "GOOG", "MarketCapitalization": "1000000000"}
    backfill_overviews(mock_db)

    # Check the filter passed to symbols.find
    symbols_col = mock_db["symbols"]
    find_args = symbols_col.find.call_args
    query = find_args[0][0]
    assert "NYSE ARCA" in query["exchange"]["$nin"]


@patch("bluehorseshoe.core.symbols.upsert_overview_to_mongo")
@patch("bluehorseshoe.core.symbols.fetch_overview_from_net")
def test_backfill_respects_limit(mock_fetch, mock_upsert):
    """The limit parameter should cap the number of symbols fetched."""
    mock_db = _make_mock_db(
        existing_symbols=[],
        candidate_docs=[{"symbol": "A"}, {"symbol": "B"}, {"symbol": "C"}],
    )
    mock_fetch.return_value = {"Symbol": "X", "MarketCapitalization": "500000000"}

    result = backfill_overviews(mock_db, limit=2)

    assert mock_fetch.call_count == 2
    assert result == 2


@patch("bluehorseshoe.core.symbols.upsert_overview_to_mongo")
@patch("bluehorseshoe.core.symbols.fetch_overview_from_net")
def test_backfill_handles_empty_overview(mock_fetch, mock_upsert):
    """Symbols returning empty overview should not be upserted."""
    mock_db = _make_mock_db(
        existing_symbols=[],
        candidate_docs=[{"symbol": "DEAD"}],
    )
    mock_fetch.return_value = {}  # Empty overview (e.g., delisted/ETF)

    result = backfill_overviews(mock_db)

    mock_fetch.assert_called_once_with("DEAD")
    mock_upsert.assert_not_called()
    assert result == 0


@patch("bluehorseshoe.core.symbols.upsert_overview_to_mongo")
@patch("bluehorseshoe.core.symbols.fetch_overview_from_net")
def test_backfill_handles_fetch_exception(mock_fetch, mock_upsert):
    """Fetch exceptions should be logged but not abort the run."""
    mock_db = _make_mock_db(
        existing_symbols=[],
        candidate_docs=[{"symbol": "ERR"}, {"symbol": "OK"}],
    )
    mock_fetch.side_effect = [
        RuntimeError("API rate limit"),
        {"Symbol": "OK", "MarketCapitalization": "500000000"},
    ]

    result = backfill_overviews(mock_db)

    assert mock_fetch.call_count == 2
    assert mock_upsert.call_count == 1  # Only OK was upserted
    assert result == 1
