"""Unit tests for swap-charge helpers."""

from __future__ import annotations

# pylint: disable=missing-function-docstring

from datetime import date, datetime

import pytest

from bh_ftmo.backtest.swap import SwapRates, apply_swap_to_positions, daily_swap_charge, is_wednesday
from bh_ftmo.backtest.types import Position



def _position(direction: int, position_id: int = 1) -> Position:
    return Position(
        id=position_id,
        symbol="EUR_USD",
        strategy="baseline",
        direction=direction,
        open_ts=datetime(2026, 4, 20, 0, 0),
        open_price=1.10,
        stop=1.09,
        target=1.12,
        lots=2.0,
        risk_at_open_account_ccy=200.0,
    )



def test_is_wednesday():
    assert is_wednesday(date(2026, 4, 22)) is True
    assert is_wednesday(date(2026, 4, 23)) is False



def test_daily_swap_charge_non_wednesday_uses_single_multiplier():
    charge = daily_swap_charge(_position(1), SwapRates(long_rate=-1.5, short_rate=0.5), date(2026, 4, 21))
    assert charge == pytest.approx(-3.0)



def test_daily_swap_charge_wednesday_uses_triple_multiplier():
    charge = daily_swap_charge(_position(1), SwapRates(long_rate=-1.5, short_rate=0.5), date(2026, 4, 22))
    assert charge == pytest.approx(-9.0)



def test_daily_swap_charge_short_direction_uses_short_rate():
    charge = daily_swap_charge(_position(-1), SwapRates(long_rate=-1.5, short_rate=0.5), date(2026, 4, 21))
    assert charge == pytest.approx(1.0)



def test_apply_swap_to_positions_returns_id_keyed_mapping():
    positions = [_position(1, 1), _position(-1, 2)]
    rates = {"EUR_USD": SwapRates(long_rate=-1.0, short_rate=0.25)}
    got = apply_swap_to_positions(positions, rates, date(2026, 4, 21))
    assert got == {1: -2.0, 2: 0.5}
