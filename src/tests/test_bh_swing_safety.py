"""Tests for bh_swing.trading.safety — pure-function safety gates."""
import os

import pytest

from bh_swing.trading import safety


class TestStopMoveIsTightening:
    def test_long_raising_stop_allowed(self):
        ok, reason = safety.stop_move_is_tightening(98.0, 100.0, "long")
        assert ok is True
        assert "tightens" in reason

    def test_long_lowering_stop_refused(self):
        ok, reason = safety.stop_move_is_tightening(100.0, 95.0, "long")
        assert ok is False
        assert "would not tighten" in reason

    def test_long_equal_stop_refused(self):
        # No-op is not a tightening; refuse so the monitor doesn't spam IBKR
        ok, _ = safety.stop_move_is_tightening(100.0, 100.0, "long")
        assert ok is False

    def test_short_lowering_stop_allowed(self):
        ok, _ = safety.stop_move_is_tightening(102.0, 100.0, "short")
        assert ok is True

    def test_short_raising_stop_refused(self):
        ok, _ = safety.stop_move_is_tightening(100.0, 102.0, "short")
        assert ok is False

    def test_zero_or_negative_proposed_refused(self):
        assert safety.stop_move_is_tightening(100.0, 0.0, "long")[0] is False
        assert safety.stop_move_is_tightening(100.0, -1.0, "long")[0] is False

    def test_unknown_side_refused(self):
        ok, reason = safety.stop_move_is_tightening(100.0, 102.0, "foo")
        assert ok is False
        assert "unknown side" in reason.lower()


class TestActionsUnderRateLimit:
    def test_under_cap_allowed(self):
        ok, _ = safety.actions_under_rate_limit(0, cap=3)
        assert ok is True
        ok, _ = safety.actions_under_rate_limit(2, cap=3)
        assert ok is True

    def test_at_cap_refused(self):
        ok, reason = safety.actions_under_rate_limit(3, cap=3)
        assert ok is False
        assert "rate limit" in reason.lower()

    def test_over_cap_refused(self):
        ok, _ = safety.actions_under_rate_limit(10, cap=3)
        assert ok is False

    def test_default_cap_is_three(self):
        # Sanity-check the documented default
        assert safety.DEFAULT_ACTION_RATE_LIMIT == 3

    def test_negative_counter_refused(self):
        ok, _ = safety.actions_under_rate_limit(-1, cap=3)
        assert ok is False


class TestPositionCountUnderCap:
    def test_count_below_cap_allowed(self):
        ok, _ = safety.position_count_under_cap([1, 2, 3], cap=10)
        assert ok is True

    def test_count_at_cap_allowed(self):
        ok, _ = safety.position_count_under_cap(list(range(10)), cap=10)
        assert ok is True

    def test_count_over_cap_refused(self):
        ok, reason = safety.position_count_under_cap(list(range(11)), cap=10)
        assert ok is False
        assert "exceeds cap" in reason

    def test_empty_allowed(self):
        ok, _ = safety.position_count_under_cap([], cap=10)
        assert ok is True


class TestKillSwitch:
    def test_no_file_allowed(self, tmp_path):
        path = tmp_path / "missing-sentinel"
        ok, reason = safety.kill_switch_inactive(str(path))
        assert ok is True
        assert "clear" in reason

    def test_file_present_refused(self, tmp_path):
        path = tmp_path / "kill-me"
        path.write_text("paused")
        ok, reason = safety.kill_switch_inactive(str(path))
        assert ok is False
        assert "kill switch active" in reason

    def test_default_path_in_repo_root(self):
        assert safety.KILL_SWITCH_PATH.endswith(".bh_swing_pause_management")
