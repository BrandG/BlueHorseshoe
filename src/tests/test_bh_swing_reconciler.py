"""Tests for bh_swing.trading.reconciler — IBKR mocked, no live gateway."""
from unittest.mock import MagicMock

import pytest

from bh_swing import journal
from bh_swing.trading import reconciler


@pytest.fixture
def temp_journal(tmp_path, monkeypatch):
    p = tmp_path / "bh_swing_journal.csv"
    monkeypatch.setattr(journal, "JOURNAL_PATH", str(p))
    return str(p)


def _mock_client(fills):
    client = MagicMock()
    client.get_executions.return_value = fills
    return client


class TestReconcile:
    def test_emits_one_row_per_new_fill(self, temp_journal):
        client = _mock_client([
            {"exec_id": "X1", "symbol": "AAPL", "side": "BOT",
             "quantity": 10, "price": 150.0, "order_id": 42, "exec_time": "20260512-13:30:00"},
            {"exec_id": "X2", "symbol": "MSFT", "side": "SLD",
             "quantity": 5, "price": 410.5, "order_id": 43, "exec_time": "20260512-13:31:00"},
        ])
        result = reconciler.reconcile(client, run_mode="live", nav=10000, settled_cash=8000)
        assert result == {"fills_seen": 2, "fills_new": 2, "dup_skipped": 0}
        rows = journal.read_recent()
        assert len(rows) == 2
        events = {r["event"] for r in rows}
        assert events == {"fill_detected"}

    def test_dedupes_known_exec_ids(self, temp_journal):
        # Pre-seed an exec_id; reconciler should skip it the second time.
        journal.append(journal.JournalRow(
            run_mode="live", event="fill_detected", exec_id="X1",
        ))
        client = _mock_client([
            {"exec_id": "X1", "symbol": "AAPL", "side": "BOT",
             "quantity": 10, "price": 150.0, "order_id": 42, "exec_time": ""},
            {"exec_id": "X2", "symbol": "AAPL", "side": "BOT",
             "quantity": 10, "price": 151.0, "order_id": 42, "exec_time": ""},
        ])
        result = reconciler.reconcile(client)
        assert result["fills_new"] == 1
        assert result["dup_skipped"] == 1

    def test_normalizes_side_codes(self, temp_journal):
        client = _mock_client([
            {"exec_id": "A", "symbol": "X", "side": "BOT", "quantity": 1, "price": 1.0},
            {"exec_id": "B", "symbol": "X", "side": "SLD", "quantity": 1, "price": 1.0},
            {"exec_id": "C", "symbol": "X", "side": "BUY", "quantity": 1, "price": 1.0},
            {"exec_id": "D", "symbol": "X", "side": "sell", "quantity": 1, "price": 1.0},
        ])
        reconciler.reconcile(client)
        rows = sorted(journal.read_recent(), key=lambda r: r["exec_id"])
        sides = [r["side"] for r in rows]
        assert sides == ["buy", "sell", "buy", "sell"]

    def test_skips_fills_without_exec_id(self, temp_journal):
        client = _mock_client([
            {"exec_id": "", "symbol": "X", "side": "BOT", "quantity": 1, "price": 1.0},
            {"exec_id": "Y", "symbol": "X", "side": "BOT", "quantity": 1, "price": 1.0},
        ])
        result = reconciler.reconcile(client)
        assert result["fills_new"] == 1

    def test_no_fills_writes_no_rows(self, temp_journal):
        client = _mock_client([])
        result = reconciler.reconcile(client)
        assert result == {"fills_seen": 0, "fills_new": 0, "dup_skipped": 0}
        assert journal.read_recent() == []


class TestSnapshotAccount:
    def test_returns_tuple_of_account_positions_trades(self):
        client = MagicMock()
        client.get_account_summary.return_value = {"net_liquidation": 1000.0}
        client.get_positions.return_value = [{"symbol": "AAPL", "position": 10}]
        client.get_open_trades.return_value = ["trade1", "trade2"]
        account, positions, trades = reconciler.snapshot_account(client)
        assert account == {"net_liquidation": 1000.0}
        assert positions == [{"symbol": "AAPL", "position": 10}]
        assert trades == ["trade1", "trade2"]
