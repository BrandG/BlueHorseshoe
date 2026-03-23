"""Tests for the trade journal reporter."""
import pytest
from datetime import datetime
from unittest.mock import MagicMock

from bluehorseshoe.trading.trade_journal_reporter import TradeJournalReporter
from bluehorseshoe.trading.trade_metrics import PortfolioMetrics


def _make_collections():
    db = MagicMock()
    reviews_col = MagicMock()
    positions_col = MagicMock()
    ideas_col = MagicMock()
    cols = {
        "trade_reviews": reviews_col,
        "trade_positions": positions_col,
        "trade_ideas": ideas_col,
    }
    db.__getitem__ = MagicMock(side_effect=lambda name: cols[name])
    return db, reviews_col, positions_col, ideas_col


def _make_closed_position(symbol="AAPL", strategy="baseline", pnl=50.0,
                          commission=2.0, planned_entry=150.0, planned_stop=145.0,
                          actual_entry=150.10, total_qty=10):
    return {
        "position_id": f"pos_idea_2026-03-22_{symbol}_{strategy}",
        "idea_id": f"idea_2026-03-22_{symbol}_{strategy}",
        "symbol": symbol,
        "strategy": strategy,
        "status": "closed",
        "planned_entry": planned_entry,
        "planned_stop": planned_stop,
        "planned_target_t1": planned_entry * 1.02,
        "planned_target_t2": 160.0,
        "actual_entry": actual_entry,
        "total_quantity": total_qty,
        "total_pnl": pnl,
        "total_commission": commission,
        "entry_slippage": actual_entry - planned_entry,
        "opened_at": datetime(2026, 3, 23, 14, 0),
        "closed_at": datetime(2026, 3, 25, 15, 0),
        "legs": [{
            "leg": "T2",
            "quantity": total_qty,
            "entry_price": actual_entry,
            "exit_price": actual_entry + pnl / total_qty,
            "close_reason": "take_profit_t2" if pnl > 0 else "stop_loss",
            "pnl": pnl,
            "r_multiple": 0.96,
            "hold_days": 2,
        }],
    }


class TestDailyReview:
    def test_creates_reviews(self):
        db, reviews_col, positions_col, ideas_col = _make_collections()

        positions_col.find.return_value = [
            _make_closed_position("AAPL", pnl=50.0),
            _make_closed_position("MSFT", pnl=-20.0),
        ]

        reporter = TradeJournalReporter(database=db)
        result = reporter.generate_daily_review("2026-03-25")

        assert result["reviews_created"] == 2
        assert result["positions_reviewed"] == 2

        # Check review docs were upserted
        assert reviews_col.update_one.call_count == 2

        # Check first review doc
        first_call = reviews_col.update_one.call_args_list[0]
        doc = first_call[0][1]["$set"]
        assert doc["symbol"] == "AAPL"
        assert doc["outcome"] == "win"
        assert doc["t2_hit"] is True
        assert doc["stop_hit"] is False

    def test_empty_positions(self):
        db, reviews_col, positions_col, ideas_col = _make_collections()
        positions_col.find.return_value = []
        ideas_col.distinct.return_value = []

        reporter = TradeJournalReporter(database=db)
        result = reporter.generate_daily_review("2026-03-25")

        assert result["reviews_created"] == 0
        assert result["positions_reviewed"] == 0


