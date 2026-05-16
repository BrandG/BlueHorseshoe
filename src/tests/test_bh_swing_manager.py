"""Tests for bh_swing.trading.manager — orchestration logic, mocks only."""
import os
from unittest.mock import MagicMock

import pytest

from bh_swing import journal
from bh_swing.analysis.position_state import (
    BracketLeg, BrokerOrderView, ManagedPosition,
)
from bh_swing.trading import manager


@pytest.fixture
def temp_journal(tmp_path, monkeypatch):
    p = tmp_path / "bh_swing_journal.csv"
    monkeypatch.setattr(journal, "JOURNAL_PATH", str(p))
    return str(p)


def _view(order_id, action="SELL", order_type="STP", lmt=0.0, stp=0.0,
          status="Submitted", filled=0):
    return BrokerOrderView(
        order_id=order_id, symbol="AAPL", action=action, order_type=order_type,
        limit_price=lmt, stop_price=stp, status=status,
        filled_qty=filled, remaining_qty=10 - filled,
    )


def _t1_filled_position(entry=150.0, stop=147.0, t2_stop_order_id=99):
    """A managed position with T1 filled, T2 stop still working at original stop."""
    t1_entry = _view(1, action="BUY", order_type="LMT", lmt=entry, status="Filled", filled=10)
    t1_tp = _view(2, action="SELL", order_type="LMT", lmt=152.0, status="Submitted")
    t1_stop = _view(3, action="SELL", order_type="STP", stp=stop, status="PreSubmitted")
    t1 = BracketLeg(
        leg="T1", quantity=10, entry_price=entry,
        take_profit_price=152.0, stop_loss_price=stop,
        entry_order=t1_entry, take_profit_order=t1_tp, stop_order=t1_stop,
    )

    t2_entry = _view(4, action="BUY", order_type="LMT", lmt=entry, status="Filled", filled=10)
    t2_tp = _view(5, action="SELL", order_type="LMT", lmt=155.0, status="Submitted")
    t2_stop = _view(t2_stop_order_id, action="SELL", order_type="STP",
                    stp=stop, status="PreSubmitted")
    t2 = BracketLeg(
        leg="T2", quantity=10, entry_price=entry,
        take_profit_price=155.0, stop_loss_price=stop,
        entry_order=t2_entry, take_profit_order=t2_tp, stop_order=t2_stop,
    )

    return ManagedPosition(
        symbol="AAPL", idea_id="i", side="long",
        entry_price=entry, target_price=155.0, original_stop_price=stop,
        legs=[t1, t2], broker_position_qty=20, broker_avg_cost=entry,
    )


def _mock_build_managed(monkeypatch, managed_positions, unmanaged=None, drift=None):
    """Patch position_state.build_managed_positions to return our fakes."""
    from bh_swing.analysis import position_state as ps
    result = ps.BuildResult(
        managed=managed_positions,
        unmanaged_symbols=unmanaged or [],
        drift_notes=drift or [],
    )
    monkeypatch.setattr(ps, "build_managed_positions", lambda *a, **kw: result)


def _coll():
    return MagicMock()


class TestGlobalGates:
    def test_kill_switch_halts_pass(self, temp_journal, monkeypatch, tmp_path):
        sentinel = tmp_path / "pause"
        sentinel.write_text("x")
        client = MagicMock()
        _mock_build_managed(monkeypatch, [_t1_filled_position()])

        cfg = manager.ManageConfig(
            dry_run=False, kill_switch_path=str(sentinel),
        )
        ms = manager.manage_tick(
            client=client, broker_positions=[], broker_open_trades=[],
            trade_orders_collection=_coll(), config=cfg,
        )
        assert ms.halted_reason is not None
        assert "kill switch active" in ms.halted_reason
        client.modify_order_stop.assert_not_called()
        events = [r["event"] for r in journal.read_recent()]
        assert "kill_switch_active" in events

    def test_position_cap_exceeded_logs_drift_but_continues(self, temp_journal, monkeypatch):
        """Over-cap is diagnostic only for this orchestrator — risk-reducing
        actions (stop-tightening, early-exit) should still proceed so a
        bloated book doesn't go unmanaged."""
        client = MagicMock()
        _mock_build_managed(monkeypatch, [_t1_filled_position()])

        positions = [{"symbol": f"S{i}", "position": 1, "avg_cost": 1.0} for i in range(11)]
        cfg = manager.ManageConfig(
            dry_run=True, position_count_cap=10,
            kill_switch_path="/tmp/never-exists",
        )
        ms = manager.manage_tick(
            client=client, broker_positions=positions, broker_open_trades=[],
            trade_orders_collection=_coll(), config=cfg,
        )
        # No halt.
        assert ms.halted_reason is None
        # Diagnostic row was written.
        rows = journal.read_recent()
        drift_rows = [r for r in rows if r["event"] == journal.EVENT_STATE_DRIFT]
        assert any("position_cap_exceeded" in r.get("note", "") for r in drift_rows)
        # Management proceeded — proposed advancement made it through.
        assert ms.proposed == 1
        assert ms.taken == 1
        would_events = [r for r in rows if r["event"] == journal.EVENT_WOULD_ADVANCE_STOP]
        assert len(would_events) == 1


