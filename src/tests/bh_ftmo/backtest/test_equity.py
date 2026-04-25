"""Unit tests for equity calculations and resampling."""

from __future__ import annotations

# pylint: disable=missing-function-docstring

from datetime import datetime

import pandas as pd
import pytest

from bh_ftmo.backtest.equity import EquityCurve, equity
from bh_ftmo.backtest.types import Position



def _position(symbol: str, direction: int, open_price: float, lots: float) -> Position:
    return Position(
        id=1,
        symbol=symbol,
        strategy="baseline",
        direction=direction,
        open_ts=datetime(2026, 4, 25, 8, 0),
        open_price=open_price,
        stop=open_price - 0.01,
        target=open_price + 0.01,
        lots=lots,
    )



def test_equity_marks_to_market_positions():
    positions = [_position("EUR_USD", 1, 1.1000, 1.0), _position("USD_JPY", -1, 150.00, 2.0)]
    got = equity(
        cash=100_000.0,
        positions=positions,
        bid_at={"EUR_USD": 1.1020, "USD_JPY": 149.80},
        ask_at={"EUR_USD": 1.1022, "USD_JPY": 149.82},
        pip_values={"EUR_USD": 10.0, "USD_JPY": 6.67},
    )
    eur_pnl = 20.0 * 10.0 * 1.0
    jpy_pnl = 18.0 * 6.67 * 2.0
    assert got == pytest.approx(100_000.0 + eur_pnl + jpy_pnl)



def test_equity_curve_to_series_and_resample_forward_fill():
    curve = EquityCurve()
    curve.record(datetime(2026, 4, 25, 8, 0), 100_000.0)
    curve.record(datetime(2026, 4, 25, 10, 0), 100_100.0)

    series = curve.to_series()
    assert list(series.index) == [pd.Timestamp("2026-04-25 08:00:00"), pd.Timestamp("2026-04-25 10:00:00")]

    resampled = curve.resample_1h()
    assert list(resampled.index) == [
        pd.Timestamp("2026-04-25 08:00:00"),
        pd.Timestamp("2026-04-25 09:00:00"),
        pd.Timestamp("2026-04-25 10:00:00"),
    ]
    assert resampled.iloc[1] == pytest.approx(100_000.0)
    assert resampled.iloc[2] == pytest.approx(100_100.0)
