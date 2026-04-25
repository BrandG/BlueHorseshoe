"""Golden frozen challenge run for engine regression protection."""

from __future__ import annotations

# pylint: disable=missing-function-docstring

from datetime import datetime, timedelta

import pandas as pd
import pytest

from bh_ftmo.analysis.strategy import Signal
from bh_ftmo.backtest.calendar_provider import NullCalendarProvider
from bh_ftmo.backtest.engine import run_challenge
from bh_ftmo.backtest.swap import SwapRates
from bh_ftmo.backtest.types import PairSpec


def test_golden_frozen_single_symbol_run():
    t0 = datetime(2026, 1, 12, 10, 0)
    t1 = t0 + timedelta(hours=4)
    t2 = t1 + timedelta(hours=4)
    bars_4h = {
        "EUR_USD": pd.DataFrame(
            [
                {"timestamp": t0, "open_bid": 1.0998, "open_ask": 1.1000, "close_bid": 1.1002, "close_ask": 1.1004, "high_bid": 1.1002, "high_ask": 1.1004, "low_bid": 1.0998, "low_ask": 1.1000},
                {"timestamp": t1, "open_bid": 1.0998, "open_ask": 1.1000, "close_bid": 1.1100, "close_ask": 1.1102, "high_bid": 1.1100, "high_ask": 1.1102, "low_bid": 1.0998, "low_ask": 1.1000},
                {"timestamp": t2, "open_bid": 1.1100, "open_ask": 1.1102, "close_bid": 1.1100, "close_ask": 1.1102, "high_bid": 1.1100, "high_ask": 1.1102, "low_bid": 1.1100, "low_ask": 1.1102},
            ]
        )
    }
    bars_1h = {
        "EUR_USD": pd.DataFrame(
            [
                {"timestamp": t1 + timedelta(hours=1), "close_bid": 1.1100, "close_ask": 1.1102, "high_bid": 1.1110, "high_ask": 1.1112, "low_bid": 1.0990, "low_ask": 1.0992},
                {"timestamp": t1 + timedelta(hours=2), "close_bid": 1.1100, "close_ask": 1.1102, "high_bid": 1.1105, "high_ask": 1.1107, "low_bid": 1.1095, "low_ask": 1.1097},
                {"timestamp": t1 + timedelta(hours=3), "close_bid": 1.1100, "close_ask": 1.1102, "high_bid": 1.1105, "high_ask": 1.1107, "low_bid": 1.1095, "low_ask": 1.1097},
                {"timestamp": t1 + timedelta(hours=4), "close_bid": 1.1100, "close_ask": 1.1102, "high_bid": 1.1105, "high_ask": 1.1107, "low_bid": 1.1095, "low_ask": 1.1097},
            ]
        )
    }
    signals = [Signal(symbol="EUR_USD", strategy="baseline", timestamp=t0, direction=1, score=1.0, components={"edge": 1.0}, above_threshold=True)]
    atr = {"EUR_USD": pd.Series([0.0040, 0.0040, 0.0040], index=[t0, t1, t2])}
    ftmo_config = {
        "initial_balance": 100_000.0,
        "account_currency": "USD",
        "phase": "challenge",
        "profit_target_pct": 0.01,
        "daily_loss_pct": 0.05,
        "max_loss_pct": 0.10,
        "max_loss_type": "static",
        "min_trading_days": 1,
        "max_trading_days": 14,
        "server_timezone": "Europe/Prague",
        "commission_per_lot_round_turn": 0.0,
        "swap_model": "standard",
    }
    sizing_config = {"risk_pct_per_trade": 0.006, "k_stop": 1.5, "k_target": 2.5}
    result = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=signals,
        atr_by_symbol=atr,
        pair_specs={"EUR_USD": PairSpec("EUR_USD", 0.0001, 100_000)},
        ftmo_config=ftmo_config,
        sizing_config=sizing_config,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=t0,
        start_equity=100_000.0,
        rng_seed=99,
    )
    assert result.final_equity_account_ccy == 101_000.0
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.symbol == "EUR_USD"
    assert trade.strategy == "baseline"
    assert trade.direction == 1
    assert trade.open_ts == t1
    assert trade.open_price == 1.1
    assert trade.close_ts == t1 + timedelta(hours=1)
    assert trade.close_price == 1.11
    assert trade.stop == 1.094
    assert trade.target == 1.11
    assert trade.lots == pytest.approx(1.0)
    assert trade.pnl_account_ccy == pytest.approx(1000.0)
    assert trade.swap_account_ccy == 0.0
    assert trade.commission_account_ccy == 0.0
    assert trade.exit_reason == "target"
    assert trade.components == {"edge": 1.0}
