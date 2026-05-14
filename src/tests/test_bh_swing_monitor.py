"""Integration tests for bh_swing_monitor entrypoint.

Verifies the monitor's branching on broker reachability without standing up a
real IB Gateway.
"""
from unittest.mock import MagicMock, patch

import pytest

import bh_swing_monitor
from bh_swing import journal


@pytest.fixture
def temp_journal(tmp_path, monkeypatch):
    p = tmp_path / "bh_swing_journal.csv"
    monkeypatch.setattr(journal, "JOURNAL_PATH", str(p))
    return str(p)


@pytest.fixture
def fake_client():
    """A MagicMock IBKRClient that returns broker-reachable defaults."""
    client = MagicMock()
    client.get_account_summary.return_value = {
        "account_id": "DUE000001",
        "net_liquidation": 10000.0,
        "settled_cash": 5000.0,
        "available_funds": 5000.0,
        "buying_power": 20000.0,
        "total_cash_value": 5000.0,
        "gross_position_value": 0.0,
    }
    client.get_positions.return_value = []
    client.get_open_trades.return_value = []
    client.get_executions.return_value = []
    return client


class TestMonitorHappyPath:
    def test_emits_run_start_and_run_end_when_broker_reachable(
        self, temp_journal, fake_client, tmp_path, monkeypatch
    ):
        # Redirect tracker output so we don't clobber the real one.
        from bh_swing.trading import tracker_html
        monkeypatch.setattr(tracker_html, "TRACKER_PATH", str(tmp_path / "tracker.html"))

        with patch.object(bh_swing_monitor, "_build_client", return_value=fake_client):
            rc = bh_swing_monitor.main(["-v"])

        assert rc == 0
        events = [r["event"] for r in journal.read_recent()]
        assert journal.EVENT_RUN_START in events
        assert journal.EVENT_RUN_END in events
        assert journal.EVENT_RUN_ERROR not in events


class TestMonitorBrokerUnreachable:
    def test_journals_run_error_and_exits_nonzero_when_account_id_blank(
        self, temp_journal, fake_client, tmp_path, monkeypatch
    ):
        # Simulate IBKRClient's "connection failed" return value.
        fake_client.get_account_summary.return_value = {
            "account_id": "",
            "net_liquidation": 0.0,
            "settled_cash": 0.0,
            "available_funds": 0.0,
            "buying_power": 0.0,
            "total_cash_value": 0.0,
            "gross_position_value": 0.0,
        }

        # Make sure failure mode doesn't render — tracker file should stay absent.
        from bh_swing.trading import tracker_html
        tracker_path = tmp_path / "tracker.html"
        monkeypatch.setattr(tracker_html, "TRACKER_PATH", str(tracker_path))

        with patch.object(bh_swing_monitor, "_build_client", return_value=fake_client):
            rc = bh_swing_monitor.main([])

        assert rc == 2
        events = [r["event"] for r in journal.read_recent()]
        assert journal.EVENT_RUN_ERROR in events
        # run_end should NOT appear — failure exits before that point.
        assert journal.EVENT_RUN_END not in events
        # Tracker file should NOT have been rendered (preserves last-known-good).
        assert not tracker_path.exists()
        # Reconciler should NOT have been queried on the failure path.
        fake_client.get_executions.assert_not_called()

    def test_run_error_note_identifies_root_cause(self, temp_journal, fake_client, monkeypatch):
        fake_client.get_account_summary.return_value = {"account_id": ""}
        from bh_swing.trading import tracker_html
        monkeypatch.setattr(tracker_html, "TRACKER_PATH", "/tmp/should-not-exist.html")

        with patch.object(bh_swing_monitor, "_build_client", return_value=fake_client):
            bh_swing_monitor.main([])

        err_rows = [r for r in journal.read_recent() if r["event"] == journal.EVENT_RUN_ERROR]
        assert err_rows, "expected run_error row"
        assert "broker unreachable" in err_rows[0]["note"].lower()
