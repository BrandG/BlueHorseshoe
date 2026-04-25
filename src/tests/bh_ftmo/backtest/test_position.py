"""Unit tests for position P&L helpers."""

from __future__ import annotations

# pylint: disable=missing-function-docstring

from datetime import datetime

import pytest

from bh_ftmo.backtest.position import floating_pnl_account_ccy, pip_distance, realized_pnl_account_ccy
from bh_ftmo.backtest.types import Position



def _position(direction: int, price: float = 1.1000) -> Position:
    return Position(
        id=1,
        symbol="EUR_USD",
        strategy="baseline",
        direction=direction,
        open_ts=datetime(2026, 4, 25, 8, 0),
        open_price=price,
        stop=1.0900,
        target=1.1200,
        lots=2.0,
        risk_at_open_account_ccy=200.0,
    )



def test_realized_pnl_long_winner():
    pnl = realized_pnl_account_ccy(_position(1), close_price=1.1050, pip_value=10.0)
    assert pnl == pytest.approx(1000.0)



def test_realized_pnl_short_winner():
    pnl = realized_pnl_account_ccy(_position(-1), close_price=1.0950, pip_value=10.0)
    assert pnl == pytest.approx(1000.0)



def test_floating_pnl_breakeven():
    pnl = floating_pnl_account_ccy(_position(1), bid=1.1000, ask=1.1002, pip_value=10.0)
    assert pnl == pytest.approx(0.0)



def test_pip_distance_major_pair():
    assert pip_distance(1.1000, 1.1015, 0.0001) == pytest.approx(15.0)



def test_pip_distance_jpy_pair():
    assert pip_distance(150.00, 149.75, 0.01) == pytest.approx(-25.0)
