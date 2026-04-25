"""Unit tests for BH FTMO backtest metrics helpers."""

from __future__ import annotations

# pylint: disable=missing-function-docstring,too-many-arguments

from datetime import datetime, timedelta
import math

import pandas as pd
import pytest

from bh_ftmo.analysis.strategy import Signal
from bh_ftmo.backtest.metrics import (
    cohort_metrics,
    equity_metrics,
    per_session_breakdown,
    per_strategy_breakdown,
    trade_metrics,
)
from bh_ftmo.backtest.types import ChallengeResult, Trade


BASE_TS = datetime(2026, 1, 12, 0, 0)


def _trade(
    *,
    open_ts: datetime,
    pnl: float,
    strategy: str = "baseline",
    symbol: str = "EUR_USD",
    open_price: float = 1.1000,
    stop: float = 1.0990,
    close_ts: datetime | None = None,
    risk_at_open_account_ccy: float = 100.0,
) -> Trade:
    return Trade(
        symbol=symbol,
        strategy=strategy,
        direction=1,
        open_ts=open_ts,
        open_price=open_price,
        close_ts=close_ts or (open_ts + timedelta(hours=4)),
        close_price=open_price + 0.0010,
        stop=stop,
        target=open_price + 0.0020,
        lots=1.0,
        risk_at_open_account_ccy=risk_at_open_account_ccy,
        pnl_account_ccy=pnl,
        swap_account_ccy=0.0,
        commission_account_ccy=0.0,
        exit_reason="target",
        components={"edge": 1.0},
    )


def _result(
    *,
    trades: tuple[Trade, ...] = (),
    outcome: str = "passed",
    equity_curve: pd.Series | None = None,
    equity_curve_daily: pd.Series | None = None,
) -> ChallengeResult:
    hourly = equity_curve
    if hourly is None:
        hourly = pd.Series(
            [100_000.0, 100_100.0, 100_200.0],
            index=pd.date_range(BASE_TS, periods=3, freq="1h"),
            dtype=float,
        )
    daily = equity_curve_daily
    if daily is None:
        daily = pd.Series(
            [float(hourly.iloc[0]), float(hourly.iloc[-1])],
            index=pd.date_range(BASE_TS, periods=2, freq="1D"),
            dtype=float,
        )
    return ChallengeResult(
        start_ts=hourly.index[0].to_pydatetime(),
        end_ts=hourly.index[-1].to_pydatetime(),
        outcome=outcome,  # type: ignore[arg-type]
        failed_by=None if outcome != "failed" else "daily_loss",
        target_hit_at=None,
        trading_days=1,
        final_equity_account_ccy=float(hourly.iloc[-1]),
        trades=trades,
        breaches=(),
        equity_curve=hourly,
        equity_curve_daily=daily,
        skipped_signals=((_signal(), "rule_blocked"),),
        rng_seed=7,
    )


def _signal() -> Signal:
    return Signal(
        symbol="EUR_USD",
        strategy="baseline",
        timestamp=BASE_TS,
        direction=1,
        score=1.0,
        components={"edge": 1.0},
        above_threshold=True,
    )


def test_trade_metrics_empty_trade_list_returns_zero_safe_values():
    metrics = trade_metrics(_result())
    assert metrics.n_trades == 0
    assert metrics.win_rate == 0.0
    assert metrics.profit_factor == 0.0
    assert metrics.r_expectancy == 0.0


def test_trade_metrics_all_wins_returns_infinite_profit_factor():
    result = _result(
        trades=(
            _trade(open_ts=BASE_TS, pnl=200.0),
            _trade(open_ts=BASE_TS + timedelta(hours=4), pnl=100.0),
        )
    )
    metrics = trade_metrics(result)
    assert metrics.n_trades == 2
    assert metrics.n_wins == 2
    assert metrics.n_losses == 0
    assert metrics.win_rate == 1.0
    assert math.isinf(metrics.profit_factor)
    assert metrics.r_expectancy == pytest.approx(1.5)


