"""Unit tests for portfolio-level event ordering."""

from __future__ import annotations

# pylint: disable=missing-function-docstring

from datetime import datetime

import pandas as pd
import pytest

from bh_ftmo.backtest.equity import EquityCurve
from bh_ftmo.backtest.event_queue import apply_in_order, collect_and_sort
from bh_ftmo.backtest.types import ExitEvent, PairSpec, Position, RuleBreach


class StubRuleEngine:
    """Small FTMO rule stub for ordered event tests."""

    def __init__(self, breach_at: datetime | None = None, rule: str = "daily_loss") -> None:
        self.breach_at = breach_at
        self.rule = rule
        self.trade_events: list[datetime] = []
        self.equity_updates: list[tuple[datetime, float]] = []

    def on_trade_event(self, ts: datetime) -> None:
        self.trade_events.append(ts)

    def on_equity_update(self, ts: datetime, equity: float) -> RuleBreach | None:
        self.equity_updates.append((ts, equity))
        if self.breach_at is not None and ts == self.breach_at:
            return RuleBreach(rule=self.rule, timestamp=ts, equity_at_breach=equity, threshold=95_000.0)
        return None



def _position(position_id: int, symbol: str, *, direction: int = 1, open_price: float | None = None) -> Position:
    default_open = 150.0 if symbol == "USD_JPY" else 1.10
    return Position(
        id=position_id,
        symbol=symbol,
        strategy="baseline",
        direction=direction,
        open_ts=datetime(2026, 4, 25, 8, 0),
        open_price=default_open if open_price is None else open_price,
        stop=149.0 if symbol == "USD_JPY" else 1.09,
        target=151.0 if symbol == "USD_JPY" else 1.12,
        lots=1.0,
        risk_at_open_account_ccy=100.0,
    )



def _pip_value_at(ts: datetime, symbol: str) -> float:
    del ts
    return 9.0 if symbol == "USD_JPY" else 10.0



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



def test_apply_in_order_processes_two_events_without_breach():
    positions = {
        1: _position(1, "EUR_USD", open_price=1.1000),
        2: _position(2, "USD_JPY", open_price=150.0),
    }
    events = [
        ExitEvent(datetime(2026, 4, 25, 18, 0), "EUR_USD", "target", 1.1200, 1),
        ExitEvent(datetime(2026, 4, 25, 19, 0), "USD_JPY", "stop", 149.0, 2),
    ]
    rule_engine = StubRuleEngine()
    curve = EquityCurve()

    open_positions_after, cash_after, trades, breach = apply_in_order(
        events=events,
        open_positions=positions,
        cash=100_000.0,
        pip_specs={
            "EUR_USD": PairSpec("EUR_USD", 0.0001, 100_000),
            "USD_JPY": PairSpec("USD_JPY", 0.01, 100_000),
        },
        pip_values_at=_pip_value_at,
        commission_per_lot_round_turn=3.0,
        equity_curve=curve,
        rule_engine=rule_engine,
        bid_at={"EUR_USD": 1.1200, "USD_JPY": 149.0},
        ask_at={"EUR_USD": 1.1202, "USD_JPY": 149.02},
    )

    assert breach is None
    assert not open_positions_after
    assert len(trades) == 2
    assert [trade.exit_reason for trade in trades] == ["target", "stop"]
    assert [trade.close_ts for trade in trades] == [datetime(2026, 4, 25, 18, 0), datetime(2026, 4, 25, 19, 0)]
    assert all(trade.risk_at_open_account_ccy == pytest.approx(100.0) for trade in trades)
    assert rule_engine.trade_events == [datetime(2026, 4, 25, 18, 0), datetime(2026, 4, 25, 19, 0)]
    assert len(curve.to_series()) == 2
    assert cash_after == pytest.approx(100_000.0 + 2000.0 - 1.5 - 900.0 - 1.5)



def test_apply_in_order_stops_after_cross_position_breach():
    positions = {
        1: _position(1, "USD_JPY", open_price=150.0),
        2: _position(2, "EUR_USD", open_price=1.1000),
    }
    events = [
        ExitEvent(datetime(2026, 4, 25, 18, 0), "USD_JPY", "stop", 149.0, 1),
        ExitEvent(datetime(2026, 4, 25, 19, 30), "EUR_USD", "target", 1.1200, 2),
    ]
    rule_engine = StubRuleEngine(breach_at=datetime(2026, 4, 25, 18, 0))

    open_positions_after, cash_after, trades, breach = apply_in_order(
        events=events,
        open_positions=positions,
        cash=95_901.5,
        pip_specs={
            "EUR_USD": PairSpec("EUR_USD", 0.0001, 100_000),
            "USD_JPY": PairSpec("USD_JPY", 0.01, 100_000),
        },
        pip_values_at=_pip_value_at,
        commission_per_lot_round_turn=3.0,
        equity_curve=EquityCurve(),
        rule_engine=rule_engine,
        bid_at={"EUR_USD": 1.1200, "USD_JPY": 149.0},
        ask_at={"EUR_USD": 1.1202, "USD_JPY": 149.02},
    )

    assert breach is not None
    assert breach.rule == "daily_loss"
    assert len(trades) == 1
    assert trades[0].symbol == "USD_JPY"
    assert 2 in open_positions_after
    assert cash_after == pytest.approx(95_901.5 - 900.0 - 1.5)



def test_apply_in_order_maps_weekend_flatten_exit_reason():
    positions = {1: _position(1, "EUR_USD", open_price=1.1000)}
    events = [ExitEvent(datetime(2026, 4, 25, 18, 0), "EUR_USD", "weekend_flatten", 1.1050, 1)]

    _, _, trades, breach = apply_in_order(
        events=events,
        open_positions=positions,
        cash=100_000.0,
        pip_specs={"EUR_USD": PairSpec("EUR_USD", 0.0001, 100_000)},
        pip_values_at=_pip_value_at,
        commission_per_lot_round_turn=3.0,
        equity_curve=EquityCurve(),
        rule_engine=StubRuleEngine(),
        bid_at={"EUR_USD": 1.1050},
        ask_at={"EUR_USD": 1.1052},
    )

    assert breach is None
    assert len(trades) == 1
    assert trades[0].exit_reason == "weekend_flatten"



def test_apply_in_order_rejects_swap_exit_event():
    positions = {1: _position(1, "EUR_USD")}
    events = [ExitEvent(datetime(2026, 4, 25, 18, 0), "EUR_USD", "swap", 1.10, 1)]

    with pytest.raises(ValueError, match="swap ExitEvent"):
        apply_in_order(
            events=events,
            open_positions=positions,
            cash=100_000.0,
            pip_specs={"EUR_USD": PairSpec("EUR_USD", 0.0001, 100_000)},
            pip_values_at=_pip_value_at,
            commission_per_lot_round_turn=3.0,
            equity_curve=EquityCurve(),
            rule_engine=StubRuleEngine(),
            bid_at={"EUR_USD": 1.1000},
            ask_at={"EUR_USD": 1.1002},
        )
