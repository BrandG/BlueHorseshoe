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
    strategy="DeepOS",  # a live (paper_tradeable) sleeve; Baseline is now tracking-only
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


def _make_trader(tmp_path, db=None, client=None, fractional_shares=False):
    """Create a PaperTrader with mocked client and optional mock db.

    Default mock client = healthy broker with nothing on the book. Tests
    that need a non-empty book or a wedged gateway pass their own client.

    fractional_shares defaults False here so the whole-share sizing tests below
    (floor math, single-share fallback) stay valid as the whole-share regression
    suite. Production defaults True; fractional sizing is covered in
    TestFractionalSizing.
    """
    if client is None:
        client = MagicMock(spec=[
            "place_bracket_order",
            "get_account_summary",
            "get_positions",
            "get_open_trades",
        ])
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3],
            "status": "submitted",
            "error": None,
        }
    # If the caller passed a spec-less or partial MagicMock, give it sensible
    # defaults for the occupancy-check methods so existing tests don't have
    # to know about the new behavior. Tests that *want* to assert occupancy
    # configure these explicitly.
    _ensure_broker_defaults(client)
    config = PaperTradeConfig(
        total_investment=10000.0,
        max_positions=10,
        logs_path=str(tmp_path),
        fractional_shares=fractional_shares,
    )
    return PaperTrader(ibkr_client=client, config=config, database=db)


def _ensure_broker_defaults(client):
    """Default the occupancy-check reads to 'healthy broker, empty book',
    but ONLY for methods the caller hasn't already configured. Tests that
    set their own return_value (e.g. an open position) keep it.
    """
    defaults = {
        "get_account_summary": {"account_id": "PAPER1"},
        "get_positions": [],
        "get_open_trades": [],
    }
    for method_name, default in defaults.items():
        try:
            method = getattr(client, method_name)
        except AttributeError:
            continue  # spec-restricted mock without this method
        # An unconfigured MagicMock returns a MagicMock from .return_value.
        # Only override when nothing real has been set.
        if isinstance(method.return_value, MagicMock):
            method.return_value = default


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
        assert results[0].error == "insufficient capital for minimum order"


class TestFractionalSizing:
    """Fractional shares deploy exact dollars (no whole-share flooring leak)."""

    def test_no_flooring_leak(self, tmp_path):
        """$1000 / $33 = 30.303 shares exactly, split into two ~15.15 legs."""
        client = MagicMock()
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3], "status": "submitted", "error": None,
        }
        trader = _make_trader(tmp_path, client=client, fractional_shares=True)
        results = trader.execute(
            [_make_candidate(close=33.0, stop_loss=31.0, target=36.0)], "2026-01-15",
        )
        r = results[0]
        assert abs(r.quantity - round(1000.0 / 33.0, 4)) < 1e-9   # 30.3030, not floored to 30
        assert abs(r.t1_qty + r.t2_qty - r.quantity) < 1e-9        # halves sum to total
        # fractional qty reaches the broker call
        assert any(abs(c.kwargs["quantity"] - r.t1_qty) < 1e-9
                   for c in client.place_bracket_order.call_args_list)

    def test_pricey_name_now_tradeable(self, tmp_path):
        """A $2000 name that floored to 0 whole shares trades fractionally ($1000 → 0.5 sh)."""
        client = MagicMock()
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3], "status": "submitted", "error": None,
        }
        trader = _make_trader(tmp_path, client=client, fractional_shares=True)
        results = trader.execute(
            [_make_candidate(close=2000.0, stop_loss=1900.0, target=2100.0)], "2026-01-15",
        )
        r = results[0]
        assert r.status == "submitted"
        assert abs(r.quantity - 0.5) < 1e-9

    def test_below_min_order_value_skipped(self, tmp_path):
        """Notional below min_order_value is skipped (not a degenerate dust order)."""
        client = MagicMock()
        config = PaperTradeConfig(
            total_investment=5.0, max_positions=10, logs_path=str(tmp_path),
            fractional_shares=True, min_order_value=1.0,
        )  # $0.50/position → below $1 min
        trader = PaperTrader(ibkr_client=client, config=config)
        results = trader.execute([_make_candidate(close=50.0)], "2026-01-15")
        assert results[0].status == "skipped"
        assert results[0].error == "insufficient capital for minimum order"


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
            "symbol": "AAPL", "date": "2026-01-15", "strategy": "DeepOS",
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
        """15 candidates with max_positions=10 and empty broker → only 10 processed."""
        client = MagicMock()
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3], "status": "submitted", "error": None,
        }
        _ensure_broker_defaults(client)
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


