"""Tests for sentiment snapshot storage functions."""

from datetime import datetime
from unittest.mock import MagicMock, patch, call

import pytest

from bluehorseshoe.core.symbols import (
    get_sentiment_score,
    get_sentiment_score_with_count,
    save_sentiment_snapshots,
    get_sentiment_history,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def mock_database():
    """Create a mock MongoDB database."""
    db = MagicMock()
    return db


@pytest.fixture
def sample_feed():
    """News feed with two articles matching AAPL within 7-day window."""
    return [
        {
            "time_published": "20260310T120000",
            "ticker_sentiment": [
                {"ticker": "AAPL", "ticker_sentiment_score": "0.4"},
                {"ticker": "MSFT", "ticker_sentiment_score": "0.1"},
            ],
        },
        {
            "time_published": "20260312T080000",
            "ticker_sentiment": [
                {"ticker": "AAPL", "ticker_sentiment_score": "0.6"},
            ],
        },
        {
            "time_published": "20260201T080000",  # Outside 7-day window
            "ticker_sentiment": [
                {"ticker": "AAPL", "ticker_sentiment_score": "0.9"},
            ],
        },
    ]


# ── get_sentiment_score_with_count ────────────────────────────────────

def test_get_sentiment_score_with_count(mock_database, sample_feed):
    """Returns (average_score, article_count) tuple."""
    mock_database["symbol_news"].find_one.return_value = {"feed": sample_feed}

    score, count = get_sentiment_score_with_count("AAPL", "2026-03-14", database=mock_database)

    assert count == 2
    assert score == pytest.approx(0.5)  # (0.4 + 0.6) / 2


def test_get_sentiment_score_with_count_no_feed(mock_database):
    """Returns (0.0, 0) when no feed exists."""
    mock_database["symbol_news"].find_one.return_value = None

    score, count = get_sentiment_score_with_count("AAPL", "2026-03-14", database=mock_database)

    assert score == 0.0
    assert count == 0


def test_get_sentiment_score_with_count_no_match(mock_database):
    """Returns (0.0, 0) when no articles match the symbol."""
    feed = [
        {
            "time_published": "20260312T080000",
            "ticker_sentiment": [
                {"ticker": "MSFT", "ticker_sentiment_score": "0.5"},
            ],
        },
    ]
    mock_database["symbol_news"].find_one.return_value = {"feed": feed}

    score, count = get_sentiment_score_with_count("AAPL", "2026-03-14", database=mock_database)

    assert score == 0.0
    assert count == 0


# ── get_sentiment_score backward compat ───────────────────────────────

def test_get_sentiment_score_backward_compat(mock_database, sample_feed):
    """get_sentiment_score still returns a plain float."""
    mock_database["symbol_news"].find_one.return_value = {"feed": sample_feed}

    result = get_sentiment_score("AAPL", "2026-03-14", database=mock_database)

    assert isinstance(result, float)
    assert result == pytest.approx(0.5)


# ── save_sentiment_snapshots ──────────────────────────────────────────

def test_save_sentiment_snapshots(mock_database):
    """Verifies bulk_write with correct UpdateOne ops."""
    col = mock_database["sentiment_snapshots"]
    mock_result = MagicMock()
    mock_result.upserted_count = 2
    mock_result.modified_count = 0
    col.bulk_write.return_value = mock_result

    snapshots = [
        {"symbol": "AAPL", "date": "2026-03-14", "score": 0.5, "article_count": 2},
        {"symbol": "MSFT", "date": "2026-03-14", "score": 0.3, "article_count": 5},
    ]

    count = save_sentiment_snapshots(snapshots, database=mock_database)

    assert count == 2
    col.create_index.assert_called_once()
    col.bulk_write.assert_called_once()

    # Verify the ops contain correct filters
    ops = col.bulk_write.call_args[0][0]
    assert len(ops) == 2


def test_save_empty_list(mock_database):
    """Returns 0 and performs no writes for empty list."""
    count = save_sentiment_snapshots([], database=mock_database)

    assert count == 0
    mock_database["sentiment_snapshots"].bulk_write.assert_not_called()


def test_save_sentiment_snapshots_requires_database():
    """Raises ValueError when database is None."""
    with pytest.raises(ValueError, match="database parameter is required"):
        save_sentiment_snapshots([{"symbol": "AAPL"}])


# ── get_sentiment_history ─────────────────────────────────────────────

def test_get_sentiment_history(mock_database):
    """Returns documents newest first, respects limit."""
    docs = [
        {"symbol": "AAPL", "date": "2026-03-14", "score": 0.5, "article_count": 2},
        {"symbol": "AAPL", "date": "2026-03-13", "score": 0.3, "article_count": 4},
    ]
    col = mock_database["sentiment_snapshots"]
    # Chain: find().sort().limit() returns docs
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = docs
    col.find.return_value = cursor

    result = get_sentiment_history("AAPL", limit=10, database=mock_database)

    assert result == docs
    col.find.assert_called_once_with({"symbol": "AAPL"}, {"_id": 0})
    cursor.sort.assert_called_once_with("date", -1)
    cursor.limit.assert_called_once_with(10)


def test_get_sentiment_history_requires_database():
    """Raises ValueError when database is None."""
    with pytest.raises(ValueError, match="database parameter is required"):
        get_sentiment_history("AAPL")
