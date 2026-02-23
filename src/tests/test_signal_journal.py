"""Tests for the immutable Signal Journal (Layer A)."""
import pytest
from unittest.mock import MagicMock, patch
from pymongo.errors import DuplicateKeyError

from bluehorseshoe.core.journal import SignalJournal, ALGORITHM_VERSION


@pytest.fixture
def mock_database():
    """Create a mock database with journal collections."""
    mock_db = MagicMock()
    mock_batches = MagicMock()
    mock_signals = MagicMock()
    mock_db.__getitem__.side_effect = lambda key: {
        "journal_batches": mock_batches,
        "journal_signals": mock_signals,
    }.get(key, MagicMock())
    return mock_db


@pytest.fixture
def journal(mock_database):
    """Create a SignalJournal with mock database."""
    return SignalJournal(database=mock_database)


@pytest.fixture
def sample_valid_results():
    """Minimal valid_results matching _score_symbol_worker output structure."""
    return [
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "exchange": "NASDAQ",
            "date": "2026-02-20",
            "rs_ratio": 1.05,
            "baseline_score": 15.0,
            "baseline_components": {"adx": 5.0, "macd": 3.0, "rsi": 7.0},
            "baseline_setup": {
                "entry_price": 180.50,
                "stop_loss": 175.00,
                "take_profit": 192.00,
                "rr_ratio": 2.09,
                "atr_discount_used": 0.10,
                "signal_strength": "HIGH",
                "is_realistic": True,
                "vol_ratio": 1.2,
            },
            "baseline_ml_prob": 0.72,
            "mr_score": 0.0,
            "mr_components": {},
            "mr_setup": {},
            "mr_ml_prob": 0.0,
            "sentiment": 0.35,
        },
        {
            "symbol": "MSFT",
            "name": "Microsoft Corp.",
            "exchange": "NASDAQ",
            "date": "2026-02-20",
            "rs_ratio": 0.98,
            "baseline_score": 0.0,
            "baseline_components": {},
            "baseline_setup": {},
            "baseline_ml_prob": 0.0,
            "mr_score": 12.5,
            "mr_components": {"rsi": 6.0, "bb": 4.0, "ma_dist": 2.5},
            "mr_setup": {
                "entry_price": 410.00,
                "stop_loss": 400.00,
                "take_profit": 430.00,
                "rr_ratio": 2.0,
                "is_realistic": True,
                "vol_ratio": 0.9,
            },
            "mr_ml_prob": 0.65,
            "sentiment": -0.10,
        },
    ]


@pytest.fixture
def sample_market_health():
    """Sample market regime data."""
    return {
        "status": "Bullish",
        "multiplier": 1.0,
        "details": {
            "SPY": {"close": 500.0, "ema50": 490.0, "ema200": 470.0},
            "QQQ": {"close": 420.0, "ema50": 410.0, "ema200": 390.0},
            "breadth": 0.75,
        },
    }


@pytest.fixture
def paper_settings():
    """Sample paper trading settings."""
    return {
        "paper_trading_enabled": False,
        "paper_total_investment": 10000,
        "paper_max_positions": 10,
    }


