"""Tests for the opt-in intraday risk overlay."""

from __future__ import annotations

from datetime import datetime

from bh_ftmo.backtest.risk_overlay import RiskOverlay, RiskOverlayConfig
from bh_ftmo.backtest.types import Position


FTMO_CONFIG = {"daily_loss_pct": 0.05}


def _position(position_id: int, risk: float = 1_000.0) -> Position:
    return Position(
        id=position_id,
        symbol="EUR_USD",
        strategy="sandbox_v1",
        direction=1,
        open_ts=datetime(2026, 1, 12, 10, 0),
        open_price=1.1000,
        stop=1.0900,
        target=1.1200,
        lots=1.0,
        risk_at_open_account_ccy=risk,
    )


def _overlay(*, enabled: bool = True, buffer_mult: float = 1.10, soft_daily_limit: float = -0.04) -> RiskOverlay:
    return RiskOverlay(
        RiskOverlayConfig(enabled=enabled, buffer_mult=buffer_mult, soft_daily_limit=soft_daily_limit),
        FTMO_CONFIG,
        start_equity=100_000.0,
    )


def test_entry_restraint_blocks_when_buffer_exceeded() -> None:
    overlay = _overlay()
    overlay.on_position_closed(-2_000.0)

    assert overlay.should_block_entry({1: _position(1, 2_500.0)}, 1_000.0) is True


def test_entry_restraint_allows_when_buffer_safe() -> None:
    overlay = _overlay()
    overlay.on_position_closed(-500.0)

    assert overlay.should_block_entry({1: _position(1, 1_500.0)}, 1_000.0) is False


def test_entry_restraint_buffer_mult_loosens_threshold() -> None:
    strict = _overlay(buffer_mult=1.00)
    loose = _overlay(buffer_mult=1.10)

    open_positions = {1: _position(1, 4_800.0)}

    assert strict.should_block_entry(open_positions, 400.0) is True
    assert loose.should_block_entry(open_positions, 400.0) is False


def test_liquidation_returns_worst_position_first() -> None:
    overlay = _overlay()
    positions = {idx: _position(idx) for idx in (1, 2, 3)}

    assert overlay.positions_to_liquidate(
        positions,
        {1: -100.0, 2: -300.0, 3: -50.0},
        equity_low_now=95_900.0,
    )[0] == 2


def test_liquidation_cascade_closes_until_safe() -> None:
    overlay = _overlay()
    positions = {idx: _position(idx) for idx in (1, 2, 3)}

    assert overlay.positions_to_liquidate(
        positions,
        {1: -700.0, 2: -500.0, 3: -100.0},
        equity_low_now=94_900.0,
    ) == [1, 2]


def test_liquidation_returns_empty_when_above_soft_limit() -> None:
    overlay = _overlay()

    assert overlay.positions_to_liquidate({1: _position(1)}, {1: -1_000.0}, equity_low_now=96_100.0) == []


def test_disabled_overlay_is_noop() -> None:
    overlay = _overlay(enabled=False)

    assert overlay.should_block_entry({1: _position(1, 10_000.0)}, 10_000.0) is False
    assert overlay.positions_to_liquidate({1: _position(1)}, {1: -10_000.0}, equity_low_now=90_000.0) == []


def test_session_reset_clears_daily_realized_pnl() -> None:
    overlay = _overlay()
    overlay.on_position_closed(-2_000.0)

    overlay.on_session_reset(datetime(2026, 1, 13, 0, 0), 99_000.0)

    assert overlay.daily_realized_pnl == 0.0
    assert overlay.day_start_equity == 99_000.0
