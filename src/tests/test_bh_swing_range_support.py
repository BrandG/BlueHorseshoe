"""Phase C: range_support up-day ratchet + ~25-bar time flatten in bh_swing.

Pure-rule tests (propose_stop_ratchet / propose_time_flatten) plus manager-block tests that
monkeypatch _daily_features so no DuckDB is needed. Mirrors test_bh_swing_manager.py style.
"""
from unittest.mock import MagicMock

import pytest

from bh_swing import journal
from bh_swing.analysis import position_state as ps, stop_rules
from bh_swing.analysis.position_state import BracketLeg, BrokerOrderView, ManagedPosition
from bh_swing.trading import manager


@pytest.fixture
def temp_journal(tmp_path, monkeypatch):
    p = tmp_path / "bh_swing_journal.csv"
    monkeypatch.setattr(journal, "JOURNAL_PATH", str(p))
    return str(p)


def _stop_view(order_id, stp, status="PreSubmitted"):
    return BrokerOrderView(
        order_id=order_id, symbol="AAPL", action="SELL", order_type="STP",
        limit_price=0.0, stop_price=stp, status=status, filled_qty=0, remaining_qty=10,
    )


def _range_support_position(entry=50.0, stop=48.0, qty=10, stop_order_id=99,
                            entry_dt="2026-05-01", stop_status="PreSubmitted"):
    """A live range_support position: single no-TP leg (recorded as T2) with a working stop."""
    entry_v = BrokerOrderView(
        order_id=1, symbol="AAPL", action="BUY", order_type="LMT", limit_price=entry,
        stop_price=0.0, status="Filled", filled_qty=qty, remaining_qty=0,
    )
    leg = BracketLeg(
        leg="T2", quantity=qty, entry_price=entry, take_profit_price=0.0, stop_loss_price=stop,
        entry_order=entry_v, take_profit_order=None, stop_order=_stop_view(stop_order_id, stop, stop_status),
    )
    return ManagedPosition(
        symbol="AAPL", idea_id="idea_2026-05-01_AAPL_range_support", side="long",
        entry_price=entry, target_price=0.0, original_stop_price=stop, legs=[leg],
        broker_position_qty=qty, broker_avg_cost=entry,
        strategy="range_support", entry_datetime=entry_dt,
    )


def _mock_build(monkeypatch, positions):
    result = ps.BuildResult(managed=positions, unmanaged_symbols=[], drift_notes=[])
    monkeypatch.setattr(ps, "build_managed_positions", lambda *a, **kw: result)


def _patch_feats(monkeypatch, **feats):
    base = {"last_close": 50.0, "prior_close": 50.0, "atr": 1.0,
            "bars_since_entry": 0, "last_date": "2026-06-19"}
    base.update(feats)
    monkeypatch.setattr(manager, "_daily_features", lambda *a, **kw: base)


def _run(client, positions, monkeypatch, **cfg_kw):
    _mock_build(monkeypatch, positions)
    cfg = manager.ManageConfig(kill_switch_path="/tmp/never-exists", store=object(), **cfg_kw)
    return manager.manage_tick(
        client=client, broker_positions=[{"symbol": "AAPL", "position": 10, "avg_cost": 50.0}],
        broker_open_trades=[], trade_orders_collection=MagicMock(), config=cfg,
    )


# ── pure rules ────────────────────────────────────────────────────────

class TestRatchetRule:
    def test_up_day_proposes_close_minus_2atr(self):
        pos = _range_support_position(stop=48.0)
        adv = stop_rules.propose_stop_ratchet(pos, last_close=55.0, prior_close=54.0, atr=1.0, ratchet_atr=2.0)
        assert adv is not None
        assert adv.new_stop == 53.0          # 55 - 2*1
        assert adv.order_id == 99

    def test_down_day_no_op(self):
        pos = _range_support_position(stop=48.0)
        assert stop_rules.propose_stop_ratchet(pos, last_close=53.0, prior_close=54.0, atr=1.0) is None

    def test_ratchet_only_never_lowers(self):
        pos = _range_support_position(stop=54.0)        # current stop already above close-2ATR
        assert stop_rules.propose_stop_ratchet(pos, last_close=55.0, prior_close=54.0, atr=1.0) is None

    def test_short_side_ignored(self):
        from dataclasses import replace
        pos = replace(_range_support_position(), side="short")
        assert stop_rules.propose_stop_ratchet(pos, last_close=55.0, prior_close=54.0, atr=1.0) is None


