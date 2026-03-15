"""Tests for Tiingo news sentiment module."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from bluehorseshoe.data.tiingo_news import (
    score_article_vader,
    score_articles,
    fetch_tiingo_news,
    upsert_tiingo_news_to_mongo,
    get_tiingo_sentiment_score_with_count,
)


# ── VADER scoring ────────────────────────────────────────────────────

def test_positive_headline():
    """Positive headline returns positive compound score."""
    score = score_article_vader("Company reports record earnings and strong growth")
    assert score > 0.0


def test_negative_headline():
    """Negative headline returns negative compound score."""
    score = score_article_vader("Stock crashes amid fraud investigation and massive losses")
    assert score < 0.0


def test_empty_title():
    """Empty or None title returns 0.0."""
    assert score_article_vader("") == 0.0
    assert score_article_vader(None) == 0.0


# ── Batch scoring ────────────────────────────────────────────────────

def test_score_articles_adds_vader_score():
    """score_articles adds vader_score key to each article dict."""
    articles = [
        {"title": "Great earnings beat expectations", "id": 1},
        {"title": "CEO resigns amid scandal", "id": 2},
        {"title": "", "id": 3},
    ]
    result = score_articles(articles)

    assert len(result) == 3
    for art in result:
        assert "vader_score" in art
    assert result[0]["vader_score"] > 0.0  # positive
    assert result[1]["vader_score"] < 0.0  # negative
    assert result[2]["vader_score"] == 0.0  # empty


# ── get_tiingo_sentiment_score_with_count ────────────────────────────

@pytest.fixture
def mock_database():
    """Create a mock MongoDB database."""
    return MagicMock()


def test_get_tiingo_sentiment_score_with_count(mock_database):
    """Returns average VADER score within 7-day window."""
    articles = [
        {
            "publishedDate": "2026-03-10T15:30:00+00:00",
            "vader_score": 0.4,
        },
        {
            "publishedDate": "2026-03-12T09:00:00+00:00",
            "vader_score": 0.6,
        },
        {
            # Outside 7-day window
            "publishedDate": "2026-02-01T10:00:00+00:00",
            "vader_score": 0.9,
        },
    ]
    mock_database["symbol_news_tiingo"].find_one.return_value = {
        "symbol": "AAPL",
        "articles": articles,
    }

    score, count = get_tiingo_sentiment_score_with_count(
        "AAPL", "2026-03-14", database=mock_database
    )

    assert count == 2
    assert score == pytest.approx(0.5)  # (0.4 + 0.6) / 2


def test_get_tiingo_sentiment_no_data(mock_database):
    """Returns (0.0, 0) when no documents exist."""
    mock_database["symbol_news_tiingo"].find_one.return_value = None

    score, count = get_tiingo_sentiment_score_with_count(
        "AAPL", "2026-03-14", database=mock_database
    )

    assert score == 0.0
    assert count == 0


def test_get_tiingo_sentiment_empty_articles(mock_database):
    """Returns (0.0, 0) when articles list is empty."""
    mock_database["symbol_news_tiingo"].find_one.return_value = {
        "symbol": "AAPL",
        "articles": [],
    }

    score, count = get_tiingo_sentiment_score_with_count(
        "AAPL", "2026-03-14", database=mock_database
    )

    assert score == 0.0
    assert count == 0


def test_get_tiingo_sentiment_requires_database():
    """Raises ValueError when database is None."""
    with pytest.raises(ValueError, match="database parameter is required"):
        get_tiingo_sentiment_score_with_count("AAPL", "2026-03-14")


# ── MongoDB upsert ──────────────────────────────────────────────────

def test_upsert_tiingo_news_to_mongo(mock_database):
    """Upserts document with correct shape."""
    articles = [
        {"title": "Headline", "vader_score": 0.5, "publishedDate": "2026-03-14T10:00:00+00:00"},
    ]

    upsert_tiingo_news_to_mongo("aapl", articles, database=mock_database)

    col = mock_database["symbol_news_tiingo"]
    col.update_one.assert_called_once()
    args = col.update_one.call_args
    assert args[0][0] == {"symbol": "AAPL"}  # filter
    doc = args[0][1]["$set"]
    assert doc["symbol"] == "AAPL"
    assert doc["articles"] == articles
    assert "last_updated" in doc


def test_upsert_tiingo_news_requires_database():
    """Raises ValueError when database is None."""
    with pytest.raises(ValueError, match="database parameter is required"):
        upsert_tiingo_news_to_mongo("AAPL", [])


# ── fetch_tiingo_news ───────────────────────────────────────────────

@patch("bluehorseshoe.data.tiingo_news.get_settings")
def test_fetch_tiingo_news_no_api_key(mock_settings):
    """Returns empty list when TIINGO_API_KEY is not set."""
    mock_settings.return_value = MagicMock(tiingo_api_key="", tiingo_cps=5)

    result = fetch_tiingo_news("AAPL")

    assert result == []


@patch("bluehorseshoe.data.tiingo_news.requests.get")
@patch("bluehorseshoe.data.tiingo_news.get_settings")
def test_fetch_tiingo_news_success(mock_settings, mock_get):
    """Returns articles list on successful response."""
    mock_settings.return_value = MagicMock(tiingo_api_key="testkey", tiingo_cps=5)
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"title": "AAPL hits new high", "publishedDate": "2026-03-14T10:00:00+00:00"},
        {"title": "Apple launches product", "publishedDate": "2026-03-13T12:00:00+00:00"},
    ]
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    result = fetch_tiingo_news("AAPL")

    assert len(result) == 2
    mock_get.assert_called_once()
    # Verify token param was passed
    call_kwargs = mock_get.call_args
    assert call_kwargs[1]["params"]["token"] == "testkey"


@patch("bluehorseshoe.data.tiingo_news.requests.get")
@patch("bluehorseshoe.data.tiingo_news.get_settings")
def test_fetch_tiingo_news_http_error(mock_settings, mock_get):
    """Returns empty list on HTTP error."""
    mock_settings.return_value = MagicMock(tiingo_api_key="testkey", tiingo_cps=5)
    mock_get.side_effect = Exception("Connection refused")

    result = fetch_tiingo_news("AAPL")

    assert result == []