def test_trade_metrics_mixed_example_matches_hand_computation():
    result = _result(
        trades=(
            _trade(open_ts=BASE_TS, pnl=200.0),
            _trade(open_ts=BASE_TS + timedelta(hours=4), pnl=-100.0),
            _trade(open_ts=BASE_TS + timedelta(hours=8), pnl=50.0),
        )
    )
    metrics = trade_metrics(result)
    assert metrics.n_trades == 3
    assert metrics.n_wins == 2
    assert metrics.n_losses == 1
    assert metrics.n_breakeven == 0
    assert metrics.win_rate == pytest.approx(2 / 3)
    assert metrics.profit_factor == pytest.approx(2.5)
    assert metrics.payoff_ratio == pytest.approx(1.25)
    assert metrics.avg_trade_pnl == pytest.approx(50.0)
    assert metrics.total_pnl == pytest.approx(150.0)
    assert metrics.r_expectancy == pytest.approx(0.5)


def test_trade_metrics_breakeven_threshold_counts_neutral_trades():
    result = _result(
        trades=(
            _trade(open_ts=BASE_TS, pnl=1e-10),
            _trade(open_ts=BASE_TS + timedelta(hours=4), pnl=-1e-10),
            _trade(open_ts=BASE_TS + timedelta(hours=8), pnl=25.0),
        )
    )
    metrics = trade_metrics(result)
    assert metrics.n_breakeven == 2
    assert metrics.n_wins == 1
    assert metrics.n_losses == 0


def test_equity_metrics_flat_curve_returns_nan_sharpe_and_zero_drawdown():
    equity_curve = pd.Series(
        [100_000.0, 100_000.0, 100_000.0],
        index=pd.date_range(BASE_TS, periods=3, freq="1h"),
        dtype=float,
    )
    metrics = equity_metrics(_result(equity_curve=equity_curve))
    assert math.isnan(metrics.sharpe_annualized)
    assert math.isnan(metrics.sortino_annualized)
    assert metrics.max_drawdown_pct == 0.0
    assert metrics.max_drawdown_account_ccy == 0.0


def test_equity_metrics_linear_up_curve_has_positive_sharpe_and_higher_sortino():
    equity_curve = pd.Series(
        [100_000.0, 101_000.0, 102_000.0, 103_000.0],
        index=pd.date_range(BASE_TS, periods=4, freq="1h"),
        dtype=float,
    )
    metrics = equity_metrics(_result(equity_curve=equity_curve))
    assert metrics.sharpe_annualized > 0.0
    assert metrics.sortino_annualized > metrics.sharpe_annualized


def test_equity_metrics_sawtooth_curve_matches_hand_drawdown_and_trade_chain():
    index = pd.date_range(BASE_TS, periods=4, freq="1h")
    equity_curve = pd.Series([100_000.0, 120_000.0, 90_000.0, 130_000.0], index=index, dtype=float)
    trades = (
        _trade(open_ts=index[0].to_pydatetime(), pnl=50.0),
        _trade(open_ts=index[1].to_pydatetime(), pnl=-100.0),
        _trade(open_ts=index[2].to_pydatetime(), pnl=200.0),
        _trade(open_ts=(index[2] + timedelta(hours=1)).to_pydatetime(), pnl=25.0),
    )
    metrics = equity_metrics(_result(trades=trades, equity_curve=equity_curve))
    assert metrics.max_drawdown_pct == pytest.approx(0.25)
    assert metrics.max_drawdown_account_ccy == pytest.approx(30_000.0)
    assert metrics.worst_dd_peak_ts == index[1].to_pydatetime()
    assert metrics.worst_dd_trough_ts == index[2].to_pydatetime()
    assert metrics.worst_dd_trade_chain == (trades[1], trades[2])


def test_cohort_metrics_all_passes_returns_degenerate_ci():
    metrics = cohort_metrics([_result(outcome="passed") for _ in range(5)])
    assert metrics.pass_rate == 1.0
    assert metrics.pass_rate_lower_ci_95 == 1.0
    assert metrics.pass_rate_upper_ci_95 == 1.0