class TestFreezeBatch:
    """Test the primary freeze_batch() method."""

    def test_successful_freeze(
        self, journal, mock_database, sample_valid_results,
        sample_market_health, paper_settings,
    ):
        """freeze_batch inserts batch doc and signal docs."""
        result = journal.freeze_batch(
            batch_date="2026-02-20",
            valid_results=sample_valid_results,
            market_health=sample_market_health,
            symbol_count=3000,
            paper_settings=paper_settings,
        )

        assert result is True

        # Batch was inserted
        batches_col = mock_database["journal_batches"]
        batches_col.insert_one.assert_called_once()
        batch_doc = batches_col.insert_one.call_args[0][0]
        assert batch_doc["batch_date"] == "2026-02-20"
        assert batch_doc["algorithm_version"] == ALGORITHM_VERSION
        assert batch_doc["symbol_count"] == 3000
        assert batch_doc["candidate_count"] == 2  # 1 baseline + 1 MR
        assert "weights" in batch_doc["config_snapshot"]
        assert "constants" in batch_doc["config_snapshot"]
        assert "generated_at" in batch_doc

        # Signals were inserted
        signals_col = mock_database["journal_signals"]
        signals_col.insert_many.assert_called_once()
        signal_docs = signals_col.insert_many.call_args[0][0]
        assert len(signal_docs) == 2

    def test_baseline_signal_fields(
        self, journal, mock_database, sample_valid_results,
        sample_market_health, paper_settings,
    ):
        """Baseline signal has all expected fields with correct values."""
        journal.freeze_batch(
            batch_date="2026-02-20",
            valid_results=sample_valid_results,
            market_health=sample_market_health,
            symbol_count=3000,
            paper_settings=paper_settings,
        )

        signals_col = mock_database["journal_signals"]
        signal_docs = signals_col.insert_many.call_args[0][0]
        bl_sig = [d for d in signal_docs if d["strategy"] == "baseline"][0]

        assert bl_sig["symbol"] == "AAPL"
        assert bl_sig["rank"] == 1
        assert bl_sig["composite_score"] == 15.0
        assert bl_sig["ml_win_probability"] == 0.72
        assert bl_sig["signal_strength"] == "HIGH"
        assert bl_sig["entry_price"] == 180.50
        assert bl_sig["stop_loss"] == 175.00
        assert bl_sig["take_profit_t1"] == round(180.50 * 1.02, 4)
        assert bl_sig["take_profit_t2"] == 192.00
        assert bl_sig["risk_reward_ratio"] == 2.09
        assert bl_sig["sentiment"] == 0.35
        assert bl_sig["components"] == {"adx": 5.0, "macd": 3.0, "rsi": 7.0}

    def test_mr_signal_fields(
        self, journal, mock_database, sample_valid_results,
        sample_market_health, paper_settings,
    ):
        """Mean reversion signal has correct strategy-specific values."""
        journal.freeze_batch(
            batch_date="2026-02-20",
            valid_results=sample_valid_results,
            market_health=sample_market_health,
            symbol_count=3000,
            paper_settings=paper_settings,
        )

        signals_col = mock_database["journal_signals"]
        signal_docs = signals_col.insert_many.call_args[0][0]
        mr_sig = [d for d in signal_docs if d["strategy"] == "mean_reversion"][0]

        assert mr_sig["symbol"] == "MSFT"
        assert mr_sig["rank"] == 1
        assert mr_sig["composite_score"] == 12.5
        assert mr_sig["ml_win_probability"] == 0.65
        assert mr_sig["sentiment"] == -0.10
        assert mr_sig["stop_multiplier"] == 1.5  # MR default
        assert mr_sig["target_multiplier"] == 2.0  # MR default

    def test_duplicate_batch_skips(
        self, journal, mock_database, sample_valid_results,
        sample_market_health,
    ):
        """Second call for same date returns False and does not insert signals."""
        batches_col = mock_database["journal_batches"]
        batches_col.insert_one.side_effect = DuplicateKeyError("duplicate key")

        result = journal.freeze_batch(
            batch_date="2026-02-20",
            valid_results=sample_valid_results,
            market_health=sample_market_health,
            symbol_count=3000,
        )

        assert result is False
        signals_col = mock_database["journal_signals"]
        signals_col.insert_many.assert_not_called()

    def test_database_error_non_blocking(
        self, journal, mock_database, sample_valid_results,
        sample_market_health,
    ):
        """Database errors return False but do not raise."""
        batches_col = mock_database["journal_batches"]
        batches_col.insert_one.side_effect = ConnectionError("MongoDB down")

        result = journal.freeze_batch(
            batch_date="2026-02-20",
            valid_results=sample_valid_results,
            market_health=sample_market_health,
            symbol_count=3000,
        )

        assert result is False

    def test_empty_results(self, journal, mock_database, sample_market_health):
        """Empty valid_results creates batch with 0 candidates."""
        result = journal.freeze_batch(
            batch_date="2026-02-20",
            valid_results=[],
            market_health=sample_market_health,
            symbol_count=3000,
        )

        assert result is True
        batches_col = mock_database["journal_batches"]
        batch_doc = batches_col.insert_one.call_args[0][0]
        assert batch_doc["candidate_count"] == 0

        # No signals to insert
        signals_col = mock_database["journal_signals"]
        signals_col.insert_many.assert_not_called()


