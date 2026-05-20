"""Tests for bh_swing.analysis.position_state.

Mocks IBKR Trade objects and a Mongo collection — no live infra required.
"""
from unittest.mock import MagicMock

import pytest

from bh_swing.analysis import position_state


def _trade(order_id, action, order_type, lmt=0.0, stp=0.0,
           status="Submitted", filled=0, remaining=0, symbol="AAPL"):
    """Build an ib_async-shaped Trade mock."""
    t = MagicMock()
    t.contract.symbol = symbol
    t.order.orderId = order_id
    t.order.action = action
    t.order.orderType = order_type
    t.order.lmtPrice = lmt
    t.order.auxPrice = stp
    t.orderStatus.status = status
    t.orderStatus.filled = filled
    t.orderStatus.remaining = remaining
    return t


def _mongo(docs):
    """Build a MagicMock that mimics a Mongo collection.find().sort()."""
    coll = MagicMock()
    cursor = MagicMock()
    cursor.sort.return_value = iter(docs)
    coll.find.return_value = cursor
    return coll


def _doc(symbol, leg, idea_id, ids, entry=100.0, tp=102.0, stop=98.0, qty=10, ts=100):
    return {
        "symbol": symbol, "leg": leg, "idea_id": idea_id,
        "broker_order_ids": ids, "quantity": qty,
        "limit_price": entry, "take_profit_price": tp, "stop_loss_price": stop,
        "status": "submitted", "submitted_at": ts,
    }


class TestBuildResult:
    def test_no_positions_returns_empty(self):
        coll = _mongo([])
        result = position_state.build_managed_positions([], [], coll)
        assert result.managed == []
        assert result.unmanaged_symbols == []
        assert result.drift_notes == []

    def test_skips_flat_positions(self):
        coll = _mongo([])
        positions = [{"symbol": "AAPL", "position": 0, "avg_cost": 0}]
        result = position_state.build_managed_positions(positions, [], coll)
        assert result.managed == []
        assert result.unmanaged_symbols == []

    def test_unmanaged_when_mongo_collection_is_none(self):
        positions = [{"symbol": "AAPL", "position": 10, "avg_cost": 150.0}]
        result = position_state.build_managed_positions(positions, [], None)
        assert result.managed == []
        assert result.unmanaged_symbols == ["AAPL"]
        assert any("no Mongo trade_orders" in n for n in result.drift_notes)

    def test_unmanaged_when_no_trade_orders_match(self):
        positions = [{"symbol": "AAPL", "position": 10, "avg_cost": 150.0}]
        coll = _mongo([])  # find().sort() yields nothing
        result = position_state.build_managed_positions(positions, [], coll)
        assert result.managed == []
        assert result.unmanaged_symbols == ["AAPL"]


