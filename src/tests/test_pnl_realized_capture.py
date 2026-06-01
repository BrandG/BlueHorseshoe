"""Tests for BH Swing realized P&L capture from IBKR executions."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bluehorseshoe.data.ibkr_client import IBKRClient
from bh_swing import journal
from bh_swing.trading import reconciler


class _ExecutionFilter:
    time = ""


@pytest.fixture
def temp_journal(tmp_path, monkeypatch):
    p = tmp_path / "bh_swing_journal.csv"
    monkeypatch.setattr(journal, "JOURNAL_PATH", str(p))
    return str(p)


def _fill(exec_id, realized_pnl):
    return SimpleNamespace(
        execution=SimpleNamespace(
            execId=exec_id,
            side="SLD",
            shares=1,
            price=100.0,
            time="20260601-14:30:00",
            orderId=42,
        ),
        contract=SimpleNamespace(symbol="AAPL"),
        commissionReport=SimpleNamespace(
            commission=1.23,
            realizedPNL=realized_pnl,
        ),
    )


def test_get_executions_realized_pnl_passthrough_and_sentinel_guard(monkeypatch):
    fake_ib_async = SimpleNamespace(ExecutionFilter=_ExecutionFilter)
    monkeypatch.setitem(__import__("sys").modules, "ib_async", fake_ib_async)

    client = IBKRClient()
    client._ensure_connected = MagicMock()  # pylint: disable=protected-access
    client._ib = MagicMock()  # pylint: disable=protected-access
    client._ib.reqExecutions.return_value = [  # pylint: disable=protected-access
        _fill("OPEN1", 1.8e308),
        _fill("CLOSE1", -12.34),
    ]

    executions = client.get_executions()

    assert executions[0]["realized_pnl"] == 0.0
    assert executions[1]["realized_pnl"] == -12.34


def test_reconciler_writes_realized_pnl_to_journal(temp_journal):
    client = MagicMock()
    client.get_executions.return_value = [{
        "exec_id": "CLOSE1",
        "symbol": "AAPL",
        "side": "SLD",
        "quantity": 10,
        "price": 100.0,
        "order_id": 42,
        "exec_time": "20260601-14:30:00",
        "realized_pnl": -12.34,
    }]

    reconciler.reconcile(client)

    rows = journal.read_recent()
    assert len(rows) == 1
    assert rows[0]["side"] == "sell"
    assert float(rows[0]["pnl"]) == -12.34