class TestSignalRanking:
    """Test that signals are correctly ranked within their strategy."""

    def test_baseline_ranking_by_score(self, journal):
        """Baseline signals ranked by score descending."""
        results = [
            {
                "symbol": "A", "date": "2026-02-20",
                "baseline_score": 10.0, "baseline_components": {"x": 1},
                "baseline_setup": {
                    "entry_price": 50, "stop_loss": 48,
                    "take_profit": 55, "rr_ratio": 2.5,
                },
                "baseline_ml_prob": 0.5,
                "mr_score": 0, "mr_components": {},
                "mr_setup": {}, "mr_ml_prob": 0, "sentiment": 0,
            },
            {
                "symbol": "B", "date": "2026-02-20",
                "baseline_score": 20.0, "baseline_components": {"x": 2},
                "baseline_setup": {
                    "entry_price": 100, "stop_loss": 95,
                    "take_profit": 110, "rr_ratio": 2.0,
                },
                "baseline_ml_prob": 0.8,
                "mr_score": 0, "mr_components": {},
                "mr_setup": {}, "mr_ml_prob": 0, "sentiment": 0,
            },
        ]
        docs = journal._build_signal_docs("2026-02-20", results)
        assert docs[0]["symbol"] == "B"  # Higher score ranked first
        assert docs[0]["rank"] == 1
        assert docs[1]["symbol"] == "A"
        assert docs[1]["rank"] == 2

    def test_dual_strategy_symbol(self, journal):
        """A symbol scoring in both strategies produces two signal records."""
        results = [
            {
                "symbol": "TSLA", "date": "2026-02-20",
                "baseline_score": 8.0, "baseline_components": {"x": 1},
                "baseline_setup": {
                    "entry_price": 200, "stop_loss": 190,
                    "take_profit": 220, "rr_ratio": 2.0,
                },
                "baseline_ml_prob": 0.6,
                "mr_score": 5.0, "mr_components": {"y": 1},
                "mr_setup": {
                    "entry_price": 195, "stop_loss": 188,
                    "take_profit": 210, "rr_ratio": 2.14,
                },
                "mr_ml_prob": 0.55, "sentiment": 0.1,
            },
        ]
        docs = journal._build_signal_docs("2026-02-20", results)
        assert len(docs) == 2
        strategies = {d["strategy"] for d in docs}
        assert strategies == {"baseline", "mean_reversion"}


class TestConfigSnapshot:
    """Test configuration snapshotting."""

    def test_snapshot_contains_expected_keys(self):
        """Config snapshot captures weights, constants, and paper settings."""
        snap = SignalJournal._build_config_snapshot(
            {
                "paper_trading_enabled": True,
                "paper_total_investment": 25000,
                "paper_max_positions": 5,
            }
        )
        assert "weights" in snap
        assert "constants" in snap
        assert "paper_settings" in snap
        assert snap["paper_settings"]["paper_total_investment"] == 25000
        assert "MIN_RR_RATIO_BASELINE" in snap["constants"]
        assert "SIGNAL_STRENGTH_THRESHOLDS" in snap["constants"]
        assert "trend" in snap["weights"]
        assert "momentum" in snap["weights"]
        assert "volume" in snap["weights"]


class TestGitCommit:
    """Test git commit capture."""

    @patch("bluehorseshoe.core.journal.subprocess.run")
    def test_git_commit_success(self, mock_run):
        """Successful git rev-parse returns trimmed hash."""
        mock_run.return_value = MagicMock(returncode=0, stdout="abc1234\n")
        assert SignalJournal._get_git_commit() == "abc1234"

    @patch("bluehorseshoe.core.journal.subprocess.run")
    def test_git_commit_failure(self, mock_run):
        """Git failure returns empty string."""
        mock_run.side_effect = FileNotFoundError("git not found")
        assert SignalJournal._get_git_commit() == ""

    @patch("bluehorseshoe.core.journal.subprocess.run")
    def test_git_commit_nonzero_exit(self, mock_run):
        """Non-zero exit code returns empty string."""
        mock_run.return_value = MagicMock(returncode=128, stdout="")
        assert SignalJournal._get_git_commit() == ""


class TestConstructor:
    """Test constructor validation."""

    def test_none_database_raises(self):
        """None database raises ValueError."""
        with pytest.raises(ValueError, match="database parameter is required"):
            SignalJournal(database=None)

    def test_indexes_created(self, mock_database):
        """Constructor creates unique indexes on both collections."""
        journal = SignalJournal(database=mock_database)
        batches_col = mock_database["journal_batches"]
        signals_col = mock_database["journal_signals"]
        batches_col.create_index.assert_called_once()
        signals_col.create_index.assert_called_once()