def test_cohort_metrics_all_fails_returns_zero_ci():
    metrics = cohort_metrics([_result(outcome="failed") for _ in range(5)])
    assert metrics.pass_rate == 0.0
    assert metrics.pass_rate_lower_ci_95 == 0.0
    assert metrics.pass_rate_upper_ci_95 == 0.0


def test_cohort_metrics_half_pass_half_fail_has_expected_ci_band():
    results = [_result(outcome="passed") for _ in range(50)] + [_result(outcome="failed") for _ in range(50)]
    metrics = cohort_metrics(results, bootstrap_b=1000, rng_seed=42)
    assert metrics.pass_rate == pytest.approx(0.5)
    assert 0.35 <= metrics.pass_rate_lower_ci_95 <= 0.45
    assert 0.55 <= metrics.pass_rate_upper_ci_95 <= 0.65


def test_cohort_metrics_same_seed_is_deterministic():
    results = [_result(outcome="passed") for _ in range(3)] + [_result(outcome="failed") for _ in range(2)]
    left = cohort_metrics(results, bootstrap_b=1000, rng_seed=17)
    right = cohort_metrics(results, bootstrap_b=1000, rng_seed=17)
    assert left.pass_rate_lower_ci_95 == right.pass_rate_lower_ci_95
    assert left.pass_rate_upper_ci_95 == right.pass_rate_upper_ci_95


def test_per_session_breakdown_groups_trades_by_open_timestamp_session():
    trades = (
        _trade(open_ts=datetime(2026, 1, 13, 0, 0), pnl=100.0),
        _trade(open_ts=datetime(2026, 1, 13, 9, 0), pnl=50.0),
        _trade(open_ts=datetime(2026, 1, 13, 14, 0), pnl=-25.0),
        _trade(open_ts=datetime(2026, 1, 13, 18, 0), pnl=75.0),
    )
    breakdown = per_session_breakdown(_result(trades=trades))
    assert breakdown["ASIA"].n_trades == 1
    assert breakdown["LONDON"].n_trades == 1
    assert breakdown["OVERLAP"].n_trades == 1
    assert breakdown["NY"].n_trades == 1


def test_per_strategy_breakdown_groups_trades_across_results():
    left = _result(trades=(_trade(open_ts=BASE_TS, pnl=100.0, strategy="bh_ftmo"),))
    right = _result(
        trades=(
            _trade(open_ts=BASE_TS + timedelta(hours=1), pnl=-50.0, strategy="baseline_a"),
            _trade(open_ts=BASE_TS + timedelta(hours=2), pnl=25.0, strategy="baseline_a"),
        )
    )
    breakdown = per_strategy_breakdown([left, right])
    assert breakdown["bh_ftmo"].n_trades == 1
    assert breakdown["baseline_a"].n_trades == 2
    assert breakdown["baseline_a"].profit_factor == pytest.approx(0.5)


def test_trade_metrics_r_expectancy_uses_exact_risk_field():
    result = _result(
        trades=(
            _trade(open_ts=BASE_TS, pnl=150.0, risk_at_open_account_ccy=50.0),
            _trade(open_ts=BASE_TS + timedelta(hours=4), pnl=-60.0, risk_at_open_account_ccy=30.0),
        )
    )
    metrics = trade_metrics(result)
    assert metrics.r_expectancy == pytest.approx(0.5)


def test_trade_metrics_zero_risk_trade_excluded_from_r():
    result = _result(
        trades=(
            _trade(open_ts=BASE_TS, pnl=100.0, risk_at_open_account_ccy=0.0),
            _trade(open_ts=BASE_TS + timedelta(hours=4), pnl=50.0, risk_at_open_account_ccy=25.0),
        )
    )
    metrics = trade_metrics(result)
    assert metrics.r_expectancy == pytest.approx(2.0)