class TestBuildReviewDoc:
    def test_winning_trade_review(self):
        db, _, _, _ = _make_collections()
        reporter = TradeJournalReporter(database=db)

        pos = _make_closed_position(pnl=50.0, commission=2.0)
        review = reporter._build_review_doc(pos, "2026-03-22")

        assert review["outcome"] == "win"
        assert review["gross_pnl"] == 50.0
        assert review["net_pnl"] == 48.0
        assert review["t2_hit"] is True
        assert review["stop_hit"] is False
        assert review["hold_days"] == 2

    def test_losing_trade_review(self):
        db, _, _, _ = _make_collections()
        reporter = TradeJournalReporter(database=db)

        pos = _make_closed_position(pnl=-30.0, commission=2.0)
        review = reporter._build_review_doc(pos, "2026-03-22")

        assert review["outcome"] == "loss"
        assert review["net_pnl"] == -32.0
        assert review["stop_hit"] is True

    def test_discipline_score_on_plan(self):
        db, _, _, _ = _make_collections()
        reporter = TradeJournalReporter(database=db)

        pos = _make_closed_position(planned_entry=150.0, actual_entry=150.05)
        review = reporter._build_review_doc(pos, "2026-03-22")

        # 0.05/150 = 0.033%, within 1% → full discipline
        assert review["discipline_score"] == 1.0
        assert review["followed_plan"] is True

    def test_discipline_score_off_plan(self):
        db, _, _, _ = _make_collections()
        reporter = TradeJournalReporter(database=db)

        pos = _make_closed_position(planned_entry=150.0, actual_entry=155.0)
        review = reporter._build_review_doc(pos, "2026-03-22")

        # 5/150 = 3.3%, penalty = min(0.3, 0.033*10) = 0.3
        assert review["discipline_score"] < 1.0
        assert review["followed_plan"] is False

    def test_review_id_format(self):
        db, _, _, _ = _make_collections()
        reporter = TradeJournalReporter(database=db)

        pos = _make_closed_position()
        review = reporter._build_review_doc(pos, "2026-03-22")

        assert review["review_id"].startswith("review_pos_")

    def test_breakeven_outcome(self):
        db, _, _, _ = _make_collections()
        reporter = TradeJournalReporter(database=db)

        pos = _make_closed_position(pnl=1.0, commission=1.0)  # net = 0
        review = reporter._build_review_doc(pos, "2026-03-22")

        assert review["outcome"] == "breakeven"


class TestWeeklySummary:
    def test_generates_summary(self):
        db, _, positions_col, ideas_col = _make_collections()

        positions = [
            _make_closed_position("AAPL", pnl=50.0),
            _make_closed_position("MSFT", pnl=-20.0),
        ]

        # positions_col.find is called multiple times (metrics + top positions)
        # Need to handle .sort() chain for the top winners/losers query
        class MockSortable:
            def __init__(self, data):
                self._data = data
            def sort(self, *args, **kwargs):
                return self._data
            def __iter__(self):
                return iter(self._data)

        positions_col.find.return_value = MockSortable(positions)
        ideas_col.count_documents.return_value = 10

        reporter = TradeJournalReporter(database=db)
        summary = reporter.generate_weekly_summary("2026-03-17")

        assert summary["period"] == "2026-03-17 to 2026-03-22"
        assert isinstance(summary["portfolio"], PortfolioMetrics)
        assert hasattr(summary["discipline"], "ideas_generated")


class TestConsoleOutput:
    def test_print_daily_review(self, capsys):
        db, _, _, _ = _make_collections()
        reporter = TradeJournalReporter(database=db)

        data = {
            "reviews_created": 2,
            "positions_reviewed": 2,
            "summary": PortfolioMetrics(
                total_trades=2, wins=1, losses=1,
                win_rate=0.5, net_pnl=25.0, avg_r_multiple=0.5,
                expectancy=12.5,
            ),
        }
        reporter.print_daily_review(data)
        output = capsys.readouterr().out

        assert "DAILY TRADE REVIEW" in output
        assert "50.0%" in output
        assert "$+25.00" in output

    def test_print_weekly_summary(self, capsys):
        db, _, _, _ = _make_collections()
        reporter = TradeJournalReporter(database=db)

        from bluehorseshoe.trading.trade_metrics import DisciplineMetrics
        data = {
            "period": "2026-03-17 to 2026-03-22",
            "portfolio": PortfolioMetrics(total_trades=5, wins=3, losses=2, win_rate=0.6, net_pnl=100.0),
            "by_strategy": [],
            "discipline": DisciplineMetrics(ideas_generated=10, ideas_traded=5, execution_rate=0.5, avg_plan_adherence=0.9),
            "top_winners": [{"symbol": "AAPL", "strategy": "baseline", "pnl": 50.0}],
            "top_losers": [{"symbol": "MSFT", "strategy": "baseline", "pnl": -20.0}],
        }
        reporter.print_weekly_summary(data)
        output = capsys.readouterr().out

        assert "WEEKLY TRADE SUMMARY" in output
        assert "AAPL" in output
        assert "MSFT" in output
