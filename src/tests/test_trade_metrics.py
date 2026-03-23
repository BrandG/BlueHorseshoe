"""Tests for trade metrics calculator."""
import pytest
from unittest.mock import MagicMock

from bluehorseshoe.trading.trade_metrics import (
    TradeMetricsCalculator,
    PortfolioMetrics,
    StrategyMetrics,
    DisciplineMetrics,
)


def _make_position(
    pnl=10.0, commission=1.0, planned_entry=150.0, planned_stop=145.0,
    actual_entry=150.05, total_qty=10, strategy="baseline", status="closed",
    legs=None,
):
    """Build a position dict matching trade_positions schema."""
    if legs is None:
        legs = [{"leg": "T2", "quantity": total_qty, "hold_days": 3,
                 "entry_price": actual_entry, "exit_price": actual_entry + pnl / total_qty}]
    return {
        "position_id": "pos_test",
        "idea_id": "idea_test",
        "symbol": "AAPL",
        "strategy": strategy,
        "status": status,
        "planned_entry": planned_entry,
        "planned_stop": planned_stop,
        "actual_entry": actual_entry,
        "total_quantity": total_qty,
        "total_pnl": pnl,
        "total_commission": commission,
        "legs": legs,
    }


@pytest.fixture
def mock_db():
    db = MagicMock()
    positions_col = MagicMock()
    ideas_col = MagicMock()
    cols = {"trade_positions": positions_col, "trade_ideas": ideas_col}
    db.__getitem__ = MagicMock(side_effect=lambda name: cols[name])
    return db, positions_col, ideas_col


class TestRMultiple:
    def test_winning_trade(self):
        pos = _make_position(pnl=50.0, commission=2.0, planned_entry=100.0,
                             planned_stop=95.0, total_qty=10)
        # net = 48, risk = (100-95) * 10 = 50, R = 48/50 = 0.96
        assert TradeMetricsCalculator.calculate_r_multiple(pos) == 0.96

    def test_losing_trade(self):
        pos = _make_position(pnl=-30.0, commission=2.0, planned_entry=100.0,
                             planned_stop=95.0, total_qty=10)
        # net = -32, risk = 50, R = -32/50 = -0.64
        assert TradeMetricsCalculator.calculate_r_multiple(pos) == -0.64

    def test_zero_risk(self):
        pos = _make_position(planned_entry=100.0, planned_stop=100.0)
        assert TradeMetricsCalculator.calculate_r_multiple(pos) == 0.0

    def test_zero_quantity(self):
        pos = _make_position(total_qty=0, legs=[])
        assert TradeMetricsCalculator.calculate_r_multiple(pos) == 0.0


class TestSlippage:
    def test_positive_slippage(self):
        pos = _make_position(planned_entry=100.0, actual_entry=100.10)
        assert TradeMetricsCalculator.calculate_slippage(pos) == 0.001

    def test_negative_slippage(self):
        pos = _make_position(planned_entry=100.0, actual_entry=99.90)
        assert TradeMetricsCalculator.calculate_slippage(pos) == -0.001

    def test_zero_planned(self):
        pos = _make_position(planned_entry=0.0)
        assert TradeMetricsCalculator.calculate_slippage(pos) == 0.0


class TestPortfolioMetrics:
    def test_win_rate(self, mock_db):
        db, positions_col, _ = mock_db
        positions_col.find.return_value = [
            _make_position(pnl=50.0, commission=1.0),   # win
            _make_position(pnl=30.0, commission=1.0),   # win
            _make_position(pnl=-20.0, commission=1.0),  # loss
        ]
        calc = TradeMetricsCalculator(database=db)
        m = calc.calculate_portfolio_metrics()

        assert m.total_trades == 3
        assert m.wins == 2
        assert m.losses == 1
        assert m.win_rate == pytest.approx(0.6667, abs=0.001)

    def test_profit_factor(self, mock_db):
        db, positions_col, _ = mock_db
        positions_col.find.return_value = [
            _make_position(pnl=100.0, commission=0),
            _make_position(pnl=-40.0, commission=0),
        ]
        calc = TradeMetricsCalculator(database=db)
        m = calc.calculate_portfolio_metrics()

        # gross_wins=100, gross_losses=40, PF=2.5
        assert m.profit_factor == 2.5

    def test_expectancy(self, mock_db):
        db, positions_col, _ = mock_db
        positions_col.find.return_value = [
            _make_position(pnl=100.0, commission=0),
            _make_position(pnl=-50.0, commission=0),
        ]
        calc = TradeMetricsCalculator(database=db)
        m = calc.calculate_portfolio_metrics()

        # win_rate=0.5, avg_win=100, loss_rate=0.5, avg_loss=50
        # expectancy = 0.5*100 - 0.5*50 = 25
        assert m.expectancy == 25.0

    def test_empty_positions(self, mock_db):
        db, positions_col, _ = mock_db
        positions_col.find.return_value = []
        calc = TradeMetricsCalculator(database=db)
        m = calc.calculate_portfolio_metrics()

        assert m.total_trades == 0
        assert m.win_rate == 0.0
        assert m.net_pnl == 0.0

    def test_net_pnl_includes_commission(self, mock_db):
        db, positions_col, _ = mock_db
        positions_col.find.return_value = [
            _make_position(pnl=100.0, commission=5.0),
        ]
        calc = TradeMetricsCalculator(database=db)
        m = calc.calculate_portfolio_metrics()

        assert m.total_pnl == 100.0
        assert m.total_commission == 5.0
        assert m.net_pnl == 95.0


class TestStrategyMetrics:
    def test_strategy_filter(self, mock_db):
        db, positions_col, _ = mock_db
        positions_col.find.return_value = [
            _make_position(pnl=50.0, commission=0, strategy="baseline"),
        ]
        calc = TradeMetricsCalculator(database=db)
        m = calc.calculate_strategy_metrics("baseline")

        assert isinstance(m, StrategyMetrics)
        assert m.strategy == "baseline"
        assert m.total_trades == 1


class TestDisciplineMetrics:
    def test_execution_rate(self, mock_db):
        db, positions_col, ideas_col = mock_db
        ideas_col.count_documents.return_value = 10
        positions_col.find.return_value = [
            _make_position() for _ in range(3)
        ]
        calc = TradeMetricsCalculator(database=db)
        m = calc.calculate_discipline_metrics()

        assert m.ideas_generated == 10
        assert m.ideas_traded == 3
        assert m.execution_rate == pytest.approx(0.3, abs=0.01)

    def test_zero_ideas(self, mock_db):
        db, positions_col, ideas_col = mock_db
        ideas_col.count_documents.return_value = 0
        positions_col.find.return_value = []
        calc = TradeMetricsCalculator(database=db)
        m = calc.calculate_discipline_metrics()

        assert m.execution_rate == 0.0