# ── Occupancy-aware sizing (cap = "have at most", not "submit this many") ──

class TestOccupancyAwareSizing:
    """The double-deploy bug: PaperTrader used to submit N brackets every run
    regardless of what was already working on the broker. Across days this
    stacked unboundedly. Cap is now 'have at most N on the book at once.'"""

    @staticmethod
    def _trade(symbol, action="BUY"):
        """A minimal stand-in for an ib_async Trade: just the attrs we read."""
        t = MagicMock()
        t.contract.symbol = symbol
        t.order.action = action
        return t

    def test_skips_candidate_already_in_open_positions(self, tmp_path):
        """If AAPL is already in get_positions(), the AAPL candidate is dropped
        and we don't pile T1+T2 onto it."""
        client = MagicMock(spec=[
            "place_bracket_order", "get_account_summary",
            "get_positions", "get_open_trades",
        ])
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3], "status": "submitted", "error": None,
        }
        client.get_account_summary.return_value = {"account_id": "PAPER1"}
        client.get_positions.return_value = [
            {"symbol": "AAPL", "position": 10, "avg_cost": 150.0},
        ]
        client.get_open_trades.return_value = []
        trader = _make_trader(tmp_path, client=client)

        results = trader.execute(
            [_make_candidate(symbol="AAPL"), _make_candidate(symbol="MSFT")],
            "2026-01-15",
        )
        symbols_submitted = {r.symbol for r in results if r.status == "submitted"}
        assert "MSFT" in symbols_submitted
        assert "AAPL" not in symbols_submitted
        # MSFT split-bracket = 2 place_bracket_order calls, no AAPL calls
        assert client.place_bracket_order.call_count == 2

    def test_skips_candidate_with_working_buy_entry(self, tmp_path):
        """If a BUY LMT is working for AAPL (entry not yet filled), the AAPL
        candidate is dropped — the slot is already reserved."""
        client = MagicMock(spec=[
            "place_bracket_order", "get_account_summary",
            "get_positions", "get_open_trades",
        ])
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3], "status": "submitted", "error": None,
        }
        client.get_account_summary.return_value = {"account_id": "PAPER1"}
        client.get_positions.return_value = []
        client.get_open_trades.return_value = [
            self._trade("AAPL", action="BUY"),
        ]
        trader = _make_trader(tmp_path, client=client)

        results = trader.execute(
            [_make_candidate(symbol="AAPL"), _make_candidate(symbol="MSFT")],
            "2026-01-15",
        )
        symbols_submitted = {r.symbol for r in results if r.status == "submitted"}
        assert symbols_submitted == {"MSFT"}

    def test_sell_legs_alone_do_not_occupy_a_slot(self, tmp_path):
        """SELL legs are bracket exits, tied to existing positions. They
        shouldn't double-count vs. get_positions(). If AAPL has SELL legs
        working but no open position, the symbol is free."""
        client = MagicMock(spec=[
            "place_bracket_order", "get_account_summary",
            "get_positions", "get_open_trades",
        ])
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3], "status": "submitted", "error": None,
        }
        client.get_account_summary.return_value = {"account_id": "PAPER1"}
        client.get_positions.return_value = []
        client.get_open_trades.return_value = [
            self._trade("AAPL", action="SELL"),
        ]
        trader = _make_trader(tmp_path, client=client)
        results = trader.execute([_make_candidate(symbol="AAPL")], "2026-01-15")
        assert results[0].status == "submitted"

    def test_caps_to_remaining_slots(self, tmp_path):
        """7 already on the book + max_positions=10 → only top 3 candidates
        get submitted, even if 10 candidates are eligible."""
        client = MagicMock(spec=[
            "place_bracket_order", "get_account_summary",
            "get_positions", "get_open_trades",
        ])
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3], "status": "submitted", "error": None,
        }
        client.get_account_summary.return_value = {"account_id": "PAPER1"}
        client.get_positions.return_value = [
            {"symbol": f"HELD{i}", "position": 1, "avg_cost": 50.0} for i in range(7)
        ]
        client.get_open_trades.return_value = []
        trader = _make_trader(tmp_path, client=client)
        # 10 fresh candidates, none overlap with HELD*
        candidates = [_make_candidate(symbol=f"NEW{i}") for i in range(10)]
        results = trader.execute(candidates, "2026-01-15")

        # 10 - 7 = 3 slots available
        assert len(results) == 3
        assert client.place_bracket_order.call_count == 6  # 3 × split bracket

    def test_full_book_submits_nothing(self, tmp_path):
        """10 on the book + max_positions=10 → 0 candidates submitted."""
        client = MagicMock(spec=[
            "place_bracket_order", "get_account_summary",
            "get_positions", "get_open_trades",
        ])
        client.get_account_summary.return_value = {"account_id": "PAPER1"}
        client.get_positions.return_value = [
            {"symbol": f"HELD{i}", "position": 1, "avg_cost": 50.0} for i in range(10)
        ]
        client.get_open_trades.return_value = []
        trader = _make_trader(tmp_path, client=client)
        results = trader.execute(
            [_make_candidate(symbol=f"NEW{i}") for i in range(5)],
            "2026-01-15",
        )
        assert results == []
        client.place_bracket_order.assert_not_called()

    def test_unreachable_broker_skips_all(self, tmp_path):
        """Blank account_id signals the gateway didn't answer. Fail closed
        rather than size off an empty assumption."""
        client = MagicMock(spec=[
            "place_bracket_order", "get_account_summary",
            "get_positions", "get_open_trades",
        ])
        client.get_account_summary.return_value = {"account_id": ""}
        trader = _make_trader(tmp_path, client=client)
        results = trader.execute(
            [_make_candidate(symbol=f"NEW{i}") for i in range(5)],
            "2026-01-15",
        )
        assert results == []
        client.place_bracket_order.assert_not_called()


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


