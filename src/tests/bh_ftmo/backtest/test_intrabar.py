"""Unit tests for 1h intrabar event extraction."""

from __future__ import annotations

# pylint: disable=missing-function-docstring

from datetime import datetime, timedelta

import pandas as pd

from bh_ftmo.backtest.intrabar import extract_events
from bh_ftmo.backtest.types import Position



def _bars(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)



def _position(direction: int, stop: float, target: float, symbol: str = "EUR_USD") -> Position:
    return Position(
        id=1,
        symbol=symbol,
        strategy="baseline",
        direction=direction,
        open_ts=datetime(2026, 4, 25, 8, 0),
        open_price=1.1000 if symbol == "EUR_USD" else 150.00,
        stop=stop,
        target=target,
        lots=1.0,
        risk_at_open_account_ccy=100.0,
    )



def test_long_stop_hits_in_first_sub_bar():
    ts = datetime(2026, 4, 25, 8, 0)
    bars = _bars([
        {"timestamp": ts, "low_bid": 1.0940, "high_bid": 1.1010, "high_ask": 1.1012, "low_ask": 1.0942},
        {"timestamp": ts + timedelta(hours=1), "low_bid": 1.0980, "high_bid": 1.1020, "high_ask": 1.1022, "low_ask": 1.0982},
    ])
    events = extract_events(_position(1, stop=1.0950, target=1.1100), pd.Series(dtype=float), bars, 0.0001)
    assert len(events) == 1
    assert events[0].kind == "stop"
    assert events[0].ts == ts



def test_long_target_hits_in_third_sub_bar():
    ts = datetime(2026, 4, 25, 8, 0)
    bars = _bars([
        {"timestamp": ts, "low_bid": 1.0980, "high_bid": 1.1010, "high_ask": 1.1012, "low_ask": 1.0982},
        {"timestamp": ts + timedelta(hours=1), "low_bid": 1.0990, "high_bid": 1.1020, "high_ask": 1.1022, "low_ask": 1.0992},
        {"timestamp": ts + timedelta(hours=2), "low_bid": 1.1000, "high_bid": 1.1110, "high_ask": 1.1112, "low_ask": 1.1002},
    ])
    events = extract_events(_position(1, stop=1.0950, target=1.1100), pd.Series(dtype=float), bars, 0.0001)
    assert len(events) == 1
    assert events[0].kind == "target"
    assert events[0].ts == ts + timedelta(hours=2)



def test_short_stop_and_target_both_hit_in_same_sub_bar():
    ts = datetime(2026, 4, 25, 8, 0)
    bars = _bars([
        {"timestamp": ts, "low_bid": 149.10, "high_bid": 150.20, "high_ask": 150.30, "low_ask": 149.00},
    ])
    events = extract_events(_position(-1, stop=150.25, target=149.05, symbol="USD_JPY"), pd.Series(dtype=float), bars, 0.01)
    assert [event.kind for event in events] == ["stop", "target"]
    assert events[0].ts == ts
    assert events[1].ts == ts



def test_intrabar_returns_empty_when_neither_level_hits():
    ts = datetime(2026, 4, 25, 8, 0)
    bars = _bars([
        {"timestamp": ts, "low_bid": 1.0980, "high_bid": 1.1010, "high_ask": 1.1012, "low_ask": 1.0982},
    ])
    events = extract_events(_position(1, stop=1.0950, target=1.1100), pd.Series(dtype=float), bars, 0.0001)
    assert events == []



def test_intrabar_jpy_pair_has_no_off_by_100_behavior():
    ts = datetime(2026, 4, 25, 8, 0)
    bars = _bars([
        {"timestamp": ts, "low_bid": 149.78, "high_bid": 149.95, "high_ask": 149.98, "low_ask": 149.80},
    ])
    events = extract_events(_position(-1, stop=150.50, target=149.80, symbol="USD_JPY"), pd.Series(dtype=float), bars, 0.01)
    assert len(events) == 1
    assert events[0].kind == "target"
