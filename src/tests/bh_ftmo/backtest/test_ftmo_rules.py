"""Unit tests for the FTMO rule engine."""

from __future__ import annotations

# pylint: disable=missing-function-docstring

from datetime import datetime
import json
from pathlib import Path

import pytest

from bh_ftmo.backtest.ftmo_rules import FtmoConfigUnverifiedError, FtmoRuleEngine, load_ftmo_config


BASE_CONFIG = {
    "initial_balance": 100_000.0,
    "account_currency": "USD",
    "phase": "challenge",
    "profit_target_pct": 0.10,
    "daily_loss_pct": 0.05,
    "max_loss_pct": 0.10,
    "max_loss_type": "static",
    "min_trading_days": 4,
    "max_trading_days": 14,
    "server_timezone": "Europe/Prague",
    "commission_per_lot_round_turn": 3.0,
    "swap_model": "standard",
}


def _write_config(tmp_path: Path, ftmo_block: dict) -> Path:
    path = tmp_path / "bh_ftmo_config.json"
    path.write_text(json.dumps({"ftmo": ftmo_block}), encoding="utf-8")
    return path



def _engine(config: dict | None = None, start_ts: datetime | None = None) -> FtmoRuleEngine:
    cfg = dict(BASE_CONFIG if config is None else config)
    ts = datetime(2026, 1, 12, 10, 0) if start_ts is None else start_ts
    return FtmoRuleEngine(cfg, start_equity=100_000.0, start_ts=ts, server_tz=cfg["server_timezone"])



def test_load_ftmo_config_raises_on_missing_field(tmp_path: Path):
    broken = dict(BASE_CONFIG)
    broken.pop("phase")
    with pytest.raises(FtmoConfigUnverifiedError, match="missing required fields"):
        load_ftmo_config(_write_config(tmp_path, broken))



def test_load_ftmo_config_raises_on_placeholder_value(tmp_path: Path):
    broken = dict(BASE_CONFIG)
    broken["swap_model"] = "PLACEHOLDER_STANDARD"
    with pytest.raises(FtmoConfigUnverifiedError, match="PLACEHOLDER"):
        load_ftmo_config(_write_config(tmp_path, broken))



def test_load_ftmo_config_raises_on_invalid_max_loss_type(tmp_path: Path):
    broken = dict(BASE_CONFIG)
    broken["max_loss_type"] = "invalid"
    with pytest.raises(FtmoConfigUnverifiedError, match="max_loss_type"):
        load_ftmo_config(_write_config(tmp_path, broken))



def test_load_ftmo_config_strips_metadata_keys(tmp_path: Path):
    ftmo_block = dict(BASE_CONFIG)
    ftmo_block["_comment"] = "PLACEHOLDER metadata is ignored"
    loaded = load_ftmo_config(_write_config(tmp_path, ftmo_block))
    assert "_comment" not in loaded
    assert loaded["max_loss_type"] == "static"



def test_static_max_loss_breaches_below_threshold():
    engine = _engine()
    breach = engine.on_equity_update(datetime(2026, 1, 12, 11, 0), 89_999.99)
    assert breach is not None
    assert breach.rule == "max_loss"



def test_trailing_max_loss_breaches_after_peak_rise_then_fall():
    config = dict(BASE_CONFIG)
    config["max_loss_type"] = "trailing"
    engine = _engine(config)
    assert engine.on_equity_update(datetime(2026, 1, 12, 11, 0), 105_000.0) is None
    breach = engine.on_equity_update(datetime(2026, 1, 12, 12, 0), 94_499.99)
    assert breach is not None
    assert breach.rule == "max_loss"



def test_static_max_loss_does_not_breach_in_same_rise_then_fall_scenario():
    config = dict(BASE_CONFIG)
    config["daily_loss_pct"] = 0.20
    engine = _engine(config)
    assert engine.on_equity_update(datetime(2026, 1, 12, 11, 0), 105_000.0) is None
    assert engine.on_equity_update(datetime(2026, 1, 12, 12, 0), 94_499.99) is None



def test_daily_loss_breaches_below_reference_minus_limit():
    engine = _engine()
    engine.on_session_reset(datetime(2026, 1, 12, 23, 0), 100_000.0)
    breach = engine.on_equity_update(datetime(2026, 1, 13, 10, 0), 94_999.99)
    assert breach is not None
    assert breach.rule == "daily_loss"



