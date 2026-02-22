"""Tests for paper trading module — all mocked, no live gateway needed."""
import csv
import os
from unittest.mock import MagicMock, patch

import pytest

from bluehorseshoe.trading.paper_trader import (
    OrderResult,
    PaperTradeConfig,
    PaperTrader,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_candidate(
    symbol="AAPL",
    strategy="Baseline",
    close=50.0,
    stop_loss=47.5,
    target=55.0,
    score=8.0,
    ml_prob=0.7,
):
    return {
        "symbol": symbol,
        "strategy": strategy,
        "close": close,
        "stop_loss": stop_loss,
        "target": target,
        "score": score,
        "ml_prob": ml_prob,
    }


def _make_trader(tmp_path, db=None, client=None):
    """Create a PaperTrader with mocked client and optional mock db."""
    if client is None:
        client = MagicMock(spec=["place_bracket_order"])
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3],
            "status": "submitted",
            "error": None,
        }
    config = PaperTradeConfig(
        total_investment=10000.0,
        max_positions=10,
        logs_path=str(tmp_path),
    )
    return PaperTrader(ibkr_client=client, config=config, database=db)


# ── Position sizing ──────────────────────────────────────────────────

class TestPositionSizing:
    def test_basic_sizing(self, tmp_path):
        """$10k / 10 positions / $50 stock = 20 shares split into T1(10) + T2(10)."""
        client = MagicMock()
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3], "status": "submitted", "error": None,
        }
        trader = _make_trader(tmp_path, client=client)
        results = trader.execute([_make_candidate(close=50.0)], "2026-01-15")

        assert len(results) == 1
        assert results[0].quantity == 20
        # Split orders: 2 calls (T1 half + T2 half)
        assert client.place_bracket_order.call_count == 2
        # T1 call: 10 shares at entry*1.02
        t1_call = client.place_bracket_order.call_args_list[0]
        assert t1_call.kwargs["quantity"] == 10
        assert t1_call.kwargs["take_profit_price"] == 50.0 * 1.02
        # T2 call: 10 shares at original target
        t2_call = client.place_bracket_order.call_args_list[1]
        assert t2_call.kwargs["quantity"] == 10
        assert t2_call.kwargs["take_profit_price"] == 55.0

    def test_fractional_shares_floored(self, tmp_path):
        """$1000 per position / $33 stock = floor(30.30) = 30 shares split."""
        client = MagicMock()
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3], "status": "submitted", "error": None,
        }
        trader = _make_trader(tmp_path, client=client)
        results = trader.execute(
            [_make_candidate(close=33.0, stop_loss=31.0, target=36.0)],
            "2026-01-15",
        )

        assert results[0].quantity == 30

    def test_skip_if_too_expensive(self, tmp_path):
        """If stock costs more than per-position budget, skip."""
        trader = _make_trader(tmp_path)
        results = trader.execute(
            [_make_candidate(close=2000.0, stop_loss=1900.0, target=2100.0)],
            "2026-01-15",
        )

        assert results[0].status == "skipped"
        assert results[0].error == "insufficient capital for 1 share"


# ── Price validation ─────────────────────────────────────────────────

class TestPriceValidation:
    def test_valid_prices(self):
        assert PaperTrader._validate_prices(50.0, 47.5, 55.0) is True

    def test_zero_entry(self):
        assert PaperTrader._validate_prices(0, 47.5, 55.0) is False

    def test_negative_stop(self):
        assert PaperTrader._validate_prices(50.0, -1.0, 55.0) is False

    def test_take_profit_below_entry(self):
        """take_profit must be above entry."""
        assert PaperTrader._validate_prices(50.0, 47.5, 49.0) is False

    def test_take_profit_equal_entry(self):
        assert PaperTrader._validate_prices(50.0, 47.5, 50.0) is False

    def test_stop_loss_above_entry(self):
        """stop_loss must be below entry."""
        assert PaperTrader._validate_prices(50.0, 51.0, 55.0) is False

    def test_stop_loss_equal_entry(self):
        assert PaperTrader._validate_prices(50.0, 50.0, 55.0) is False

    def test_skips_invalid_candidate(self, tmp_path):
        """Candidate with take_profit <= entry is skipped."""
        trader = _make_trader(tmp_path)
        results = trader.execute(
            [_make_candidate(close=50.0, target=49.0)], "2026-01-15"
        )
        assert results[0].status == "skipped"
        assert results[0].error == "invalid prices"


# ── Duplicate detection ──────────────────────────────────────────────

class TestDuplicateDetection:
    def test_duplicate_skipped(self, tmp_path):
        """If MongoDB already has this symbol/date/strategy, skip."""
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        mock_collection.find_one.return_value = {"symbol": "AAPL"}  # exists

        trader = _make_trader(tmp_path, db=mock_db)
        results = trader.execute([_make_candidate()], "2026-01-15")

        assert results[0].status == "skipped"
        assert results[0].error == "duplicate"

    def test_no_duplicate_proceeds(self, tmp_path):
        """If MongoDB has no match, order proceeds."""
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        mock_collection.find_one.return_value = None  # not found

        client = MagicMock()
        client.place_bracket_order.return_value = {
            "order_ids": [10, 11, 12], "status": "submitted", "error": None,
        }
        trader = _make_trader(tmp_path, db=mock_db, client=client)
        results = trader.execute([_make_candidate()], "2026-01-15")

        assert results[0].status == "submitted"

    def test_no_db_means_no_duplicate_check(self, tmp_path):
        """Without a database, duplicate check is skipped."""
        trader = _make_trader(tmp_path, db=None)
        results = trader.execute([_make_candidate()], "2026-01-15")

        assert results[0].status == "submitted"


