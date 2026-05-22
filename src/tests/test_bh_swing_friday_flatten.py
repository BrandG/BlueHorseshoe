"""Tests for bh_swing.operator.friday_flatten — day-of-week gate, kill
switch, --force override, --dry-run, journal event names."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from bh_swing.operator import flatten, friday_flatten


@pytest.fixture(autouse=True)
def temp_journal(tmp_path, monkeypatch):
    p = tmp_path / "bh_swing_flatten_journal.csv"
    monkeypatch.setattr(flatten, "JOURNAL_PATH", str(p))
    return str(p)


@pytest.fixture
def no_kill_switch(tmp_path, monkeypatch):
    """Point KILL_SWITCH_PATH at a guaranteed-missing path."""
    monkeypatch.setattr(friday_flatten, "KILL_SWITCH_PATH",
                        str(tmp_path / "missing"))


@pytest.fixture
def fake_client(monkeypatch):
    """Patch IBKRClient construction inside friday_flatten.main so the test
    doesn't need a real broker. Returns the MagicMock instance that the
    code under test will use."""
    instance = MagicMock()
    instance.get_positions.return_value = []
    instance.get_open_trades.return_value = []
    fake_class = MagicMock(return_value=instance)
    monkeypatch.setattr(friday_flatten, "IBKRClient", fake_class)
    return instance


class TestFridayCheck:
    def test_returns_true_on_friday(self):
        # 2026-05-22 is a Friday
        d = datetime(2026, 5, 22, 12, 0, 0)
        assert friday_flatten.is_friday_in_ny(d) is True

    def test_returns_false_on_thursday(self):
        d = datetime(2026, 5, 21, 12, 0, 0)
        assert friday_flatten.is_friday_in_ny(d) is False

    def test_returns_false_on_saturday(self):
        d = datetime(2026, 5, 23, 12, 0, 0)
        assert friday_flatten.is_friday_in_ny(d) is False


class TestDayOfWeekGate:
    def test_skips_when_not_friday(self, fake_client, no_kill_switch,
                                    monkeypatch, capsys):
        monkeypatch.setattr(friday_flatten, "is_friday_in_ny", lambda: False)
        rc = friday_flatten.main([])
        assert rc == 0
        # Should NOT have connected/disconnected; instance must be untouched
        fake_client.get_positions.assert_not_called()
        out = capsys.readouterr().out
        assert "not Friday" in out

    def test_force_bypasses_day_gate(self, fake_client, no_kill_switch,
                                      monkeypatch, capsys):
        monkeypatch.setattr(friday_flatten, "is_friday_in_ny", lambda: False)
        rc = friday_flatten.main(["--force"])
        assert rc == 0
        # Force bypasses gate → flatten.run is reached → broker calls happen
        fake_client.get_positions.assert_called()

    def test_runs_on_friday_without_force(self, fake_client, no_kill_switch,
                                            monkeypatch):
        monkeypatch.setattr(friday_flatten, "is_friday_in_ny", lambda: True)
        rc = friday_flatten.main([])
        assert rc == 0
        fake_client.get_positions.assert_called()


class TestKillSwitch:
    def test_exits_zero_when_kill_switch_present(self, tmp_path, fake_client,
                                                   monkeypatch, capsys):
        kill = tmp_path / "kill"
        kill.write_text("")
        monkeypatch.setattr(friday_flatten, "KILL_SWITCH_PATH", str(kill))
        monkeypatch.setattr(friday_flatten, "is_friday_in_ny", lambda: True)
        rc = friday_flatten.main([])
        assert rc == 0
        fake_client.get_positions.assert_not_called()
        assert "kill switch" in capsys.readouterr().out


class TestDryRun:
    def test_dry_run_does_not_mutate(self, fake_client, no_kill_switch,
                                       monkeypatch):
        monkeypatch.setattr(friday_flatten, "is_friday_in_ny", lambda: True)
        fake_client.get_positions.return_value = [
            {"symbol": "AAPL", "position": 10, "avg_cost": 150.0},
        ]
        fake_client.get_quote.side_effect = lambda s: MagicMock(last=148.0, close=148.0)
        rc = friday_flatten.main(["--dry-run"])
        assert rc == 0
        fake_client.cancel_order.assert_not_called()
        fake_client.place_market_order.assert_not_called()


class TestEventNames:
    def test_executed_close_journals_friday_flatten_event(
        self, fake_client, no_kill_switch, monkeypatch, temp_journal
    ):
        monkeypatch.setattr(friday_flatten, "is_friday_in_ny", lambda: True)
        fake_trade = MagicMock()
        fake_trade.contract.symbol = "AAPL"
        fake_trade.order.orderId = 42
        fake_client.get_positions.return_value = [
            {"symbol": "AAPL", "position": 10, "avg_cost": 150.0},
        ]
        fake_client.get_open_trades.return_value = [fake_trade]
        fake_client.get_quote.side_effect = lambda s: MagicMock(last=148.0, close=148.0)
        fake_client.cancel_order.return_value = {"status": "cancelling", "error": None}
        fake_client.place_market_order.return_value = {
            "order_id": 999, "status": "submitted", "error": None,
        }
        rc = friday_flatten.main([])
        assert rc == 0
        with open(temp_journal) as f:
            content = f.read()
        # Distinct event name lands in the journal (not "position_flattened")
        assert "friday_flatten" in content
        assert "position_flattened" not in content

    def test_dry_run_journals_friday_flatten_proposed(
        self, fake_client, no_kill_switch, monkeypatch, temp_journal
    ):
        monkeypatch.setattr(friday_flatten, "is_friday_in_ny", lambda: True)
        fake_client.get_positions.return_value = [
            {"symbol": "AAPL", "position": 10, "avg_cost": 150.0},
        ]
        fake_client.get_quote.side_effect = lambda s: MagicMock(last=148.0, close=148.0)
        rc = friday_flatten.main(["--dry-run"])
        assert rc == 0
        with open(temp_journal) as f:
            content = f.read()
        assert "friday_flatten_proposed" in content
        assert "would_close" not in content