class TestTimeFlattenRule:
    def test_fires_at_cap(self):
        pos = _range_support_position()
        d = stop_rules.propose_time_flatten(pos, bars_since_entry=25, hold_days=25, enabled=True)
        assert d is not None and d.action == stop_rules.ExitAction.CLOSE_NOW

    def test_below_cap_no_op(self):
        pos = _range_support_position()
        assert stop_rules.propose_time_flatten(pos, bars_since_entry=24, hold_days=25, enabled=True) is None

    def test_disabled_no_op(self):
        pos = _range_support_position()
        assert stop_rules.propose_time_flatten(pos, bars_since_entry=99, hold_days=25, enabled=False) is None


# ── manager wiring ────────────────────────────────────────────────────

class TestManagerRatchet:
    def test_dry_run_emits_would_ratchet(self, temp_journal, monkeypatch):
        client = MagicMock()
        _patch_feats(monkeypatch, last_close=55.0, prior_close=54.0, atr=1.0)
        ms = _run(client, [_range_support_position(stop=48.0)], monkeypatch, dry_run=True)
        assert ms.taken == 1
        client.modify_order_stop.assert_not_called()
        events = [r["event"] for r in journal.read_recent()]
        assert "would_ratchet" in events and "stop_ratcheted" not in events

    def test_live_calls_modify_order_stop(self, temp_journal, monkeypatch):
        client = MagicMock()
        client.modify_order_stop.return_value = {"status": "submitted"}
        _patch_feats(monkeypatch, last_close=55.0, prior_close=54.0, atr=1.0)
        ms = _run(client, [_range_support_position(stop=48.0)], monkeypatch, dry_run=False)
        assert ms.taken == 1
        client.modify_order_stop.assert_called_once_with(99, 53.0)
        assert "stop_ratcheted" in [r["event"] for r in journal.read_recent()]

    def test_deep_oversold_position_untouched(self, temp_journal, monkeypatch):
        from dataclasses import replace
        client = MagicMock()
        pos = replace(_range_support_position(stop=48.0),
                      strategy="deep_oversold", idea_id="idea_x_AAPL_deep_oversold")
        _patch_feats(monkeypatch, last_close=55.0, prior_close=54.0, atr=1.0)
        ms = _run(client, [pos], monkeypatch, dry_run=False)
        client.modify_order_stop.assert_not_called()   # range_support block skips other sleeves
        assert "would_ratchet" not in [r["event"] for r in journal.read_recent()]
        assert ms.taken == 0


class TestManagerFlatten:
    def test_dry_run_emits_would_flatten(self, temp_journal, monkeypatch):
        client = MagicMock()
        _patch_feats(monkeypatch, last_close=53.0, prior_close=54.0, bars_since_entry=30)  # down day → no ratchet
        ms = _run(client, [_range_support_position()], monkeypatch,
                  dry_run=True, time_flatten_enabled=True)
        assert ms.taken == 1
        client.place_market_order.assert_not_called()
        assert "would_flatten" in [r["event"] for r in journal.read_recent()]

    def test_live_cancels_stop_then_sells(self, temp_journal, monkeypatch):
        client = MagicMock()
        client.cancel_order.return_value = {"status": "submitted"}
        client.place_market_order.return_value = {"status": "submitted"}
        _patch_feats(monkeypatch, last_close=53.0, prior_close=54.0, bars_since_entry=30)
        ms = _run(client, [_range_support_position(stop_order_id=99)], monkeypatch,
                  dry_run=False, time_flatten_enabled=True)
        assert ms.taken == 1
        client.cancel_order.assert_called_once_with(99)
        client.place_market_order.assert_called_once_with("AAPL", "SELL", 10)
        assert "position_flattened" in [r["event"] for r in journal.read_recent()]

    def test_disabled_does_not_flatten(self, temp_journal, monkeypatch):
        client = MagicMock()
        _patch_feats(monkeypatch, last_close=53.0, prior_close=54.0, bars_since_entry=30)  # down day, no ratchet
        ms = _run(client, [_range_support_position()], monkeypatch,
                  dry_run=False, time_flatten_enabled=False)
        client.place_market_order.assert_not_called()
        assert ms.taken == 0
