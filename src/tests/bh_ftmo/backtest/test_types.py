"""Unit tests for immutable backtest value types."""

from __future__ import annotations

# pylint: disable=missing-function-docstring

from dataclasses import FrozenInstanceError
from datetime import datetime

import pandas as pd
import pytest

from bh_ftmo.analysis.strategy import Signal
from bh_ftmo.backtest.types import ChallengeResult, ExitEvent, PairSpec, Position, RuleBreach, Trade


def _signal() -> Signal:
    return Signal(
        symbol="EUR_USD",
        strategy="baseline",
        timestamp=datetime(2026, 4, 25, 8, 0),
        direction=1,
        score=1.0,
        components={"trend": 1.0},
        above_threshold=True,
    )


def test_pair_spec_construction_and_equality():
    left = PairSpec(symbol="EUR_USD", pip_size=0.0001, contract_size=100_000)
    right = PairSpec(symbol="EUR_USD", pip_size=0.0001, contract_size=100_000)
    assert left == right



def test_position_is_frozen():
    position = Position(
        id=1,
        symbol="EUR_USD",
        strategy="baseline",
        direction=1,
        open_ts=datetime(2026, 4, 25, 8, 0),
        open_price=1.1012,
        stop=1.0962,
        target=1.1095,
        lots=0.5,
    )
    with pytest.raises(FrozenInstanceError):
        position.lots = 1.0  # type: ignore[misc]



def test_trade_construction_and_equality():
    trade = Trade(
        symbol="EUR_USD",
        strategy="baseline",
        direction=1,
        open_ts=datetime(2026, 4, 25, 8, 0),
        open_price=1.1012,
        close_ts=datetime(2026, 4, 25, 12, 0),
        close_price=1.1072,
        stop=1.0962,
        target=1.1095,
        lots=0.5,
        pnl_account_ccy=300.0,
        swap_account_ccy=-1.5,
        commission_account_ccy=1.5,
        exit_reason="target",
        components={"trend": 1.0},
    )
    same = Trade(**trade.__dict__)
    assert trade == same



def test_exit_event_and_rule_breach_equality():
    event = ExitEvent(
        ts=datetime(2026, 4, 25, 12, 0),
        symbol="USD_JPY",
        kind="stop",
        price=149.2,
        position_id=7,
    )
    breach = RuleBreach(
        rule="daily_loss",
        timestamp=datetime(2026, 4, 25, 18, 0),
        equity_at_breach=94_999.0,
        threshold=95_000.0,
    )
    assert event == ExitEvent(**event.__dict__)
    assert breach == RuleBreach(**breach.__dict__)



def test_challenge_result_construction_uses_tuples():
    trade = Trade(
        symbol="EUR_USD",
        strategy="baseline",
        direction=1,
        open_ts=datetime(2026, 4, 25, 8, 0),
        open_price=1.1012,
        close_ts=datetime(2026, 4, 25, 12, 0),
        close_price=1.1072,
        stop=1.0962,
        target=1.1095,
        lots=0.5,
        pnl_account_ccy=300.0,
        swap_account_ccy=-1.5,
        commission_account_ccy=1.5,
        exit_reason="target",
        components={"trend": 1.0},
    )
    breach = RuleBreach(
        rule="daily_loss",
        timestamp=datetime(2026, 4, 25, 18, 0),
        equity_at_breach=94_999.0,
        threshold=95_000.0,
    )
    result = ChallengeResult(
        start_ts=datetime(2026, 4, 25, 0, 0),
        end_ts=datetime(2026, 4, 30, 0, 0),
        outcome="passed",
        failed_by=None,
        target_hit_at=datetime(2026, 4, 28, 18, 0),
        trading_days=4,
        final_equity_account_ccy=110_000.0,
        trades=(trade,),
        breaches=(breach,),
        equity_curve=pd.Series([100_000.0, 110_000.0], index=pd.date_range("2026-04-25", periods=2, freq="1h")),
        equity_curve_daily=pd.Series([100_000.0, 110_000.0], index=pd.date_range("2026-04-25", periods=2, freq="1D")),
        skipped_signals=((_signal(), "rule_blocked"),),
        rng_seed=7,
    )
    assert isinstance(result.trades, tuple)
    assert isinstance(result.breaches, tuple)
    assert isinstance(result.skipped_signals, tuple)



def test_challenge_result_is_frozen():
    result = ChallengeResult(
        start_ts=datetime(2026, 4, 25, 0, 0),
        end_ts=datetime(2026, 4, 30, 0, 0),
        outcome="in_progress",
        failed_by=None,
        target_hit_at=None,
        trading_days=0,
        final_equity_account_ccy=100_000.0,
        trades=(),
        breaches=(),
        equity_curve=pd.Series(dtype=float),
        equity_curve_daily=pd.Series(dtype=float),
        skipped_signals=(),
        rng_seed=11,
    )
    with pytest.raises(FrozenInstanceError):
        result.outcome = "failed"  # type: ignore[misc]
