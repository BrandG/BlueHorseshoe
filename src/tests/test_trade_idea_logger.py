"""Tests for the trade idea logger."""
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime

from bluehorseshoe.trading.trade_idea_logger import TradeIdeaLogger


def _make_candidate(symbol="AAPL", strategy="Baseline", score=15.0,
                    entry=150.0, stop=145.0, target=160.0, ml_prob=0.65):
    """Helper to build a candidate dict matching swing_predict() output."""
    return {
        "symbol": symbol,
        "strategy": strategy,
        "score": score,
        "close": entry,
        "stop_loss": stop,
        "t1_target": entry * 1.02,
        "target": target,
        "ml_prob": ml_prob,
        "sentiment": 0.1,
        "sentiment_composite": 0.15,
        "reasons": ["ADX=8.5", "RSI=5.0", "MACD=3.0"],
    }


@pytest.fixture
def mock_db():
    """Create a mock MongoDB database."""
    db = MagicMock()
    collection = MagicMock()
    db.__getitem__ = MagicMock(return_value=collection)
    return db


@pytest.fixture
def logger(mock_db):
    """Create a TradeIdeaLogger with mocked database."""
    return TradeIdeaLogger(database=mock_db)


class TestLogIdeas:
    def test_logs_top_n_candidates(self, logger, mock_db):
        candidates = [
            _make_candidate("AAPL", score=20.0),
            _make_candidate("MSFT", score=18.0),
            _make_candidate("GOOG", score=15.0),
        ]
        count, lookup = logger.log_ideas(candidates, "2026-03-22", max_positions=2)

        assert count == 2
        assert len(lookup) == 2
        assert ("AAPL", "Baseline") in lookup
        assert ("MSFT", "Baseline") in lookup
        assert ("GOOG", "Baseline") not in lookup

    def test_idea_id_format(self, logger, mock_db):
        candidates = [_make_candidate("SHEL", strategy="MeanRev")]
        _, lookup = logger.log_ideas(candidates, "2026-03-22", max_positions=10)

        assert lookup[("SHEL", "MeanRev")] == "idea_2026-03-22_SHEL_mean_reversion"

    def test_position_sizing(self, logger, mock_db):
        candidates = [_make_candidate("AAPL", entry=100.0)]
        logger.log_ideas(
            candidates, "2026-03-22",
            max_positions=5, total_investment=5000.0,
        )

        # per_position = 5000 / 5 = 1000, shares = floor(1000 / 100) = 10
        collection = mock_db.__getitem__.return_value
        call_args = collection.update_one.call_args
        doc = call_args[0][1]["$set"]
        assert doc["position_size_shares"] == 10
        assert doc["position_size_dollars"] == 1000.0

    def test_components_parsed_from_reasons(self, logger, mock_db):
        candidates = [_make_candidate()]
        logger.log_ideas(candidates, "2026-03-22", max_positions=10)

        collection = mock_db.__getitem__.return_value
        call_args = collection.update_one.call_args
        doc = call_args[0][1]["$set"]
        assert doc["components"] == {"ADX": 8.5, "RSI": 5.0, "MACD": 3.0}

    def test_strategy_normalized(self, logger, mock_db):
        candidates = [_make_candidate(strategy="Baseline")]
        logger.log_ideas(candidates, "2026-03-22", max_positions=10)

        collection = mock_db.__getitem__.return_value
        call_args = collection.update_one.call_args
        doc = call_args[0][1]["$set"]
        assert doc["strategy"] == "baseline"

    def test_risk_reward_calculated(self, logger, mock_db):
        candidates = [_make_candidate(entry=100.0, stop=95.0, target=110.0)]
        logger.log_ideas(candidates, "2026-03-22", max_positions=10)

        collection = mock_db.__getitem__.return_value
        call_args = collection.update_one.call_args
        doc = call_args[0][1]["$set"]
        # risk = 100 - 95 = 5, reward = 110 - 100 = 10, rr = 2.0
        assert doc["risk_reward_ratio"] == 2.0

    def test_empty_candidates_returns_zero(self, logger):
        count, lookup = logger.log_ideas([], "2026-03-22")
        assert count == 0
        assert lookup == {}

    def test_skips_invalid_entry_price(self, logger, mock_db):
        candidates = [_make_candidate(entry=0.0)]
        count, lookup = logger.log_ideas(candidates, "2026-03-22", max_positions=10)
        assert count == 0

    def test_skips_missing_symbol(self, logger, mock_db):
        candidates = [{"strategy": "Baseline", "score": 10.0, "close": 100.0}]
        count, lookup = logger.log_ideas(candidates, "2026-03-22", max_positions=10)
        assert count == 0

    def test_upsert_on_duplicate(self, logger, mock_db):
        """Verify update_one uses upsert=True."""
        candidates = [_make_candidate()]
        logger.log_ideas(candidates, "2026-03-22", max_positions=10)

        collection = mock_db.__getitem__.return_value
        call_args = collection.update_one.call_args
        assert call_args[1].get("upsert") is True or call_args[0][2] is True

    def test_rank_assigned_sequentially(self, logger, mock_db):
        candidates = [
            _make_candidate("AAPL", score=20.0),
            _make_candidate("MSFT", score=18.0),
        ]
        logger.log_ideas(candidates, "2026-03-22", max_positions=10)

        collection = mock_db.__getitem__.return_value
        calls = collection.update_one.call_args_list
        assert calls[0][0][1]["$set"]["rank"] == 1
        assert calls[1][0][1]["$set"]["rank"] == 2

    def test_database_error_nonfatal(self, logger, mock_db):
        """Database errors should not raise, just log and continue."""
        collection = mock_db.__getitem__.return_value
        collection.update_one.side_effect = Exception("DB error")

        candidates = [_make_candidate()]
        count, lookup = logger.log_ideas(candidates, "2026-03-22", max_positions=10)
        assert count == 0

    def test_signal_strength_inference(self, logger, mock_db):
        candidates = [
            _make_candidate("HIGH_SCORE", score=20.0),
            _make_candidate("MED_SCORE", score=10.0),
            _make_candidate("LOW_SCORE", score=3.0),
        ]
        logger.log_ideas(candidates, "2026-03-22", max_positions=10)

        collection = mock_db.__getitem__.return_value
        calls = collection.update_one.call_args_list
        assert calls[0][0][1]["$set"]["signal_strength"] == "HIGH"
        assert calls[1][0][1]["$set"]["signal_strength"] == "MEDIUM"
        assert calls[2][0][1]["$set"]["signal_strength"] == "LOW"

    def test_sentiment_composite_preferred(self, logger, mock_db):
        """sentiment_composite should be used over sentiment when available."""
        cand = _make_candidate()
        cand["sentiment"] = 0.1
        cand["sentiment_composite"] = 0.5
        logger.log_ideas([cand], "2026-03-22", max_positions=10)

        collection = mock_db.__getitem__.return_value
        doc = collection.update_one.call_args[0][1]["$set"]
        assert doc["sentiment"] == 0.5


