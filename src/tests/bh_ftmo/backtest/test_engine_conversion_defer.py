"""Regression tests for sparse rates snapshots in the FTMO engine."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from bh_ftmo.analysis.strategy import Signal
from bh_ftmo.backtest.calendar_provider import NullCalendarProvider
from bh_ftmo.backtest.engine import run_challenge
from bh_ftmo.backtest.swap import SwapRates
from bh_ftmo.backtest.types import PairSpec


BASE_CONFIG = {
    "initial_balance": 100_000.0,
    "account_currency": "USD",
    "phase": "challenge",
    "profit_target_pct": 0.50,
    "daily_loss_pct": 0.05,
    "max_loss_pct": 0.10,
    "max_loss_type": "static",
    "min_trading_days": 1,
    "max_trading_days": 14,
    "server_timezone": "Europe/Prague",
    "commission_per_lot_round_turn": 0.0,
    "swap_model": "standard",
}

PAIR_SPECS = {
    "EUR_CHF": PairSpec("EUR_CHF", 0.0001, 100_000),
    "USD_CHF": PairSpec("USD_CHF", 0.0001, 100_000),
    "EUR_USD": PairSpec("EUR_USD", 0.0001, 100_000),
    "AUD_NZD": PairSpec("AUD_NZD", 0.0001, 100_000),
}


def _signal(symbol: str, ts: datetime) -> Signal:
    return Signal(
        symbol=symbol,
        strategy="baseline",
        timestamp=ts,
        direction=1,
        score=1.0,
        components={"edge": 1.0},
        above_threshold=True,
    )


def _frame_4h(rows: list[tuple[datetime, float, float, float, float, float, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "timestamp": ts,
                "open_bid": open_bid,
                "open_ask": open_ask,
                "close_bid": close_bid,
                "close_ask": close_ask,
                "high_bid": high_bid,
                "high_ask": high_bid + 0.0002,
                "low_bid": low_bid,
                "low_ask": low_bid + 0.0002,
            }
            for ts, open_bid, open_ask, close_bid, close_ask, high_bid, low_bid in rows
        ]
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame


def _frame_1h(rows: list[tuple[datetime, float, float, float, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "timestamp": ts,
                "close_bid": close_bid,
                "close_ask": close_ask,
                "high_bid": high_bid,
                "high_ask": high_bid + 0.0002,
                "low_bid": low_bid,
                "low_ask": low_bid + 0.0002,
            }
            for ts, close_bid, close_ask, high_bid, low_bid in rows
        ]
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame


def _support_1h(bar_ts: datetime, price: float) -> pd.DataFrame:
    return _frame_1h([(bar_ts + timedelta(hours=1), price, price + 0.0002, price + 0.0010, price - 0.0010)])


def _conversion_gap_fixture():
    t0 = datetime(2020, 1, 6, 0, 0)
    t1 = t0 + timedelta(hours=4)
    t2 = t1 + timedelta(hours=4)
    t3 = t2 + timedelta(hours=4)
    bars_4h = {
        "EUR_CHF": _frame_4h(
            [
                (t0, 0.9498, 0.9500, 0.9500, 0.9502, 0.9510, 0.9490),
                (t1, 0.9500, 0.9502, 0.9505, 0.9507, 0.9510, 0.9495),
                (t2, 0.9505, 0.9507, 0.9505, 0.9507, 0.9510, 0.9480),
                (t3, 0.9505, 0.9507, 0.9525, 0.9527, 0.9530, 0.9500),
            ]
        ),
        "USD_CHF": _frame_4h(
            [
                (t1, 0.9700, 0.9702, 0.9700, 0.9702, 0.9710, 0.9690),
                (t3, 0.9700, 0.9702, 0.9700, 0.9702, 0.9710, 0.9690),
            ]
        ),
        "EUR_USD": _frame_4h(
            [
                (t1, 1.1000, 1.1002, 1.1000, 1.1002, 1.1010, 1.0990),
                (t3, 1.1000, 1.1002, 1.1000, 1.1002, 1.1010, 1.0990),
            ]
        ),
        "AUD_NZD": _frame_4h([(t2, 1.0700, 1.0702, 1.0700, 1.0702, 1.0710, 1.0690)]),
    }
    bars_1h = {
        "EUR_CHF": _frame_1h(
            [
                (t1 + timedelta(hours=1), 0.9505, 0.9507, 0.9510, 0.9495),
                (t2 + timedelta(hours=1), 0.9490, 0.9492, 0.9510, 0.9480),
                (t3 + timedelta(hours=1), 0.9525, 0.9527, 0.9530, 0.9500),
            ]
        ),
        "USD_CHF": pd.concat([_support_1h(t1, 0.9700), _support_1h(t3, 0.9700)], ignore_index=True),
        "EUR_USD": pd.concat([_support_1h(t1, 1.1000), _support_1h(t3, 1.1000)], ignore_index=True),
        "AUD_NZD": _support_1h(t2, 1.0700),
    }
    atr = {"EUR_CHF": pd.Series([0.0010, 0.0010, 0.0010, 0.0010], index=[t0, t1, t2, t3])}
    sizing = {
        "risk_pct_per_trade": 0.006,
        "k_stop": 1.0,
        "k_target": 2.0,
        "max_concurrent_positions": 5,
        "max_concurrent_per_currency": 5,
        "max_concurrent_per_usd_basket": 5,
    }
    return t0, t1, t2, t3, bars_4h, bars_1h, atr, sizing


def test_open_position_with_missing_conversion_path_defers_and_resumes():
    """Bar B excludes the open EUR_CHF position from MTM/events rather than using zero P&L."""
    t0, _, t2, t3, bars_4h, bars_1h, atr, sizing = _conversion_gap_fixture()
    result = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=[_signal("EUR_CHF", t0)],
        atr_by_symbol=atr,
        pair_specs=PAIR_SPECS,
        ftmo_config=dict(BASE_CONFIG),
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_CHF": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=t0,
        start_equity=100_000.0,
        rng_seed=17,
    )

    assert result.trades
    assert result.trades[0].symbol == "EUR_CHF"
    assert result.trades[0].close_ts > t2
    assert result.trades[0].close_ts == t3 + timedelta(hours=1)
    assert result.equity_curve.loc[t3] == pytest.approx(100_000.0)
    assert result.non_convertible_position_events > 0


def test_entry_signal_with_missing_conversion_path_is_skipped():
    _, t1, _, _, bars_4h, bars_1h, atr, sizing = _conversion_gap_fixture()
    result = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=[_signal("EUR_CHF", t1)],
        atr_by_symbol=atr,
        pair_specs=PAIR_SPECS,
        ftmo_config=dict(BASE_CONFIG),
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_CHF": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=t1,
        start_equity=100_000.0,
        rng_seed=18,
    )

    assert result.trades == ()
    assert any(signal.symbol == "EUR_CHF" and reason == "no_conversion_path" for signal, reason in result.skipped_signals)
