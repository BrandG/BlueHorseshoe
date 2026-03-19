"""Tests for SentimentNormalizer — z-score + tanh composite sentiment."""
import math
from unittest.mock import MagicMock, patch

import pytest

from bluehorseshoe.analysis.sentiment_normalizer import (
    MIN_HISTORY_COUNT,
    SentimentNormalizer,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
@pytest.fixture
def mock_db():
    """Return a MagicMock that behaves like a pymongo Database."""
    return MagicMock()


@pytest.fixture
def normalizer(mock_db):
    """SentimentNormalizer with pre-loaded stats for all four sources."""
    n = SentimentNormalizer(database=mock_db)
    n.stats = {
        "alphavantage": {"mean": 0.10, "std": 0.20, "count": 100},
        "tiingo": {"mean": 0.05, "std": 0.15, "count": 80},
        "stocktwits": {"mean": 0.00, "std": 0.30, "count": 60},
        "finviz": {"mean": -0.02, "std": 0.18, "count": 50},
    }
    return n


# ------------------------------------------------------------------
# normalize()
# ------------------------------------------------------------------
class TestNormalize:
    def test_normalize_with_stats(self, normalizer):
        """z-score + tanh produces expected value."""
        raw = 0.30
        # z = (0.30 - 0.10) / 0.20 = 1.0
        expected = math.tanh(1.0)
        result = normalizer.normalize(raw, "alphavantage")
        assert result == pytest.approx(expected, abs=1e-6)

    def test_normalize_negative(self, normalizer):
        """Negative raw scores produce negative normalized values."""
        raw = -0.25
        # z = (-0.25 - 0.05) / 0.15 = -2.0
        expected = math.tanh(-2.0)
        result = normalizer.normalize(raw, "tiingo")
        assert result == pytest.approx(expected, abs=1e-6)

    def test_normalize_zero_raw_returns_zero(self, normalizer):
        """A raw score of 0.0 is returned as-is (no data)."""
        assert normalizer.normalize(0.0, "alphavantage") == 0.0

    def test_normalize_fallback_insufficient_history(self, normalizer):
        """Returns raw score when count < MIN_HISTORY_COUNT."""
        normalizer.stats["alphavantage"]["count"] = MIN_HISTORY_COUNT - 1
        raw = 0.30
        assert normalizer.normalize(raw, "alphavantage") == raw

    def test_normalize_fallback_zero_std(self, normalizer):
        """Returns raw score when std is 0."""
        normalizer.stats["alphavantage"]["std"] = 0.0
        raw = 0.30
        assert normalizer.normalize(raw, "alphavantage") == raw

    def test_normalize_fallback_missing_source(self, normalizer):
        """Returns raw score when source is not in stats."""
        raw = 0.42
        assert normalizer.normalize(raw, "unknown_source") == raw


# ------------------------------------------------------------------
# composite()
# ------------------------------------------------------------------
class TestComposite:
    def test_composite_all_sources(self, normalizer):
        """Averages raw values across all 4 sources."""
        candidate = {
            "sentiment": 0.30,
            "sentiment_tiingo": 0.20,
            "sentiment_stocktwits": 0.10,
            "sentiment_finviz": -0.10,
        }
        result = normalizer.composite(candidate)
        expected = (0.30 + 0.20 + 0.10 + -0.10) / 4
        assert result == pytest.approx(expected, abs=1e-6)

    def test_composite_partial_sources(self, normalizer):
        """Skips sources with score 0.0."""
        candidate = {
            "sentiment": 0.30,
            "sentiment_tiingo": 0.0,  # skip
            "sentiment_stocktwits": 0.10,
            "sentiment_finviz": 0.0,  # skip
        }
        result = normalizer.composite(candidate)
        expected = (0.30 + 0.10) / 2
        assert result == pytest.approx(expected, abs=1e-6)

    def test_composite_no_sources(self, normalizer):
        """Returns 0.0 when all sources are zero or missing."""
        candidate = {
            "sentiment": 0.0,
            "sentiment_tiingo": 0.0,
            "sentiment_stocktwits": 0.0,
            "sentiment_finviz": 0.0,
        }
        assert normalizer.composite(candidate) == 0.0

    def test_composite_missing_keys(self, normalizer):
        """Returns 0.0 when candidate has no sentiment keys at all."""
        assert normalizer.composite({"symbol": "AAPL"}) == 0.0


# ------------------------------------------------------------------
# load_source_stats()
# ------------------------------------------------------------------
class TestLoadSourceStats:
    def test_load_source_stats_from_mongo(self, mock_db):
        """Aggregation pipeline result is stored in stats dict."""
        mock_collection = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        mock_collection.aggregate.return_value = [
            {"_id": "alphavantage", "mean": 0.08, "std": 0.22, "count": 150},
            {"_id": "tiingo", "mean": 0.03, "std": 0.14, "count": 90},
        ]

        n = SentimentNormalizer(database=mock_db)
        n.load_source_stats()

        assert "alphavantage" in n.stats
        assert n.stats["alphavantage"]["mean"] == pytest.approx(0.08)
        assert n.stats["alphavantage"]["std"] == pytest.approx(0.22)
        assert n.stats["alphavantage"]["count"] == 150
        assert "tiingo" in n.stats
        assert n.stats["tiingo"]["count"] == 90

    def test_load_source_stats_handles_failure(self, mock_db):
        """Exception is caught; stats remains empty."""
        mock_collection = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        mock_collection.aggregate.side_effect = Exception("connection failed")

        n = SentimentNormalizer(database=mock_db)
        n.load_source_stats()

        assert n.stats == {}

    def test_load_source_stats_handles_none_values(self, mock_db):
        """None mean/std from aggregation default to 0.0."""
        mock_collection = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        mock_collection.aggregate.return_value = [
            {"_id": "stocktwits", "mean": None, "std": None, "count": 40},
        ]

        n = SentimentNormalizer(database=mock_db)
        n.load_source_stats()

        assert n.stats["stocktwits"]["mean"] == 0.0
        assert n.stats["stocktwits"]["std"] == 0.0


# ------------------------------------------------------------------
# Constructor validation
# ------------------------------------------------------------------
class TestConstructor:
    def test_normalizer_requires_database(self):
        """ValueError when database is None."""
        with pytest.raises(ValueError, match="requires a database"):
            SentimentNormalizer(database=None)