# ── Trade Orders (Phase 2) ──────────────────────────────────────────

class TestTradeOrderLogging:
    """Tests for normalized trade_orders documents linked to trade_ideas."""

    def _make_db_with_orders_collection(self):
        """Create mock DB that tracks separate collections."""
        db = MagicMock()
        paper_col = MagicMock()
        orders_col = MagicMock()
        collections = {
            "paper_trades": paper_col,
            "trade_orders": orders_col,
        }
        db.__getitem__ = MagicMock(side_effect=lambda name: collections[name])
        return db, paper_col, orders_col

    def test_trade_orders_written_for_submitted(self, tmp_path):
        """Submitted orders with idea_id should write T1 and T2 trade_orders docs."""
        db, paper_col, orders_col = self._make_db_with_orders_collection()
        # Ensure duplicate check passes (no existing order)
        paper_col.find_one.return_value = None
        client = MagicMock()
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3], "status": "submitted", "error": None,
        }
        config = PaperTradeConfig(
            total_investment=10000.0, max_positions=10, logs_path=str(tmp_path),
        )
        trader = PaperTrader(ibkr_client=client, config=config, database=db)

        idea_lookup = {("AAPL", "DeepOS"): "idea_2026-03-22_AAPL_baseline"}
        results = trader.execute(
            [_make_candidate(close=50.0)], "2026-03-22", idea_lookup=idea_lookup,
        )

        assert results[0].idea_id == "idea_2026-03-22_AAPL_baseline"
        # Should write 2 order docs: T1 + T2
        assert orders_col.update_one.call_count == 2

        # Check T1 doc
        t1_call = orders_col.update_one.call_args_list[0]
        t1_filter = t1_call[0][0]
        t1_doc = t1_call[0][1]["$set"]
        assert t1_filter == {"order_ref": "order_idea_2026-03-22_AAPL_baseline_T1"}
        assert t1_doc["leg"] == "T1"
        assert t1_doc["idea_id"] == "idea_2026-03-22_AAPL_baseline"
        assert t1_doc["symbol"] == "AAPL"
        assert t1_doc["quantity"] == 10  # 20 total / 2

        # Check T2 doc
        t2_call = orders_col.update_one.call_args_list[1]
        t2_doc = t2_call[0][1]["$set"]
        assert t2_doc["leg"] == "T2"
        assert t2_doc["quantity"] == 10

    def test_no_trade_orders_without_idea_id(self, tmp_path):
        """Orders without idea_id should not write trade_orders."""
        db, paper_col, orders_col = self._make_db_with_orders_collection()
        paper_col.find_one.return_value = None
        client = MagicMock()
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3], "status": "submitted", "error": None,
        }
        config = PaperTradeConfig(
            total_investment=10000.0, max_positions=10, logs_path=str(tmp_path),
        )
        trader = PaperTrader(ibkr_client=client, config=config, database=db)

        # No idea_lookup → no idea_id
        results = trader.execute([_make_candidate(close=50.0)], "2026-03-22")
        assert results[0].idea_id is None
        assert orders_col.update_one.call_count == 0

    def test_skipped_orders_no_trade_orders(self, tmp_path):
        """Skipped orders should not write trade_orders even with idea_id."""
        db, _, orders_col = self._make_db_with_orders_collection()
        client = MagicMock()
        config = PaperTradeConfig(
            total_investment=10000.0, max_positions=10, logs_path=str(tmp_path),
        )
        trader = PaperTrader(ibkr_client=client, config=config, database=db)

        # Invalid prices → skipped
        idea_lookup = {("AAPL", "DeepOS"): "idea_2026-03-22_AAPL_baseline"}
        results = trader.execute(
            [_make_candidate(close=50.0, stop_loss=47.5, target=49.0)],  # invalid: target < entry
            "2026-03-22", idea_lookup=idea_lookup,
        )
        assert results[0].status == "skipped"
        assert orders_col.update_one.call_count == 0

    def test_per_leg_order_ids_tracked(self, tmp_path):
        """T1 and T2 order_ids should be tracked separately on OrderResult."""
        client = MagicMock()
        call_count = [0]
        def bracket_side_effect(**kwargs):
            call_count[0] += 1
            return {
                "order_ids": [call_count[0] * 10 + 1, call_count[0] * 10 + 2, call_count[0] * 10 + 3],
                "status": "submitted", "error": None,
            }
        client.place_bracket_order.side_effect = bracket_side_effect

        trader = _make_trader(tmp_path, client=client)
        results = trader.execute([_make_candidate(close=50.0)], "2026-03-22")

        r = results[0]
        assert r.t1_order_ids == [11, 12, 13]
        assert r.t2_order_ids == [21, 22, 23]
        assert r.order_ids == [11, 12, 13, 21, 22, 23]  # Combined for backward compat
        assert r.t1_qty == 10
        assert r.t2_qty == 10

    def test_single_share_only_t2(self, tmp_path):
        """With only 1 share, only T2 order is placed."""
        client = MagicMock()
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3], "status": "submitted", "error": None,
        }
        config = PaperTradeConfig(
            total_investment=600.0, max_positions=10, logs_path=str(tmp_path),
            fractional_shares=False,  # whole-share single-share fallback under test
        )
        trader = PaperTrader(ibkr_client=client, config=config)
        # $600 / 10 = $60 per position, floor(60/50) = 1 share
        results = trader.execute([_make_candidate(close=50.0)], "2026-03-22")

        r = results[0]
        assert r.quantity == 1
        assert r.t1_order_ids == []
        assert r.t2_order_ids == [1, 2, 3]
        assert r.t2_qty == 1

    def test_backward_compat_no_idea_lookup(self, tmp_path):
        """Calling execute() without idea_lookup should work identically to before."""
        client = MagicMock()
        client.place_bracket_order.return_value = {
            "order_ids": [1, 2, 3], "status": "submitted", "error": None,
        }
        trader = _make_trader(tmp_path, client=client)
        results = trader.execute([_make_candidate(close=50.0)], "2026-03-22")

        assert len(results) == 1
        assert results[0].status == "submitted"
        assert results[0].idea_id is None