class TestGetIdeas:
    def test_get_ideas(self, logger, mock_db):
        collection = mock_db.__getitem__.return_value
        collection.find.return_value.sort.return_value = [
            {"idea_id": "idea_1", "rank": 1},
            {"idea_id": "idea_2", "rank": 2},
        ]
        result = logger.get_ideas("2026-03-22")
        assert len(result) == 2
        collection.find.assert_called_once_with(
            {"batch_date": "2026-03-22"}, {"_id": 0}
        )

    def test_get_idea(self, logger, mock_db):
        collection = mock_db.__getitem__.return_value
        collection.find_one.return_value = {"idea_id": "idea_1"}
        result = logger.get_idea("idea_1")
        assert result["idea_id"] == "idea_1"

    def test_get_idea_not_found(self, logger, mock_db):
        collection = mock_db.__getitem__.return_value
        collection.find_one.return_value = None
        result = logger.get_idea("nonexistent")
        assert result is None


class TestSignalStrength:
    def test_high(self):
        assert TradeIdeaLogger._infer_signal_strength(15.0) == "HIGH"
        assert TradeIdeaLogger._infer_signal_strength(25.0) == "HIGH"

    def test_medium(self):
        assert TradeIdeaLogger._infer_signal_strength(8.0) == "MEDIUM"
        assert TradeIdeaLogger._infer_signal_strength(14.9) == "MEDIUM"

    def test_low(self):
        assert TradeIdeaLogger._infer_signal_strength(7.9) == "LOW"
        assert TradeIdeaLogger._infer_signal_strength(0.0) == "LOW"
