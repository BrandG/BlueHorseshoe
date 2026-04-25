"""Unit tests for portfolio-level event ordering."""

from __future__ import annotations

# pylint: disable=missing-function-docstring

from datetime import datetime

import pandas as pd

from bh_ftmo.backtest.event_queue import collect_and_sort
from bh_ftmo.backtest.types import ExitEvent, Position



def _position(position_id: int, symbol: str) -> Position:
    return Position(
        id=position_id,
        symbol=symbol,
        strategy="baseline",
        direction=1,
        open_ts=datetime(2026, 4, 25, 8, 0),
        open_price=1.10,
        stop=1.09,
        target=1.12,
        lots=1.0,
    )



def test_collect_and_sort_orders_earlier_timestamp_first(monkeypatch):
    positions = [_position(1, "USD_JPY"), _position(2, "EUR_USD")]

    def fake_extract(position, bar_4h, bars_1h, pip_size):
        del bar_4h, bars_1h, pip_size
        if position.symbol == "USD_JPY":
            return [ExitEvent(datetime(2026, 4, 25, 18, 0), position.symbol, "stop", 149.0, position.id)]
        return [ExitEvent(datetime(2026, 4, 25, 19, 30), position.symbol, "target", 1.11, position.id)]

    monkeypatch.setattr("bh_ftmo.backtest.intrabar.extract_events", fake_extract)
    events = collect_and_sort(
        positions,
        bar_4h_by_symbol={symbol: pd.Series(dtype=float) for symbol in ["USD_JPY", "EUR_USD"]},
        bars_1h_by_symbol={symbol: pd.DataFrame() for symbol in ["USD_JPY", "EUR_USD"]},
        pip_sizes={"USD_JPY": 0.01, "EUR_USD": 0.0001},
    )
    assert [event.symbol for event in events] == ["USD_JPY", "EUR_USD"]



def test_collect_and_sort_same_timestamp_uses_symbol_alphabetical(monkeypatch):
    positions = [_position(1, "USD_JPY"), _position(2, "EUR_USD")]

    def fake_extract(position, bar_4h, bars_1h, pip_size):
        del bar_4h, bars_1h, pip_size
        return [ExitEvent(datetime(2026, 4, 25, 18, 0), position.symbol, "target", 1.0, position.id)]

    monkeypatch.setattr("bh_ftmo.backtest.intrabar.extract_events", fake_extract)
    events = collect_and_sort(
        positions,
        bar_4h_by_symbol={symbol: pd.Series(dtype=float) for symbol in ["USD_JPY", "EUR_USD"]},
        bars_1h_by_symbol={symbol: pd.DataFrame() for symbol in ["USD_JPY", "EUR_USD"]},
        pip_sizes={"USD_JPY": 0.01, "EUR_USD": 0.0001},
    )
    assert [event.symbol for event in events] == ["EUR_USD", "USD_JPY"]



def test_collect_and_sort_same_symbol_puts_stop_before_target(monkeypatch):
    positions = [_position(1, "EUR_USD")]

    def fake_extract(position, bar_4h, bars_1h, pip_size):
        del position, bar_4h, bars_1h, pip_size
        return [
            ExitEvent(datetime(2026, 4, 25, 18, 0), "EUR_USD", "target", 1.12, 1),
            ExitEvent(datetime(2026, 4, 25, 18, 0), "EUR_USD", "stop", 1.09, 1),
        ]

    monkeypatch.setattr("bh_ftmo.backtest.intrabar.extract_events", fake_extract)
    events = collect_and_sort(
        positions,
        bar_4h_by_symbol={"EUR_USD": pd.Series(dtype=float)},
        bars_1h_by_symbol={"EUR_USD": pd.DataFrame()},
        pip_sizes={"EUR_USD": 0.0001},
    )
    assert [event.kind for event in events] == ["stop", "target"]



def test_collect_and_sort_no_positions_returns_empty():
    assert collect_and_sort([], {}, {}, {}) == []