class TestDryRunManagement:
    def test_proposed_advancement_emits_would_event(self, temp_journal, monkeypatch):
        client = MagicMock()
        _mock_build_managed(monkeypatch, [_t1_filled_position()])

        cfg = manager.ManageConfig(
            dry_run=True, kill_switch_path="/tmp/never-exists",
        )
        ms = manager.manage_tick(
            client=client, broker_positions=[{"symbol": "AAPL", "position": 20, "avg_cost": 150.0}],
            broker_open_trades=[], trade_orders_collection=_coll(),
            config=cfg,
        )
        assert ms.proposed == 1
        assert ms.taken == 1   # dry-run counts as taken (planned)
        assert ms.failed == 0
        client.modify_order_stop.assert_not_called()
        events = [r["event"] for r in journal.read_recent()]
        assert "action_proposed" in events
        assert "would_advance_stop" in events
        assert "stop_advanced" not in events  # only fires live

    def test_no_action_when_t1_not_filled(self, temp_journal, monkeypatch):
        client = MagicMock()
        # Construct a position with T1 entry NOT filled.
        pos = _t1_filled_position()
        # Mutate to unfilled
        from dataclasses import replace
        unfilled_entry = replace(pos.t1.entry_order, status="Submitted", filled_qty=0)
        unfilled_t1 = replace(pos.t1, entry_order=unfilled_entry)
        pos = replace(pos, legs=[unfilled_t1, pos.t2])
        _mock_build_managed(monkeypatch, [pos])

        cfg = manager.ManageConfig(dry_run=True, kill_switch_path="/tmp/never-exists")
        ms = manager.manage_tick(
            client=client, broker_positions=[{"symbol": "AAPL", "position": 10, "avg_cost": 150.0}],
            broker_open_trades=[], trade_orders_collection=_coll(),
            config=cfg,
        )
        assert ms.proposed == 0
        assert ms.taken == 0


class TestLiveManagement:
    def test_advances_stop_via_client(self, temp_journal, monkeypatch):
        client = MagicMock()
        client.modify_order_stop.return_value = {
            "order_id": 99, "status": "submitted", "error": None,
        }
        _mock_build_managed(monkeypatch, [_t1_filled_position(t2_stop_order_id=99)])

        cfg = manager.ManageConfig(dry_run=False, kill_switch_path="/tmp/never-exists")
        ms = manager.manage_tick(
            client=client, broker_positions=[{"symbol": "AAPL", "position": 20, "avg_cost": 150.0}],
            broker_open_trades=[], trade_orders_collection=_coll(),
            config=cfg,
        )
        assert ms.taken == 1
        assert ms.failed == 0
        client.modify_order_stop.assert_called_once_with(99, 150.0)
        events = [r["event"] for r in journal.read_recent()]
        assert "stop_advanced" in events
        assert "action_taken" in events

    def test_broker_failure_journals_action_failed(self, temp_journal, monkeypatch):
        client = MagicMock()
        client.modify_order_stop.return_value = {
            "order_id": 99, "status": "error", "error": "no route",
        }
        _mock_build_managed(monkeypatch, [_t1_filled_position(t2_stop_order_id=99)])

        cfg = manager.ManageConfig(dry_run=False, kill_switch_path="/tmp/never-exists")
        ms = manager.manage_tick(
            client=client, broker_positions=[{"symbol": "AAPL", "position": 20, "avg_cost": 150.0}],
            broker_open_trades=[], trade_orders_collection=_coll(),
            config=cfg,
        )
        assert ms.taken == 0
        assert ms.failed == 1
        events = [r["event"] for r in journal.read_recent()]
        assert "action_failed" in events
        assert "stop_advanced" not in events


class TestRateLimit:
    def test_rate_limit_skips_excess_actions(self, temp_journal, monkeypatch):
        # Three positions all wanting advancement; cap at 2.
        positions = []
        for i, oid in enumerate([100, 101, 102]):
            p = _t1_filled_position(t2_stop_order_id=oid)
            # Slight per-symbol divergence so they're distinct objects
            from dataclasses import replace
            p = replace(p, symbol=f"AAPL{i}", idea_id=f"i{i}")
            positions.append(p)

        client = MagicMock()
        client.modify_order_stop.return_value = {
            "order_id": 0, "status": "submitted", "error": None,
        }
        _mock_build_managed(monkeypatch, positions)

        cfg = manager.ManageConfig(
            dry_run=False, action_rate_limit=2,
            kill_switch_path="/tmp/never-exists",
        )
        broker_positions = [{"symbol": f"AAPL{i}", "position": 10, "avg_cost": 150.0}
                            for i in range(3)]
        ms = manager.manage_tick(
            client=client, broker_positions=broker_positions,
            broker_open_trades=[], trade_orders_collection=_coll(),
            config=cfg,
        )
        # 3 proposed, but only 2 mutations should fire
        assert ms.proposed == 3
        assert ms.taken == 2
        assert ms.skipped == 1
        assert client.modify_order_stop.call_count == 2


class TestDriftNotes:
    def test_drift_notes_journaled(self, temp_journal, monkeypatch):
        from bh_swing.analysis import position_state as ps
        result = ps.BuildResult(managed=[], unmanaged_symbols=[],
                                drift_notes=["AAPL: weirdness"])
        monkeypatch.setattr(ps, "build_managed_positions", lambda *a, **kw: result)

        cfg = manager.ManageConfig(dry_run=True, kill_switch_path="/tmp/never-exists")
        manager.manage_tick(
            client=MagicMock(), broker_positions=[], broker_open_trades=[],
            trade_orders_collection=_coll(), config=cfg,
        )
        events = [(r["event"], r["note"]) for r in journal.read_recent()]
        assert any(e == "state_drift" and "weirdness" in n for e, n in events)