def test_daily_loss_breach_is_instantaneous_even_if_later_recovered():
    engine = _engine()
    engine.on_session_reset(datetime(2026, 1, 12, 23, 0), 100_000.0)
    first = engine.on_equity_update(datetime(2026, 1, 13, 10, 0), 94_999.99)
    second = engine.on_equity_update(datetime(2026, 1, 13, 11, 0), 101_000.0)
    assert first is not None
    assert first.rule == "daily_loss"
    assert second == first



def test_rule_precedence_returns_max_loss_when_both_breach():
    engine = _engine()
    engine.on_session_reset(datetime(2026, 1, 12, 23, 0), 96_000.0)
    breach = engine.on_equity_update(datetime(2026, 1, 13, 10, 0), 89_999.99)
    assert breach is not None
    assert breach.rule == "max_loss"



def test_profit_target_records_hit_without_breach():
    engine = _engine()
    breach = engine.on_equity_update(datetime(2026, 1, 12, 11, 0), 110_000.01)
    assert breach is None
    assert engine.state.target_hit_at == datetime(2026, 1, 12, 11, 0)



def test_is_passed_true_after_target_hit_and_min_trading_days():
    engine = _engine()
    engine.on_equity_update(datetime(2026, 1, 12, 11, 0), 110_000.01)
    for ts in [
        datetime(2026, 1, 12, 11, 0),
        datetime(2026, 1, 13, 11, 0),
        datetime(2026, 1, 14, 11, 0),
        datetime(2026, 1, 15, 11, 0),
    ]:
        engine.on_trade_event(ts)
    assert engine.is_passed() is True



def test_is_passed_false_when_target_hit_but_trading_days_short():
    engine = _engine()
    engine.on_equity_update(datetime(2026, 1, 12, 11, 0), 110_000.01)
    for ts in [datetime(2026, 1, 12, 11, 0), datetime(2026, 1, 13, 11, 0), datetime(2026, 1, 14, 11, 0)]:
        engine.on_trade_event(ts)
    assert engine.is_passed() is False



def test_is_pushed_true_after_max_days_exhausted_without_target():
    engine = _engine()
    engine.on_equity_update(datetime(2026, 1, 27, 11, 0), 100_500.0)
    assert engine.is_pushed() is True



def test_can_open_new_false_after_breach():
    engine = _engine()
    engine.on_equity_update(datetime(2026, 1, 12, 11, 0), 89_999.99)
    assert engine.can_open_new(datetime(2026, 1, 12, 12, 0)) == (False, "breached")



def test_can_open_new_false_past_max_trading_days():
    engine = _engine()
    assert engine.can_open_new(datetime(2026, 1, 27, 11, 0)) == (False, "past_max_trading_days")



def test_can_open_new_false_when_target_already_passed_and_min_days_met():
    engine = _engine()
    engine.on_equity_update(datetime(2026, 1, 12, 11, 0), 110_000.01)
    for ts in [
        datetime(2026, 1, 12, 11, 0),
        datetime(2026, 1, 13, 11, 0),
        datetime(2026, 1, 14, 11, 0),
        datetime(2026, 1, 15, 11, 0),
    ]:
        engine.on_trade_event(ts)
    assert engine.can_open_new(datetime(2026, 1, 15, 12, 0)) == (False, "target_already_passed")



def test_is_session_reset_due_winter_boundary():
    engine = _engine(start_ts=datetime(2026, 1, 12, 22, 0))
    assert engine.is_session_reset_due(datetime(2026, 1, 12, 22, 59)) is False
    assert engine.is_session_reset_due(datetime(2026, 1, 12, 23, 0)) is True



def test_is_session_reset_due_summer_boundary():
    engine = _engine(start_ts=datetime(2026, 7, 12, 21, 0))
    assert engine.is_session_reset_due(datetime(2026, 7, 12, 21, 59)) is False
    assert engine.is_session_reset_due(datetime(2026, 7, 12, 22, 0)) is True



def test_is_session_reset_due_dst_mismatch_week_boundary():
    engine = _engine(start_ts=datetime(2026, 3, 15, 22, 0))
    assert engine.is_session_reset_due(datetime(2026, 3, 15, 22, 59)) is False
    assert engine.is_session_reset_due(datetime(2026, 3, 15, 23, 0)) is True



def test_on_session_reset_uses_post_swap_equity_for_reference():
    engine = _engine(start_ts=datetime(2026, 1, 12, 22, 0))
    engine.on_session_reset(datetime(2026, 1, 12, 23, 0), 99_250.0)
    assert engine.state.reference_equity == pytest.approx(99_250.0)
