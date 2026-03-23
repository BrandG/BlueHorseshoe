"""Tests for the trade reconciler."""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from bluehorseshoe.trading.trade_reconciler import TradeReconciler


class MockCursor:
    """Chainable mock cursor supporting .sort() and iteration."""
    def __init__(self, data=None):
        self._data = data or []

    def sort(self, *args, **kwargs):
        return self

    def __iter__(self):
        return iter(self._data)

    def __list__(self):
        return self._data


def _make_collections():
    """Create mock DB with all journal collections."""
    db = MagicMock()
    ideas_col = MagicMock()
    orders_col = MagicMock()
    fills_col = MagicMock()
    positions_col = MagicMock()
    cols = {
        "trade_ideas": ideas_col,
        "trade_orders": orders_col,
        "trade_fills": fills_col,
        "trade_positions": positions_col,
    }
    db.__getitem__ = MagicMock(side_effect=lambda name: cols[name])
    return db, ideas_col, orders_col, fills_col, positions_col


class TestMatchOrdersToFills:
    def test_matches_by_broker_order_id(self):
        db, ideas_col, orders_col, fills_col, positions_col = _make_collections()

        # Orders have broker_order_ids
        orders_col.find.return_value = [{
            "order_ref": "order_idea_2026-03-22_AAPL_baseline_T1",
            "idea_id": "idea_2026-03-22_AAPL_baseline",
            "broker_order_ids": [101, 102, 103],
            "leg": "T1",
        }]

        matched_fill = {
            "fill_id": "fill_E001",
            "broker_order_id": 101,
            "order_ref": None,
            "idea_id": None,
        }

        # fills_col.find is called multiple times:
        # 1. In _match_orders_to_fills: find by broker_order_id
        # 2. In _match_orphan_fills: find orphans
        # 3. In _build_positions: find by idea_id
        fills_col.find.side_effect = [
            [matched_fill],     # broker order match
            MockCursor([]),     # orphan fills
            MockCursor([]),     # fills for position building
        ]

        fills_col.count_documents.return_value = 0
        ideas_col.find.return_value = []  # No ideas for orphan matching
        ideas_col.distinct.return_value = []

        reconciler = TradeReconciler(database=db)
        result = reconciler.reconcile()

        # Should have updated the fill with order_ref and idea_id
        fills_col.update_one.assert_called()
        update_call = fills_col.update_one.call_args_list[0]
        assert update_call[0][0] == {"fill_id": "fill_E001"}
        update_set = update_call[0][1]["$set"]
        assert update_set["order_ref"] == "order_idea_2026-03-22_AAPL_baseline_T1"
        assert update_set["idea_id"] == "idea_2026-03-22_AAPL_baseline"


class TestMatchOrphanFills:
    def test_matches_by_symbol_and_date(self):
        db, ideas_col, orders_col, fills_col, positions_col = _make_collections()

        # No orders to match
        orders_col.find.return_value = []

        orphan_fill = {"fill_id": "fill_csv_0", "symbol": "AAPL", "side": "buy",
                        "exec_time": datetime(2026, 3, 23, 14, 0),
                        "idea_id": None, "order_ref": None}

        # fills_col.find calls:
        # 1. _match_orders_to_fills: no broker matches (orders empty)
        # 2. _match_orphan_fills: orphan fills
        # 3. _build_positions: fills with idea_id
        fills_col.find.side_effect = [
            MockCursor([orphan_fill]),  # orphan fills
            MockCursor([]),             # fills for position building
        ]

        # Ideas to match against
        ideas_col.find.return_value = [{
            "idea_id": "idea_2026-03-22_AAPL_baseline",
            "symbol": "AAPL",
            "batch_date": "2026-03-22",
        }]
        ideas_col.distinct.return_value = []

        fills_col.count_documents.return_value = 0

        reconciler = TradeReconciler(database=db)
        result = reconciler.reconcile()

        # Should match the orphan fill to the idea
        update_calls = [c for c in fills_col.update_one.call_args_list
                        if c[0][0].get("fill_id") == "fill_csv_0"]
        assert len(update_calls) == 1
        assert update_calls[0][0][1]["$set"]["idea_id"] == "idea_2026-03-22_AAPL_baseline"