class TestManagedPositionBuild:
    def test_full_bracket_with_two_legs_builds_cleanly(self):
        positions = [{"symbol": "AAPL", "position": 20, "avg_cost": 150.0}]
        # T1 leg: 3 orders (entry/tp/stop), T2 leg: 3 orders
        t1_docs = _doc("AAPL", "T1", "idea-1", [1, 2, 3],
                       entry=150.0, tp=151.5, stop=147.0, qty=10)
        t2_docs = _doc("AAPL", "T2", "idea-1", [4, 5, 6],
                       entry=150.0, tp=155.0, stop=147.0, qty=10)
        coll = _mongo([t1_docs, t2_docs])

        trades = [
            _trade(1, "BUY",  "LMT", lmt=150.0, status="Filled",       filled=10, remaining=0),
            _trade(2, "SELL", "LMT", lmt=151.5, status="Submitted",    filled=0,  remaining=10),
            _trade(3, "SELL", "STP", stp=147.0, status="PreSubmitted", filled=0,  remaining=10),
            _trade(4, "BUY",  "LMT", lmt=150.0, status="Filled",       filled=10, remaining=0),
            _trade(5, "SELL", "LMT", lmt=155.0, status="Submitted",    filled=0,  remaining=10),
            _trade(6, "SELL", "STP", stp=147.0, status="PreSubmitted", filled=0,  remaining=10),
        ]

        result = position_state.build_managed_positions(positions, trades, coll)
        assert len(result.managed) == 1
        mp = result.managed[0]
        assert mp.symbol == "AAPL"
        assert mp.idea_id == "idea-1"
        assert mp.side == "long"
        assert mp.entry_price == 150.0
        assert mp.target_price == 155.0
        assert mp.original_stop_price == 147.0
        assert mp.broker_position_qty == 20

        assert mp.t1 is not None
        assert mp.t1.leg == "T1"
        assert mp.t1.entry_filled is True
        assert mp.t1.take_profit_order is not None
        assert mp.t1.stop_order is not None
        assert mp.t1.stop_order.stop_price == 147.0
        assert mp.t1.stop_is_alive is True

        assert mp.t2 is not None
        assert mp.t2.entry_filled is True

    def test_partial_fill_flag(self):
        positions = [{"symbol": "TSLA", "position": 5, "avg_cost": 200.0}]
        t1 = _doc("TSLA", "T1", "i", [10, 11, 12], qty=10, entry=200.0)
        coll = _mongo([t1])
        trades = [
            _trade(10, "BUY", "LMT", lmt=200.0, status="Submitted", filled=5, remaining=5),
            _trade(11, "SELL", "LMT", lmt=202.0, status="PreSubmitted"),
            _trade(12, "SELL", "STP", stp=198.0, status="PreSubmitted"),
        ]
        result = position_state.build_managed_positions(positions, trades, coll)
        assert len(result.managed) == 1
        t1leg = result.managed[0].t1
        assert t1leg.entry_partially_filled is True
        assert t1leg.entry_filled is False

    def test_filled_entry_inferred_when_position_held(self):
        """After T1 entry fills, IBKR drops it from openTrades. If broker
        still reports the position is held, we infer the entry filled
        (cancellation would have left qty=0). Without this inference,
        propose_stop_advancement bails forever on `not t1.entry_filled`."""
        positions = [{"symbol": "NVDA", "position": 10, "avg_cost": 500.0}]
        t1 = _doc("NVDA", "T1", "i", [20, 21, 22])
        coll = _mongo([t1])
        # entry order 20 is missing from open trades (filled + gone)
        trades = [
            _trade(21, "SELL", "LMT", lmt=510.0, status="Submitted"),
            _trade(22, "SELL", "STP", stp=495.0, status="PreSubmitted"),
        ]
        result = position_state.build_managed_positions(positions, trades, coll)
        assert len(result.managed) == 1
        leg = result.managed[0].t1
        # Synthesized Filled view, not None.
        assert leg.entry_order is not None
        assert leg.entry_order.status == "Filled"
        assert leg.entry_order.order_id == 20  # carries through Mongo id
        assert leg.entry_filled is True
        assert leg.stop_is_alive is True
        assert leg.take_profit_order is not None

    def test_no_entry_synthesis_when_position_not_held(self):
        """If broker shows qty=0 the symbol isn't in get_positions() at
        all — build_managed_positions skips it. But guard against the
        synthesis firing when the leg has no broker_position_qty signal
        (e.g., a future caller that passes 0)."""
        positions = [{"symbol": "NVDA", "position": 0, "avg_cost": 0.0}]
        # build_managed_positions filters qty=0 entirely; this asserts that.
        t1 = _doc("NVDA", "T1", "i", [20, 21, 22])
        coll = _mongo([t1])
        result = position_state.build_managed_positions(positions, [], coll)
        assert result.managed == []

    def test_end_to_end_t1_filled_drives_stop_advancement(self):
        """Full chain: synthesized entry_filled → propose_stop_advancement
        returns a breakeven move. This is the bug the May 19 soak surfaced:
        seven T1 take-profits fired, zero would_advance_stop events, because
        T1 entries had been filled-and-gone for days."""
        from bh_swing.analysis import stop_rules

        # Long position, T2 still held (T1 take-profit hit yesterday).
        positions = [{"symbol": "AAPL", "position": 10, "avg_cost": 150.0}]
        t1 = _doc("AAPL", "T1", "i", [101, 102, 103], entry=150.0, stop=147.0)
        t2 = _doc("AAPL", "T2", "i", [104, 105, 106], entry=150.0, stop=147.0)
        coll = _mongo([t1, t2])
        # T1 fully closed (entry+tp+stop gone). T2 entry gone (filled);
        # T2 TP and STP still working.
        trades = [
            _trade(105, "SELL", "LMT", lmt=155.0, status="Submitted", symbol="AAPL"),
            _trade(106, "SELL", "STP", stp=147.0, status="PreSubmitted", symbol="AAPL"),
        ]
        result = position_state.build_managed_positions(positions, trades, coll)
        assert len(result.managed) == 1
        pos = result.managed[0]
        assert pos.t1.entry_filled is True   # synthesized
        assert pos.t2.entry_filled is True   # synthesized
        assert pos.t2.stop_is_alive is True

        decision = stop_rules.propose_stop_advancement(pos)
        assert decision is not None, "T1 filled + T2 stop alive should advance"
        assert decision.leg == "T2"
        assert decision.current_stop == 147.0
        assert decision.new_stop == 150.0
        assert decision.order_id == 106

    def test_takes_newest_bracket_when_multiple_match(self):
        positions = [{"symbol": "MSFT", "position": 10, "avg_cost": 400.0}]
        old = _doc("MSFT", "T1", "old-idea", [1, 2, 3], ts=10)
        new = _doc("MSFT", "T1", "new-idea", [4, 5, 6], ts=100)
        # Mongo find().sort() returns newest first
        coll = _mongo([new, old])
        result = position_state.build_managed_positions(positions, [], coll)
        assert len(result.managed) == 1
        assert result.managed[0].idea_id == "new-idea"

    def test_drift_note_on_unrecognized_order_role(self):
        positions = [{"symbol": "XYZ", "position": 10, "avg_cost": 50.0}]
        doc = _doc("XYZ", "T1", "i", [30, 31, 32])
        coll = _mongo([doc])
        # Order 31 has weird type — neither LMT nor STP
        trades = [
            _trade(30, "BUY",  "LMT", lmt=50.0, status="Filled"),
            _trade(31, "SELL", "MKT", status="Submitted"),  # unrecognized
            _trade(32, "SELL", "STP", stp=48.0, status="PreSubmitted"),
        ]
        result = position_state.build_managed_positions(positions, trades, coll)
        assert any("role unrecognized" in n for n in result.drift_notes)
        # Position still managed — TP slot just empty.
        assert len(result.managed) == 1
        assert result.managed[0].t1.take_profit_order is None

    def test_mongo_lookup_exception_is_drift_not_crash(self):
        positions = [{"symbol": "BAD", "position": 1, "avg_cost": 1.0}]
        coll = MagicMock()
        coll.find.side_effect = RuntimeError("connection lost")
        result = position_state.build_managed_positions(positions, [], coll)
        assert result.managed == []
        assert result.unmanaged_symbols == ["BAD"]
        assert any("Mongo lookup failed" in n for n in result.drift_notes)
