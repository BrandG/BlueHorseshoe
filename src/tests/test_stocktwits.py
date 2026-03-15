"""Tests for StockTwits sentiment module."""

from unittest.mock import MagicMock, patch

import pytest

from bluehorseshoe.data.stocktwits import (
    fetch_stocktwits_messages,
    score_stocktwits_messages,
    upsert_stocktwits_to_mongo,
    get_stocktwits_sentiment_score_with_count,
)


# ── score_stocktwits_messages ─────────────────────────────────────────


def test_score_all_bullish():
    """All bullish messages produce score 1.0."""
    messages = [
        {"entities": {"sentiment": {"basic": "Bullish"}}} for _ in range(5)
    ]
    score, bull, bear, total = score_stocktwits_messages(messages)
    assert score == 1.0
    assert bull == 5
    assert bear == 0
    assert total == 5


def test_score_all_bearish():
    """All bearish messages produce score -1.0."""
    messages = [
        {"entities": {"sentiment": {"basic": "Bearish"}}} for _ in range(5)
    ]
    score, bull, bear, total = score_stocktwits_messages(messages)
    assert score == -1.0
    assert bull == 0
    assert bear == 5
    assert total == 5


def test_score_mixed():
    """Equal bull/bear counts produce score 0.0."""
    messages = [
        {"entities": {"sentiment": {"basic": "Bullish"}}},
        {"entities": {"sentiment": {"basic": "Bearish"}}},
        {"entities": {"sentiment": {"basic": "Bullish"}}},
        {"entities": {"sentiment": {"basic": "Bearish"}}},
    ]
    score, bull, bear, total = score_stocktwits_messages(messages)
    assert score == 0.0
    assert bull == 2
    assert bear == 2
    assert total == 4


def test_score_no_tagged_messages():
    """Messages with no sentiment tags produce score 0.0 and count 0."""
    messages = [
        {"entities": {"sentiment": None}},
        {"entities": None},
        {"body": "no entities key"},
    ]
    score, bull, bear, total = score_stocktwits_messages(messages)
    assert score == 0.0
    assert bull == 0
    assert bear == 0
    assert total == 0


def test_score_null_entities():
    """Messages with entities=None are skipped gracefully."""
    messages = [
        {"entities": None},
        {"entities": {"sentiment": {"basic": "Bullish"}}},
        {"entities": None},
    ]
    score, bull, bear, total = score_stocktwits_messages(messages)
    assert score == 1.0
    assert bull == 1
    assert total == 1


def test_score_empty_list():
    """Empty messages list produces score 0.0 and count 0."""
    score, bull, bear, total = score_stocktwits_messages([])
    assert score == 0.0
    assert bull == 0
    assert bear == 0
    assert total == 0


# ── MongoDB operations ────────────────────────────────────────────────

@pytest.fixture
def mock_database():
    """Create a mock MongoDB database."""
    return MagicMock()


def test_upsert_stocktwits_to_mongo(mock_database):
    """Upserts document with correct shape."""
    messages = [{"body": "text", "entities": {"sentiment": {"basic": "Bullish"}}}]
    score_data = (1.0, 1, 0, 1)

    upsert_stocktwits_to_mongo("aapl", messages, score_data, database=mock_database)

    col = mock_database["symbol_news_stocktwits"]
    col.update_one.assert_called_once()
    args = col.update_one.call_args
    assert args[0][0] == {"symbol": "AAPL"}  # filter
    doc = args[0][1]["$set"]
    assert doc["symbol"] == "AAPL"
    assert doc["messages"] == messages
    assert doc["score"] == 1.0
    assert doc["bullish"] == 1
    assert doc["bearish"] == 0
    assert doc["total_tagged"] == 1
    assert "last_updated" in doc


def test_get_stocktwits_sentiment_score_with_count(mock_database):
    """Returns stored score and count."""
    mock_database["symbol_news_stocktwits"].find_one.return_value = {
        "symbol": "AAPL",
        "score": 0.6,
        "total_tagged": 8,
    }

    score, count = get_stocktwits_sentiment_score_with_count(
        "AAPL", "2026-03-14", database=mock_database
    )

    assert score == 0.6
    assert count == 8


def test_get_stocktwits_sentiment_no_data(mock_database):
    """Returns (0.0, 0) when symbol not in DB."""
    mock_database["symbol_news_stocktwits"].find_one.return_value = None

    score, count = get_stocktwits_sentiment_score_with_count(
        "XYZ", "2026-03-14", database=mock_database
    )

    assert score == 0.0
    assert count == 0


# ── fetch_stocktwits_messages ─────────────────────────────────────────

@patch("bluehorseshoe.data.stocktwits.requests.get")
def test_fetch_stocktwits_messages_success(mock_get):
    """Returns messages list on successful response."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "response": {"status": 200},
        "symbol": {"symbol": "AAPL"},
        "messages": [
            {"id": 1, "body": "bull!", "entities": {"sentiment": {"basic": "Bullish"}}},
            {"id": 2, "body": "meh", "entities": None},
        ],
    }
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    result = fetch_stocktwits_messages("AAPL")

    assert len(result) == 2
    mock_get.assert_called_once()
    call_args = mock_get.call_args
    assert "AAPL" in call_args[0][0]


@patch("bluehorseshoe.data.stocktwits.requests.get")
def test_fetch_stocktwits_messages_404(mock_get):
    """Returns empty list when symbol not found (404)."""
    mock_get.side_effect = Exception("404 Client Error")

    result = fetch_stocktwits_messages("ZZZZZ")

    assert result == []


@patch("bluehorseshoe.data.stocktwits.requests.get")
def test_fetch_stocktwits_messages_rate_limited(mock_get):
    """Returns empty list on rate-limit error (429)."""
    mock_get.side_effect = Exception("429 Too Many Requests")

    result = fetch_stocktwits_messages("AAPL")

    assert result == []
