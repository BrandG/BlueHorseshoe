"""BH FTMO Phase 3 entry-edge gate evaluator."""

from __future__ import annotations

# pylint: disable=too-many-locals

from typing import Optional

import numpy as np
import pandas as pd

from bh_ftmo.backtest.metrics import cohort_metrics, equity_metrics, trade_metrics
from bh_ftmo.backtest.types import ChallengeResult, GateCriterion, GateResult


SHARPE_THRESHOLD = 1.0
PROFIT_FACTOR_THRESHOLD = 1.3
WIN_RATE_THRESHOLD = 0.45
MAX_DRAWDOWN_THRESHOLD = 0.10
PASS_RATE_LOWER_CI_THRESHOLD = 0.70
BASELINE_MARGIN_PP_THRESHOLD = 10.0


def evaluate_gate(
    bh_ftmo_results: list[ChallengeResult],
    baseline_results_by_name: dict[str, list[ChallengeResult]],
    *,
    bootstrap_b: int = 1000,
    rng_seed: int = 0,
) -> GateResult:
    """Evaluate the locked Phase 3 gate on one BH FTMO cohort.

    Sharpe uses the median per-challenge annualized Sharpe from the canonical
    1h equity curves. This avoids stitching independent challenge curves into a
    synthetic path while still measuring typical challenge-level behavior.
    """

    if not bh_ftmo_results:
        raise ValueError('bh_ftmo_results must not be empty')

    pooled_trade_summary = _pooled_trade_metrics(bh_ftmo_results)
    sharpe_actual = _median_sharpe(bh_ftmo_results)
    max_dd_actual = max((equity_metrics(result).max_drawdown_pct for result in bh_ftmo_results), default=0.0)
    bh_cohort = cohort_metrics(bh_ftmo_results, bootstrap_b=bootstrap_b, rng_seed=rng_seed)

    baseline_pass_rates = {
        name: cohort_metrics(results, bootstrap_b=bootstrap_b, rng_seed=rng_seed).pass_rate
        for name, results in baseline_results_by_name.items()
    }
    best_baseline_name, best_baseline_pass_rate = _best_baseline(baseline_pass_rates)
    margin_vs_best_pp = (bh_cohort.pass_rate - best_baseline_pass_rate) * 100.0

    criteria = (
        GateCriterion('sharpe', SHARPE_THRESHOLD, sharpe_actual, _passes_min(sharpe_actual, SHARPE_THRESHOLD)),
        GateCriterion(
            'profit_factor',
            PROFIT_FACTOR_THRESHOLD,
            pooled_trade_summary.profit_factor,
            _passes_min(pooled_trade_summary.profit_factor, PROFIT_FACTOR_THRESHOLD),
        ),
        GateCriterion(
            'win_rate',
            WIN_RATE_THRESHOLD,
            pooled_trade_summary.win_rate,
            _passes_min(pooled_trade_summary.win_rate, WIN_RATE_THRESHOLD),
        ),
        GateCriterion('max_dd', MAX_DRAWDOWN_THRESHOLD, max_dd_actual, _passes_max(max_dd_actual, MAX_DRAWDOWN_THRESHOLD)),
        GateCriterion(
            'pass_rate_lower_ci',
            PASS_RATE_LOWER_CI_THRESHOLD,
            bh_cohort.pass_rate_lower_ci_95,
            _passes_min(bh_cohort.pass_rate_lower_ci_95, PASS_RATE_LOWER_CI_THRESHOLD),
        ),
        GateCriterion(
            'vs_best_baseline',
            BASELINE_MARGIN_PP_THRESHOLD,
            margin_vs_best_pp,
            _passes_min(margin_vs_best_pp, BASELINE_MARGIN_PP_THRESHOLD),
        ),
    )
    overall_passed = all(criterion.passed for criterion in criteria)
    failed = next((criterion for criterion in criteria if not criterion.passed), None)
    if failed is None:
        notes = 'All locked Phase 3 gate criteria passed.'
    else:
        notes = (
            f'First failed criterion: {failed.name} '
            f'(actual={failed.actual:.4f}, threshold={failed.threshold:.4f}).'
        )
    return GateResult(
        overall_passed=overall_passed,
        criteria=criteria,
        bh_ftmo_pass_rate=bh_cohort.pass_rate,
        best_baseline_name=best_baseline_name,
        best_baseline_pass_rate=best_baseline_pass_rate,
        margin_vs_best_baseline_pp=margin_vs_best_pp,
        notes=notes,
    )


def _pooled_trade_metrics(results: list[ChallengeResult]):
    trades = tuple(trade for result in results for trade in result.trades)
    template = results[0]
    pooled = ChallengeResult(
        start_ts=template.start_ts,
        end_ts=template.end_ts,
        outcome=template.outcome,
        failed_by=template.failed_by,
        target_hit_at=template.target_hit_at,
        trading_days=template.trading_days,
        final_equity_account_ccy=template.final_equity_account_ccy,
        trades=trades,
        breaches=(),
        equity_curve=pd.Series(dtype=float),
        equity_curve_daily=pd.Series(dtype=float),
        skipped_signals=(),
        rng_seed=template.rng_seed,
    )
    return trade_metrics(pooled)


def _median_sharpe(results: list[ChallengeResult]) -> float:
    values = [equity_metrics(result).sharpe_annualized for result in results]
    finite = [value for value in values if not np.isnan(value)]
    if not finite:
        return float('nan')
    return float(np.median(np.array(finite, dtype=float)))


def _best_baseline(pass_rates: dict[str, float]) -> tuple[Optional[str], float]:
    if not pass_rates:
        return None, 0.0
    name, rate = sorted(pass_rates.items(), key=lambda item: (-item[1], item[0]))[0]
    return name, float(rate)


def _passes_min(actual: float, threshold: float) -> bool:
    return not np.isnan(actual) and actual >= threshold


def _passes_max(actual: float, threshold: float) -> bool:
    return not np.isnan(actual) and actual <= threshold
