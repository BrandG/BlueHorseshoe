"""Tests for trade journal data models."""
import pytest
from datetime import datetime

from bluehorseshoe.trading.trade_models import (
    TradeIdea,
    TradeOrder,
    TradeFill,
    PositionLeg,
    TradePosition,
    TradeReview,
    make_idea_id,
    make_order_ref,
    make_position_id,
    make_review_id,
    normalize_strategy,
    STRATEGY_DISPLAY_TO_INTERNAL,
)


class TestNormalizeStrategy:
    def test_baseline(self):
        assert normalize_strategy("Baseline") == "baseline"

    def test_mean_reversion(self):
        assert normalize_strategy("MeanRev") == "mean_reversion"

    def test_connors(self):
        assert normalize_strategy("Connors") == "connors"

    def test_already_internal(self):
        assert normalize_strategy("baseline") == "baseline"

    def test_unknown_lowercased(self):
        assert normalize_strategy("SomeNew") == "somenew"

    def test_spaces_to_underscores(self):
        assert normalize_strategy("Some Strategy") == "some_strategy"


class TestIdHelpers:
    def test_make_idea_id(self):
        assert make_idea_id("2026-03-22", "AAPL", "Baseline") == "idea_2026-03-22_AAPL_baseline"

    def test_make_idea_id_mean_reversion(self):
        assert make_idea_id("2026-03-22", "SHEL", "MeanRev") == "idea_2026-03-22_SHEL_mean_reversion"

    def test_make_idea_id_internal_name(self):
        assert make_idea_id("2026-03-22", "AAPL", "baseline") == "idea_2026-03-22_AAPL_baseline"

    def test_make_order_ref(self):
        idea_id = "idea_2026-03-22_AAPL_baseline"
        assert make_order_ref(idea_id, "T1") == "order_idea_2026-03-22_AAPL_baseline_T1"
        assert make_order_ref(idea_id, "T2") == "order_idea_2026-03-22_AAPL_baseline_T2"

    def test_make_position_id(self):
        idea_id = "idea_2026-03-22_AAPL_baseline"
        assert make_position_id(idea_id) == "pos_idea_2026-03-22_AAPL_baseline"

    def test_make_review_id(self):
        pos_id = "pos_idea_2026-03-22_AAPL_baseline"
        assert make_review_id(pos_id) == "review_pos_idea_2026-03-22_AAPL_baseline"

    def test_full_chain(self):
        """Test the full ID chain from idea through review."""
        idea_id = make_idea_id("2026-03-22", "AAPL", "Baseline")
        order_ref = make_order_ref(idea_id, "T1")
        position_id = make_position_id(idea_id)
        review_id = make_review_id(position_id)

        assert idea_id == "idea_2026-03-22_AAPL_baseline"
        assert order_ref == "order_idea_2026-03-22_AAPL_baseline_T1"
        assert position_id == "pos_idea_2026-03-22_AAPL_baseline"
        assert review_id == "review_pos_idea_2026-03-22_AAPL_baseline"


class TestTradeIdea:
    def test_defaults(self):
        idea = TradeIdea(
            idea_id="test", batch_date="2026-03-22", symbol="AAPL",
            strategy="baseline", rank=1, composite_score=10.0,
            ml_win_probability=0.65, signal_strength="HIGH",
            entry_price=150.0, stop_loss=145.0,
            take_profit_t1=153.0, take_profit_t2=160.0,
            risk_reward_ratio=2.0,
        )
        assert idea.position_size_shares == 0
        assert idea.position_size_dollars == 0.0
        assert idea.components == {}
        assert idea.sentiment == 0.0
        assert isinstance(idea.created_at, datetime)

    def test_to_doc(self):
        idea = TradeIdea(
            idea_id="test", batch_date="2026-03-22", symbol="AAPL",
            strategy="baseline", rank=1, composite_score=10.0,
            ml_win_probability=0.65, signal_strength="HIGH",
            entry_price=150.0, stop_loss=145.0,
            take_profit_t1=153.0, take_profit_t2=160.0,
            risk_reward_ratio=2.0, components={"ADX": 5.0},
        )
        doc = idea.to_doc()
        assert doc["idea_id"] == "test"
        assert doc["components"] == {"ADX": 5.0}
        assert "_id" not in doc


class TestTradeOrder:
    def test_defaults(self):
        order = TradeOrder(order_ref="ref", idea_id="idea", symbol="AAPL", leg="T1")
        assert order.status == "submitted"
        assert order.broker_order_ids == []
        assert order.error is None

    def test_to_doc(self):
        order = TradeOrder(
            order_ref="ref", idea_id="idea", symbol="AAPL", leg="T1",
            broker_order_ids=[101, 102, 103], quantity=5, limit_price=150.0,
        )
        doc = order.to_doc()
        assert doc["broker_order_ids"] == [101, 102, 103]
        assert doc["leg"] == "T1"


class TestTradeFill:
    def test_defaults(self):
        fill = TradeFill(fill_id="f1", symbol="AAPL")
        assert fill.side == "buy"
        assert fill.source == "ibkr"
        assert fill.order_ref is None
        assert fill.idea_id is None

    def test_to_doc(self):
        fill = TradeFill(fill_id="f1", symbol="AAPL", price=150.0, quantity=10)
        doc = fill.to_doc()
        assert doc["fill_id"] == "f1"
        assert doc["price"] == 150.0


class TestPositionLeg:
    def test_defaults(self):
        leg = PositionLeg(leg="T1")
        assert leg.quantity == 0
        assert leg.close_reason is None
        assert leg.pnl == 0.0

    def test_to_doc(self):
        leg = PositionLeg(
            leg="T1", quantity=5, entry_price=150.0, exit_price=153.0,
            close_reason="take_profit_t1", pnl=15.0, r_multiple=0.6,
        )
        doc = leg.to_doc()
        assert doc["leg"] == "T1"
        assert doc["pnl"] == 15.0


class TestTradePosition:
    def test_defaults(self):
        pos = TradePosition(
            position_id="pos1", idea_id="idea1", symbol="AAPL", strategy="baseline"
        )
        assert pos.status == "open"
        assert pos.legs == []
        assert pos.total_pnl == 0.0

    def test_to_doc_with_legs(self):
        pos = TradePosition(
            position_id="pos1", idea_id="idea1", symbol="AAPL", strategy="baseline",
            legs=[
                PositionLeg(leg="T1", quantity=2, pnl=5.0),
                PositionLeg(leg="T2", quantity=3, pnl=-10.0),
            ],
        )
        doc = pos.to_doc()
        assert len(doc["legs"]) == 2
        assert doc["legs"][0]["leg"] == "T1"
        assert doc["legs"][1]["pnl"] == -10.0


class TestTradeReview:
    def test_defaults(self):
        review = TradeReview(
            review_id="r1", position_id="p1", idea_id="i1",
            symbol="AAPL", strategy="baseline", batch_date="2026-03-22",
        )
        assert review.followed_plan is True
        assert review.discipline_score == 1.0
        assert review.tags == []
        assert review.notes == ""
        assert review.outcome == ""

    def test_to_doc(self):
        review = TradeReview(
            review_id="r1", position_id="p1", idea_id="i1",
            symbol="AAPL", strategy="baseline", batch_date="2026-03-22",
            outcome="win", r_multiple=1.5, tags=["clean_entry"],
        )
        doc = review.to_doc()
        assert doc["outcome"] == "win"
        assert doc["tags"] == ["clean_entry"]
