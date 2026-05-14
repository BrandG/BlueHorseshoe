"""Tests for bh_swing.operator.flatten — dry-run + execute logic mocked."""
from unittest.mock import MagicMock

import pytest

from bh_swing.operator import flatten


def _client(positions=None, quotes=None, open_trades=None,
            cancel_result=None, market_result=None):
    """Build a MagicMock IBKRClient with sensible defaults."""
    c = MagicMock()
    c.get_positions.return_value = positions or []
    c.get_open_trades.return_value = open_trades or []
    c.get_quote.side_effect = lambda sym: MagicMock(
        last=(quotes or {}).get(sym, 0.0),
        close=(quotes or {}).get(sym, 0.0),
    )
    c.cancel_order.return_value = cancel_result or {"status": "cancelling", "error": None}
    c.place_market_order.return_value = market_result or {
        "order_id": 999, "status": "submitted", "error": None,
    }
    return c


@pytest.fixture(autouse=True)
def temp_journal(tmp_path, monkeypatch):
    p = tmp_path / "bh_swing_flatten_journal.csv"
    monkeypatch.setattr(flatten, "JOURNAL_PATH", str(p))
    return str(p)


class TestDryRun:
    def test_no_positions_returns_zero(self, capsys):
        c = _client()
        closed = flatten.run(c, execute=False, max_closes=5, sort_by="worst")
        assert closed == 0
        c.cancel_order.assert_not_called()
        c.place_market_order.assert_not_called()

    def test_lists_positions_without_mutating(self, capsys):
        c = _client(
            positions=[
                {"symbol": "AAPL", "position": 10, "avg_cost": 150.0},
                {"symbol": "MSFT", "position": 5, "avg_cost": 400.0},
            ],
            quotes={"AAPL": 148.0, "MSFT": 410.0},
        )
        closed = flatten.run(c, execute=False, max_closes=5, sort_by="worst")
        assert closed == 0
        c.cancel_order.assert_not_called()
        c.place_market_order.assert_not_called()
        out = capsys.readouterr().out
        assert "AAPL" in out and "MSFT" in out
        assert "DRY-RUN" in out


class TestExecute:
    def test_closes_position_cancels_orders_then_market_sell(self, capsys):
        # AAPL has 3 working orders (entry/tp/stop), 10 long position
        ord1, ord2, ord3 = MagicMock(), MagicMock(), MagicMock()
        for t, oid in [(ord1, 1), (ord2, 2), (ord3, 3)]:
            t.contract.symbol = "AAPL"
            t.order.orderId = oid
        c = _client(
            positions=[{"symbol": "AAPL", "position": 10, "avg_cost": 150.0}],
            quotes={"AAPL": 145.0},
            open_trades=[ord1, ord2, ord3],
        )
        closed = flatten.run(c, execute=True, max_closes=5, sort_by="worst")
        assert closed == 1
        # All three orders cancelled
        assert c.cancel_order.call_count == 3
        cancelled_ids = {call.args[0] for call in c.cancel_order.call_args_list}
        assert cancelled_ids == {1, 2, 3}
        # One market SELL for the full position
        c.place_market_order.assert_called_once_with("AAPL", "SELL", 10)

    def test_respects_max_closes(self):
        c = _client(
            positions=[
                {"symbol": "A", "position": 1, "avg_cost": 100.0},
                {"symbol": "B", "position": 1, "avg_cost": 100.0},
                {"symbol": "C", "position": 1, "avg_cost": 100.0},
            ],
            quotes={"A": 90.0, "B": 95.0, "C": 99.0},
        )
        closed = flatten.run(c, execute=True, max_closes=2, sort_by="worst")
        assert closed == 2
        assert c.place_market_order.call_count == 2
        # Worst first: A ($-10), then B ($-5)
        closed_syms = [call.args[0] for call in c.place_market_order.call_args_list]
        assert closed_syms == ["A", "B"]

    def test_symbols_filter(self):
        c = _client(
            positions=[
                {"symbol": "AAPL", "position": 1, "avg_cost": 100.0},
                {"symbol": "MSFT", "position": 1, "avg_cost": 100.0},
            ],
            quotes={"AAPL": 90.0, "MSFT": 80.0},
        )
        closed = flatten.run(c, execute=True, max_closes=5, sort_by="worst",
                             symbols_filter={"AAPL"})
        assert closed == 1
        c.place_market_order.assert_called_once_with("AAPL", "SELL", 1)

    def test_market_order_failure_journals_error(self, temp_journal):
        c = _client(
            positions=[{"symbol": "XYZ", "position": 1, "avg_cost": 100.0}],
            quotes={"XYZ": 99.0},
            market_result={"order_id": 0, "status": "error", "error": "rejected"},
        )
        closed = flatten.run(c, execute=True, max_closes=5, sort_by="worst")
        assert closed == 0
        with open(temp_journal) as f:
            text = f.read()
        assert "flatten_failed" in text
        assert "rejected" in text

    def test_short_position_buys_to_cover(self):
        c = _client(
            positions=[{"symbol": "SHRT", "position": -5, "avg_cost": 50.0}],
            quotes={"SHRT": 55.0},
        )
        flatten.run(c, execute=True, max_closes=1, sort_by="worst")
        c.place_market_order.assert_called_once_with("SHRT", "BUY", 5)


class TestSortStrategies:
    def _three(self):
        return [
            {"symbol": "A", "position": 1, "avg_cost": 100.0},
            {"symbol": "B", "position": 2, "avg_cost": 200.0},
            {"symbol": "C", "position": 10, "avg_cost": 50.0},
        ]

    def test_worst_first(self):
        c = _client(positions=self._three(),
                    quotes={"A": 90.0, "B": 210.0, "C": 49.0})  # A: -10, B: +20, C: -10
        flatten.run(c, execute=True, max_closes=1, sort_by="worst")
        # A or C tied; verify a known-worst symbol was closed first
        first = c.place_market_order.call_args_list[0].args[0]
        assert first in {"A", "C"}

    def test_best_first(self):
        c = _client(positions=self._three(),
                    quotes={"A": 90.0, "B": 210.0, "C": 49.0})
        flatten.run(c, execute=True, max_closes=1, sort_by="best")
        first = c.place_market_order.call_args_list[0].args[0]
        assert first == "B"

    def test_biggest_first(self):
        # Biggest notional: B = 2 * 210 = 420, C = 10 * 49 = 490, A = 90
        c = _client(positions=self._three(),
                    quotes={"A": 90.0, "B": 210.0, "C": 49.0})
        flatten.run(c, execute=True, max_closes=1, sort_by="biggest")
        first = c.place_market_order.call_args_list[0].args[0]
        assert first == "C"

    def test_unknown_sort_raises(self):
        c = _client()
        with pytest.raises(ValueError):
            flatten.run(c, execute=False, max_closes=1, sort_by="oops")
