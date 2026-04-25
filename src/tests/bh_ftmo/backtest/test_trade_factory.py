"""Unit tests for signal-to-position derivation and admission rules."""

from __future__ import annotations

# pylint: disable=missing-function-docstring

from datetime import datetime

import pandas as pd
import pytest

from bh_ftmo.analysis.strategy import Signal
from bh_ftmo.backtest.calendar_provider import NullCalendarProvider
from bh_ftmo.backtest.trade_factory import can_open, derive_position
from bh_ftmo.backtest.types import PairSpec, Position


class BlackoutCalendar:
    """Small blackout stub for admission-rule tests."""

    def is_blackout(self, ts: datetime, currencies: set[str]) -> bool:
        del ts, currencies
        return True

    def next_blackout_end(self, ts: datetime, currencies: set[str]) -> datetime | None:
        del currencies
        return ts



def _signal(direction: int, symbol: str = "EUR_USD") -> Signal:
    return Signal(
        symbol=symbol,
        strategy="baseline",
        timestamp=datetime(2026, 4, 25, 8, 0),
        direction=direction,
        score=1.0,
        components={"trend": 1.0},
        above_threshold=True,
    )



def _open_position(symbol: str, direction: int) -> Position:
    return Position(
        id=1,
        symbol=symbol,
        strategy="baseline",
        direction=direction,
        open_ts=datetime(2026, 4, 25, 8, 0),
        open_price=1.10,
        stop=1.09,
        target=1.12,
        lots=1.0,
        risk_at_open_account_ccy=100.0,
    )



def test_derive_position_long_uses_open_ask_and_correct_levels():
    next_bar = pd.Series({"timestamp": datetime(2026, 4, 25, 12, 0), "open_bid": 1.1000, "open_ask": 1.1002})
    position = derive_position(
        _signal(1),
        next_bar,
        atr_14=0.0020,
        pair_spec=PairSpec("EUR_USD", 0.0001, 100_000),
        sizing_config={"risk_pct_per_trade": 0.005, "k_stop": 1.5, "k_target": 2.5},
        account_currency="USD",
        current_equity=100_000.0,
        quote_to_account=1.0,
        next_position_id=7,
    )
    assert position is not None
    assert position.open_price == pytest.approx(1.1002)
    assert position.stop == pytest.approx(1.0972)
    assert position.target == pytest.approx(1.1052)
    assert position.lots == pytest.approx(500.0 / (30.0 * 10.0))
    assert position.risk_at_open_account_ccy == pytest.approx(500.0)



def test_derive_position_short_uses_open_bid_and_mirrored_levels():
    next_bar = pd.Series({"timestamp": datetime(2026, 4, 25, 12, 0), "open_bid": 150.00, "open_ask": 150.02})
    position = derive_position(
        _signal(-1, "USD_JPY"),
        next_bar,
        atr_14=0.40,
        pair_spec=PairSpec("USD_JPY", 0.01, 100_000),
        sizing_config={"risk_pct_per_trade": 0.005, "k_stop": 1.5, "k_target": 2.5},
        account_currency="USD",
        current_equity=100_000.0,
        quote_to_account=1.0 / 150.0,
        next_position_id=8,
    )
    assert position is not None
    assert position.open_price == pytest.approx(150.00)
    assert position.stop == pytest.approx(150.60)
    assert position.target == pytest.approx(149.00)
    assert position.risk_at_open_account_ccy == pytest.approx(500.0)



def test_derive_position_returns_none_for_zero_direction():
    next_bar = pd.Series({"timestamp": datetime(2026, 4, 25, 12, 0), "open_bid": 1.0, "open_ask": 1.0})
    assert derive_position(
        _signal(0),
        next_bar,
        atr_14=0.0020,
        pair_spec=PairSpec("EUR_USD", 0.0001, 100_000),
        sizing_config={},
        account_currency="USD",
        current_equity=100_000.0,
        quote_to_account=1.0,
        next_position_id=1,
    ) is None



def test_derive_position_returns_none_for_zero_atr():
    next_bar = pd.Series({"timestamp": datetime(2026, 4, 25, 12, 0), "open_bid": 1.0, "open_ask": 1.0})
    assert derive_position(
        _signal(1),
        next_bar,
        atr_14=0.0,
        pair_spec=PairSpec("EUR_USD", 0.0001, 100_000),
        sizing_config={},
        account_currency="USD",
        current_equity=100_000.0,
        quote_to_account=1.0,
        next_position_id=1,
    ) is None



def test_can_open_missing_1h_data_skip():
    allowed, reason = can_open(_signal(1), [], {}, NullCalendarProvider(), False, datetime(2026, 4, 25, 12, 0))
    assert (allowed, reason) == (False, "missing_1h_data")



def test_can_open_calendar_blackout_skip():
    allowed, reason = can_open(_signal(1), [], {}, BlackoutCalendar(), True, datetime(2026, 4, 25, 12, 0))
    assert (allowed, reason) == (False, "calendar_blackout")



def test_can_open_repeat_same_direction_skip():
    allowed, reason = can_open(_signal(1), [_open_position("EUR_USD", 1)], {}, NullCalendarProvider(), True, datetime(2026, 4, 25, 12, 0))
    assert (allowed, reason) == (False, "repeat_same_direction")



def test_can_open_opposing_direction_skip():
    allowed, reason = can_open(_signal(1), [_open_position("EUR_USD", -1)], {}, NullCalendarProvider(), True, datetime(2026, 4, 25, 12, 0))
    assert (allowed, reason) == (False, "opposing_direction")



def test_can_open_max_positions_skip():
    open_positions = [_open_position("EUR_USD", 1), _open_position("GBP_USD", 1)]
    allowed, reason = can_open(
        _signal(1, "AUD_USD"),
        open_positions,
        {"max_concurrent_positions": 2, "max_concurrent_per_currency": 5, "max_concurrent_per_usd_basket": 5},
        NullCalendarProvider(),
        True,
        datetime(2026, 4, 25, 12, 0),
    )
    assert (allowed, reason) == (False, "max_concurrent_positions")



def test_can_open_max_per_currency_skip():
    open_positions = [_open_position("EUR_USD", 1), _open_position("EUR_JPY", 1)]
    allowed, reason = can_open(
        _signal(1, "EUR_GBP"),
        open_positions,
        {"max_concurrent_positions": 5, "max_concurrent_per_currency": 2, "max_concurrent_per_usd_basket": 5},
        NullCalendarProvider(),
        True,
        datetime(2026, 4, 25, 12, 0),
    )
    assert (allowed, reason) == (False, "max_concurrent_per_currency")



def test_can_open_max_usd_basket_skip():
    open_positions = [_open_position("EUR_USD", 1), _open_position("GBP_USD", 1), _open_position("USD_JPY", 1)]
    allowed, reason = can_open(
        _signal(1, "AUD_USD"),
        open_positions,
        {"max_concurrent_positions": 5, "max_concurrent_per_currency": 5, "max_concurrent_per_usd_basket": 3},
        NullCalendarProvider(),
        True,
        datetime(2026, 4, 25, 12, 0),
    )
    assert (allowed, reason) == (False, "max_concurrent_per_usd_basket")