# ── Bracket order submission ─────────────────────────────────────────

class TestBracketSubmission:
    def test_order_ids_stored(self, tmp_path):
        client = MagicMock()
        client.place_bracket_order.return_value = {
            "order_ids": [100, 101, 102], "status": "submitted", "error": None,
        }
        trader = _make_trader(tmp_path, client=client)
        results = trader.execute([_make_candidate()], "2026-01-15")

        # Split orders: T1 + T2 both return [100, 101, 102]
        assert results[0].order_ids == [100, 101, 102, 100, 101, 102]
        assert results[0].status == "submitted"

    def test_order_error_captured(self, tmp_path):
        client = MagicMock()
        client.place_bracket_order.return_value = {
            "order_ids": [], "status": "error", "error": "Connection refused",
        }
        trader = _make_trader(tmp_path, client=client)
        results = trader.execute([_make_candidate()], "2026-01-15")

        assert results[0].status == "error"
        assert "Connection refused" in results[0].error


# ── CSV logging ──────────────────────────────────────────────────────

class TestCSVLogging:
    def test_csv_created_with_header(self, tmp_path):
        trader = _make_trader(tmp_path)
        trader.execute([_make_candidate()], "2026-01-15")

        csv_path = tmp_path / "paper_trades_2026-01-15.csv"
        assert csv_path.exists()

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Header + 1 data row
        assert len(rows) == 2
        assert rows[0][0] == "timestamp"
        assert rows[0][1] == "symbol"
        assert rows[1][1] == "AAPL"

    def test_csv_appends_on_second_run(self, tmp_path):
        trader = _make_trader(tmp_path)
        trader.execute([_make_candidate(symbol="AAPL")], "2026-01-15")
        trader.execute([_make_candidate(symbol="MSFT")], "2026-01-15")

        csv_path = tmp_path / "paper_trades_2026-01-15.csv"
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Header + 2 data rows
        assert len(rows) == 3


# ── MongoDB logging ──────────────────────────────────────────────────

class TestMongoLogging:
    def test_upsert_called(self, tmp_path):
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        mock_collection.find_one.return_value = None

        client = MagicMock()
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3], "status": "submitted", "error": None,
        }
        trader = _make_trader(tmp_path, db=mock_db, client=client)
        trader.execute([_make_candidate()], "2026-01-15")

        mock_collection.update_one.assert_called_once()
        call_args = mock_collection.update_one.call_args
        assert call_args[0][0] == {
            "symbol": "AAPL", "date": "2026-01-15", "strategy": "Baseline",
        }
        assert call_args[1]["upsert"] is True

    def test_no_db_skips_mongo_log(self, tmp_path):
        """Without database, MongoDB logging is silently skipped."""
        trader = _make_trader(tmp_path, db=None)
        # Should not raise
        trader.execute([_make_candidate()], "2026-01-15")


# ── End-to-end execute() ─────────────────────────────────────────────

class TestExecuteEndToEnd:
    def test_max_positions_respected(self, tmp_path):
        """15 candidates with max_positions=10 → only 10 processed."""
        client = MagicMock()
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3], "status": "submitted", "error": None,
        }
        config = PaperTradeConfig(
            total_investment=10000.0,
            max_positions=10,
            logs_path=str(tmp_path),
        )
        trader = PaperTrader(ibkr_client=client, config=config)

        candidates = [
            _make_candidate(symbol=f"SYM{i}", close=50.0)
            for i in range(15)
        ]
        results = trader.execute(candidates, "2026-01-15")

        assert len(results) == 10
        # Split orders: 2 calls per position = 20
        assert client.place_bracket_order.call_count == 20

    def test_mixed_results(self, tmp_path):
        """Mix of valid, invalid-price, and error candidates."""
        client = MagicMock()
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3], "status": "submitted", "error": None,
        }
        trader = _make_trader(tmp_path, client=client)

        candidates = [
            _make_candidate(symbol="GOOD", close=50.0, stop_loss=47.5, target=55.0),
            _make_candidate(symbol="BAD", close=50.0, stop_loss=47.5, target=49.0),  # invalid
            _make_candidate(symbol="ALSO_GOOD", close=100.0, stop_loss=95.0, target=110.0),
        ]
        results = trader.execute(candidates, "2026-01-15")

        assert len(results) == 3
        assert results[0].status == "submitted"
        assert results[1].status == "skipped"
        assert results[2].status == "submitted"
        # Split orders: 2 calls per valid position = 4
        assert client.place_bracket_order.call_count == 4


# ── Graceful failure ─────────────────────────────────────────────────

class TestGracefulFailure:
    def test_connection_refused_returns_error(self, tmp_path):
        """If IBKR is down, order comes back with status=error."""
        client = MagicMock()
        client.place_bracket_order.return_value = {
            "order_ids": [], "status": "error", "error": "Connection refused",
        }
        trader = _make_trader(tmp_path, client=client)
        results = trader.execute([_make_candidate()], "2026-01-15")

        assert results[0].status == "error"
        assert "Connection refused" in results[0].error
