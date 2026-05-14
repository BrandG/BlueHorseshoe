"""Tests for bh_swing.analysis.stop_rules."""
from dataclasses import replace

import pytest

from bh_swing.analysis import stop_rules
from bh_swing.analysis.position_state import (
    BracketLeg, BrokerOrderView, ManagedPosition,
)


def _view(order_id, action="SELL", order_type="STP", lmt=0.0, stp=0.0,
          status="Submitted", filled=0):
    return BrokerOrderView(
        order_id=order_id, symbol="AAPL", action=action, order_type=order_type,
        limit_price=lmt, stop_price=stp, status=status,
        filled_qty=filled, remaining_qty=10 - filled,
    )


def _leg(leg="T1", filled_entry=False, stop_alive=True, stop_price=147.0,
         entry_price=150.0, tp_price=151.5):
    entry = _view(1, action="BUY", order_type="LMT", lmt=entry_price,
                  status="Filled" if filled_entry else "Submitted",
                  filled=10 if filled_entry else 0)
    tp = _view(2, action="SELL", order_type="LMT", lmt=tp_price, status="Submitted")
    stop_status = "PreSubmitted" if stop_alive else "Cancelled"
    stop = _view(3, action="SELL", order_type="STP", stp=stop_price, status=stop_status)
    return BracketLeg(
        leg=leg, quantity=10, entry_price=entry_price,
        take_profit_price=tp_price, stop_loss_price=147.0,
        entry_order=entry, take_profit_order=tp, stop_order=stop,
    )


def _position(t1, t2, side="long", entry_price=150.0, target_price=155.0,
              symbol="AAPL"):
    legs = []
    if t1 is not None:
        legs.append(t1)
    if t2 is not None:
        legs.append(t2)
    return ManagedPosition(
        symbol=symbol, idea_id="idea-1", side=side,
        entry_price=entry_price, target_price=target_price,
        original_stop_price=147.0, legs=legs,
        broker_position_qty=20, broker_avg_cost=entry_price,
    )


class TestProposeStopAdvancement:
    def test_returns_none_when_t1_not_filled(self):
        pos = _position(_leg("T1", filled_entry=False), _leg("T2", filled_entry=False))
        assert stop_rules.propose_stop_advancement(pos) is None

    def test_advances_to_breakeven_when_t1_fills(self):
        t1 = _leg("T1", filled_entry=True)
        t2 = _leg("T2", filled_entry=True, stop_price=147.0)
        pos = _position(t1, t2, entry_price=150.0)
        decision = stop_rules.propose_stop_advancement(pos)
        assert decision is not None
        assert decision.symbol == "AAPL"
        assert decision.leg == "T2"
        assert decision.current_stop == 147.0
        assert decision.new_stop == 150.0
        assert decision.side == "long"
        assert decision.order_id == 3
        assert "breakeven" in decision.reason.lower()

    def test_no_op_when_stop_already_at_breakeven(self):
        t1 = _leg("T1", filled_entry=True)
        t2 = _leg("T2", filled_entry=True, stop_price=150.0)  # already at entry
        pos = _position(t1, t2, entry_price=150.0)
        assert stop_rules.propose_stop_advancement(pos) is None

    def test_no_op_when_stop_already_above_breakeven(self):
        # Some other tool already moved the stop higher; don't push back down.
        t1 = _leg("T1", filled_entry=True)
        t2 = _leg("T2", filled_entry=True, stop_price=151.0)
        pos = _position(t1, t2, entry_price=150.0)
        assert stop_rules.propose_stop_advancement(pos) is None

    def test_no_op_when_t2_stop_dead(self):
        t1 = _leg("T1", filled_entry=True)
        t2 = _leg("T2", filled_entry=True, stop_alive=False)
        pos = _position(t1, t2)
        assert stop_rules.propose_stop_advancement(pos) is None

    def test_no_op_when_t2_missing(self):
        t1 = _leg("T1", filled_entry=True)
        pos = _position(t1, None)
        assert stop_rules.propose_stop_advancement(pos) is None

    def test_no_op_when_t1_missing(self):
        t2 = _leg("T2", filled_entry=True)
        pos = _position(None, t2)
        assert stop_rules.propose_stop_advancement(pos) is None

    def test_short_advances_stop_down_to_entry(self):
        # Mirror logic for shorts. Stop is above entry for a short; advance lowers it.
        t1 = _leg("T1", filled_entry=True)
        t2 = _leg("T2", filled_entry=True, stop_price=153.0)
        pos = _position(t1, t2, side="short", entry_price=150.0)
        decision = stop_rules.propose_stop_advancement(pos)
        assert decision is not None
        assert decision.new_stop == 150.0
        assert decision.side == "short"

    def test_short_no_op_when_stop_already_below_breakeven(self):
        t1 = _leg("T1", filled_entry=True)
        t2 = _leg("T2", filled_entry=True, stop_price=149.0)
        pos = _position(t1, t2, side="short", entry_price=150.0)
        assert stop_rules.propose_stop_advancement(pos) is None

    def test_unsupported_rule_returns_none(self):
        # MIDPOINT and ATR_CLAMPED are placeholders for now.
        t1 = _leg("T1", filled_entry=True)
        t2 = _leg("T2", filled_entry=True)
        pos = _position(t1, t2)
        assert stop_rules.propose_stop_advancement(
            pos, rule=stop_rules.StopRule.MIDPOINT
        ) is None
        assert stop_rules.propose_stop_advancement(
            pos, rule=stop_rules.StopRule.ATR_CLAMPED
        ) is None


class TestProposeEarlyExit:
    def test_disabled_by_default(self):
        pos = _position(_leg("T1", filled_entry=True), _leg("T2", filled_entry=True))
        assert stop_rules.propose_early_exit(pos) is None

    def test_enabled_returns_hold_for_now(self):
        pos = _position(_leg("T1", filled_entry=True), _leg("T2", filled_entry=True))
        decision = stop_rules.propose_early_exit(pos, enabled=True)
        # Sub-phase 1c will swap the body; the wiring just needs a typed result.
        assert decision is not None
        assert decision.action == stop_rules.ExitAction.HOLD
