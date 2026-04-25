"""Tests for the Phase 3.4 gate evaluator."""

from __future__ import annotations

# pylint: disable=missing-function-docstring,duplicate-code

from datetime import datetime, timedelta

import pandas as pd
from bh_ftmo.backtest.gate import evaluate_gate
from bh_ftmo.backtest.types import ChallengeResult, Trade

BASE_TS = datetime(2026, 1, 1, 0, 0)


def _trade(open_ts: datetime, pnl: float, *, risk: float = 100.0) -> Trade:
    return Trade(
        symbol='EUR_USD',
        strategy='bh_ftmo',
        direction=1,
        open_ts=open_ts,
        open_price=1.1000,
        close_ts=open_ts + timedelta(hours=4),
        close_price=1.1010,
        stop=1.0990,
        target=1.1020,
        lots=1.0,
        risk_at_open_account_ccy=risk,
        pnl_account_ccy=pnl,
        swap_account_ccy=0.0,
        commission_account_ccy=0.0,
        exit_reason='target' if pnl >= 0 else 'stop',
        components={'edge': 1.0},
    )


def _equity_curve(kind: str) -> pd.Series:
    index = pd.date_range(BASE_TS, periods=6, freq='1h')
    curves = {
        'strong': [100_000.0, 100_800.0, 101_700.0, 102_500.0, 103_300.0, 104_200.0],
        'weak_sharpe': [100_000.0, 100_000.0, 100_000.0, 100_000.0, 100_000.0, 100_000.0],
        'high_dd': [100_000.0, 110_000.0, 98_000.0, 97_000.0, 99_000.0, 101_000.0],
    }
    return pd.Series(curves[kind], index=index, dtype=float)


def _result(outcome: str, trades: tuple[Trade, ...], equity_kind: str = 'strong') -> ChallengeResult:
    curve = _equity_curve(equity_kind)
    return ChallengeResult(
        start_ts=curve.index[0].to_pydatetime(),
        end_ts=curve.index[-1].to_pydatetime(),
        outcome=outcome,  # type: ignore[arg-type]
        failed_by=None if outcome != 'failed' else 'daily_loss',
        target_hit_at=None,
        trading_days=4,
        final_equity_account_ccy=float(curve.iloc[-1]),
        trades=trades,
        breaches=(),
        equity_curve=curve,
        equity_curve_daily=curve.resample('1D').last(),
        skipped_signals=(),
        rng_seed=7,
    )


def _bh_results(
    *,
    outcome: str = 'passed',
    equity_kind: str = 'strong',
    trades: tuple[Trade, ...] | None = None,
    n: int = 20,
) -> list[ChallengeResult]:
    base_trades = trades or (
        _trade(BASE_TS, 200.0),
        _trade(BASE_TS + timedelta(hours=4), 150.0),
        _trade(BASE_TS + timedelta(hours=8), 100.0),
        _trade(BASE_TS + timedelta(hours=12), -75.0),
    )
    return [_result(outcome, base_trades, equity_kind=equity_kind) for _ in range(n)]


def _baseline(pass_count: int, total: int = 20) -> list[ChallengeResult]:
    results = []
    for idx in range(total):
        outcome = 'passed' if idx < pass_count else 'failed'
        results.append(_result(outcome, (_trade(BASE_TS + timedelta(hours=idx), 50.0),), equity_kind='strong'))
    return results


def test_gate_passes_when_all_criteria_clear():
    gate = evaluate_gate(_bh_results(n=20), {'random_baseline': _baseline(8)}, bootstrap_b=200, rng_seed=3)
    assert gate.overall_passed is True


def test_gate_fails_on_low_sharpe():
    gate = evaluate_gate(
        _bh_results(equity_kind='weak_sharpe'),
        {'random_baseline': _baseline(8)},
        bootstrap_b=200,
        rng_seed=3,
    )
    assert gate.overall_passed is False
    assert next(item for item in gate.criteria if item.name == 'sharpe').passed is False


def test_gate_fails_on_low_profit_factor():
    trades = (_trade(BASE_TS, 50.0), _trade(BASE_TS + timedelta(hours=4), -100.0))
    gate = evaluate_gate(_bh_results(trades=trades), {'random_baseline': _baseline(8)}, bootstrap_b=200, rng_seed=3)
    assert next(item for item in gate.criteria if item.name == 'profit_factor').passed is False


def test_gate_fails_on_low_win_rate():
    trades = (_trade(BASE_TS, 50.0), _trade(BASE_TS + timedelta(hours=4), -20.0), _trade(BASE_TS + timedelta(hours=8), -20.0))
    gate = evaluate_gate(_bh_results(trades=trades), {'random_baseline': _baseline(8)}, bootstrap_b=200, rng_seed=3)
    assert next(item for item in gate.criteria if item.name == 'win_rate').passed is False


def test_gate_fails_on_excess_max_drawdown():
    gate = evaluate_gate(_bh_results(equity_kind='high_dd'), {'random_baseline': _baseline(8)}, bootstrap_b=200, rng_seed=3)
    assert next(item for item in gate.criteria if item.name == 'max_dd').passed is False


def test_gate_fails_on_low_pass_rate_lower_ci():
    gate = evaluate_gate(
        _bh_results(outcome='passed', n=12) + _bh_results(outcome='failed', n=8),
        {'random_baseline': _baseline(4)},
        bootstrap_b=200,
        rng_seed=3,
    )
    assert next(item for item in gate.criteria if item.name == 'pass_rate_lower_ci').passed is False


def test_gate_fails_when_baseline_margin_too_small():
    bh_results = _bh_results(outcome='passed', n=13) + _bh_results(outcome='failed', n=7)
    gate = evaluate_gate(bh_results, {'random_baseline': _baseline(12, total=20)}, bootstrap_b=200, rng_seed=3)
    assert next(item for item in gate.criteria if item.name == 'vs_best_baseline').passed is False


def test_gate_fails_when_a_baseline_beats_bh_ftmo():
    bh_results = _bh_results(outcome='passed', n=12) + _bh_results(outcome='failed', n=8)
    gate = evaluate_gate(bh_results, {'random_baseline': _baseline(13, total=20)}, bootstrap_b=200, rng_seed=3)
    assert gate.margin_vs_best_baseline_pp < 0.0
    assert next(item for item in gate.criteria if item.name == 'vs_best_baseline').passed is False


def test_gate_result_carries_per_criterion_detail():
    gate = evaluate_gate(_bh_results(n=20), {'random_baseline': _baseline(8)}, bootstrap_b=200, rng_seed=3)
    assert [criterion.name for criterion in gate.criteria] == [
        'sharpe', 'profit_factor', 'win_rate', 'max_dd', 'pass_rate_lower_ci', 'vs_best_baseline'
    ]


def test_gate_result_overall_passed_only_if_all_passed():
    gate = evaluate_gate(
        _bh_results(equity_kind='weak_sharpe'),
        {'random_baseline': _baseline(8)},
        bootstrap_b=200,
        rng_seed=3,
    )
    assert gate.overall_passed == all(criterion.passed for criterion in gate.criteria)


def test_gate_deterministic_across_runs_with_same_seed():
    left = evaluate_gate(_bh_results(n=20), {'random_baseline': _baseline(8)}, bootstrap_b=200, rng_seed=11)
    right = evaluate_gate(_bh_results(n=20), {'random_baseline': _baseline(8)}, bootstrap_b=200, rng_seed=11)
    assert left == right