class TestBuildPositions:
    def test_creates_position_from_fills(self):
        db, ideas_col, orders_col, fills_col, positions_col = _make_collections()

        orders_col.find.return_value = []  # No orders for matching step

        idea = {
            "idea_id": "idea_2026-03-22_AAPL_baseline",
            "symbol": "AAPL",
            "strategy": "baseline",
            "batch_date": "2026-03-22",
            "entry_price": 150.0,
            "stop_loss": 145.0,
            "take_profit_t1": 153.0,
            "take_profit_t2": 160.0,
        }

        fills = [
            {"fill_id": "f1", "idea_id": "idea_2026-03-22_AAPL_baseline",
             "symbol": "AAPL", "side": "buy", "quantity": 10, "price": 150.10,
             "commission": 1.0, "exec_time": datetime(2026, 3, 23, 14, 0),
             "order_ref": None},
            {"fill_id": "f2", "idea_id": "idea_2026-03-22_AAPL_baseline",
             "symbol": "AAPL", "side": "sell", "quantity": 10, "price": 155.0,
             "commission": 1.0, "exec_time": datetime(2026, 3, 25, 15, 0),
             "order_ref": None},
        ]

        # fills_col.find calls:
        # 1. _match_orphan_fills: no orphans
        # 2. _build_positions: fills with idea_id
        fills_col.find.side_effect = [
            MockCursor([]),      # orphan fills
            MockCursor(fills),   # fills for position building
        ]
        ideas_col.find.return_value = []  # No ideas for orphan matching
        ideas_col.distinct.return_value = []
        ideas_col.find_one.return_value = idea
        orders_col.find.return_value = MockCursor([])
        positions_col.find_one.return_value = None  # No existing position
        fills_col.count_documents.return_value = 0

        reconciler = TradeReconciler(database=db)
        result = reconciler.reconcile()

        # Should have created a position
        pos_call = positions_col.update_one.call_args
        pos_doc = pos_call[0][1]["$set"]
        assert pos_doc["position_id"] == "pos_idea_2026-03-22_AAPL_baseline"
        assert pos_doc["symbol"] == "AAPL"
        assert pos_doc["actual_entry"] == 150.10
        assert pos_doc["status"] == "closed"
        assert len(pos_doc["legs"]) == 1
        assert pos_doc["legs"][0]["pnl"] == 49.0  # (155 - 150.1) * 10
        assert pos_doc["legs"][0]["hold_days"] == 2


class TestInferCloseReason:
    def test_stop_loss(self):
        idea = {"stop_loss": 145.0, "take_profit_t1": 153.0, "take_profit_t2": 160.0}
        assert TradeReconciler._infer_close_reason(145.0, idea) == "stop_loss"

    def test_take_profit_t1(self):
        idea = {"stop_loss": 145.0, "take_profit_t1": 153.0, "take_profit_t2": 160.0}
        assert TradeReconciler._infer_close_reason(153.0, idea, "T1") == "take_profit_t1"

    def test_take_profit_t2(self):
        idea = {"stop_loss": 145.0, "take_profit_t1": 153.0, "take_profit_t2": 160.0}
        assert TradeReconciler._infer_close_reason(160.0, idea) == "take_profit_t2"

    def test_manual(self):
        idea = {"stop_loss": 145.0, "take_profit_t1": 153.0, "take_profit_t2": 160.0}
        assert TradeReconciler._infer_close_reason(152.0, idea) == "manual"


class TestCalcHoldDays:
    def test_normal(self):
        entry = [{"exec_time": datetime(2026, 3, 22, 14, 0)}]
        exit_ = [{"exec_time": datetime(2026, 3, 25, 15, 0)}]
        assert TradeReconciler._calc_hold_days(entry, exit_) == 3

    def test_same_day(self):
        entry = [{"exec_time": datetime(2026, 3, 22, 14, 0)}]
        exit_ = [{"exec_time": datetime(2026, 3, 22, 15, 0)}]
        assert TradeReconciler._calc_hold_days(entry, exit_) == 0

    def test_no_fills(self):
        assert TradeReconciler._calc_hold_days([], []) == 0

    def test_missing_exec_time(self):
        entry = [{"exec_time": None}]
        exit_ = [{"exec_time": datetime(2026, 3, 25)}]
        assert TradeReconciler._calc_hold_days(entry, exit_) == 0


class TestQueryMethods:
    def test_get_position(self):
        db, _, _, _, positions_col = _make_collections()
        positions_col.find_one.return_value = {"position_id": "pos_1"}
        reconciler = TradeReconciler(database=db)
        result = reconciler.get_position("pos_1")
        assert result["position_id"] == "pos_1"

    def test_get_open_positions(self):
        db, _, _, _, positions_col = _make_collections()
        positions_col.find.return_value.sort.return_value = [
            {"position_id": "pos_1", "status": "open"},
        ]
        reconciler = TradeReconciler(database=db)
        result = reconciler.get_open_positions()
        call_args = positions_col.find.call_args
        assert call_args[0][0]["status"] == "open"
