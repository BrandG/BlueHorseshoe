"""Metrics for BH FTMO Phase 3 backtest results.

All metrics compute from a :class:`~bh_ftmo.backtest.types.ChallengeResult` or
from a cohort of them. Per P3-17, equity-curve metrics must use the canonical
1h-resampled ``ChallengeResult.equity_curve`` series. ``equity_curve_daily`` is
reserved for reporting charts only and must never drive Sharpe, Sortino, or
drawdown calculations.
"""

from __future__ import annotations

# pylint: disable=too-many-instance-attributes,too-many-locals

from dataclasses import dataclass
from datetime import datetime
import numpy as np
import pandas as pd

from bh_ftmo.backtest.types import ChallengeResult, Trade
from bh_ftmo.indicators.sessions import session_label

PERIODS_PER_YEAR_1H = 6240
BREAKEVEN_EPSILON = 1e-9


@dataclass(frozen=True)
class TradeMetrics:
    """Trade-level summary metrics for one result or one grouped trade set."""

    n_trades: int
    n_wins: int
    n_losses: int
    n_breakeven: int
    win_rate: float
    profit_factor: float
    r_expectancy: float
    payoff_ratio: float
    avg_trade_pnl: float
    total_pnl: float


@dataclass(frozen=True)
class EquityMetrics:
    """Equity-curve metrics computed from the canonical 1h-resampled series."""

    sharpe_annualized: float
    sortino_annualized: float
    max_drawdown_pct: float
    max_drawdown_account_ccy: float
    worst_dd_peak_ts: datetime
    worst_dd_trough_ts: datetime
    worst_dd_trade_chain: tuple[Trade, ...]


@dataclass(frozen=True)
class CohortMetrics:
    """Outcome counts and bootstrap confidence bounds for a result cohort."""

    n_runs: int
    pass_count: int
    fail_count: int
    push_count: int
    in_progress_count: int
    pass_rate: float
    pass_rate_lower_ci_95: float
    pass_rate_upper_ci_95: float
    bootstrap_b: int


def trade_metrics(result: ChallengeResult) -> TradeMetrics:
    """Compute trade-set metrics from one challenge result."""

    return _trade_metrics_for_trades(result.trades)


def equity_metrics(result: ChallengeResult) -> EquityMetrics:
    """Compute equity metrics from ``result.equity_curve`` only, never daily data."""

    equity_curve = result.equity_curve.astype(float)
    if equity_curve.empty:
        return EquityMetrics(
            sharpe_annualized=float(np.nan),
            sortino_annualized=float(np.nan),
            max_drawdown_pct=0.0,
            max_drawdown_account_ccy=0.0,
            worst_dd_peak_ts=result.start_ts,
            worst_dd_trough_ts=result.start_ts,
            worst_dd_trade_chain=(),
        )

    # P3-17: metrics are pinned to the 1h-resampled canonical equity curve.
    returns = equity_curve.pct_change().dropna()
    mean_return = float(returns.mean()) if not returns.empty else float("nan")
    std_return = float(returns.std(ddof=0)) if not returns.empty else float("nan")
    sharpe = _annualized_ratio(mean_return, std_return)

    downside = returns[returns < 0.0]
    if returns.empty:
        sortino = float(np.nan)
    elif downside.empty:
        sortino = float(np.inf) if mean_return > 0.0 else float(np.nan)
    else:
        downside_std = float(downside.std(ddof=0))
        sortino = _annualized_ratio(mean_return, downside_std)

    running_max = equity_curve.cummax()
    drawdown_abs = running_max - equity_curve
    drawdown_pct = 1.0 - (equity_curve / running_max.replace(0.0, np.nan))
    trough_ts = drawdown_pct.idxmax()
    max_drawdown_pct = float(drawdown_pct.loc[trough_ts]) if not drawdown_pct.empty else 0.0
    max_drawdown_account_ccy = float(drawdown_abs.loc[trough_ts]) if not drawdown_abs.empty else 0.0
    peak_value = float(running_max.loc[trough_ts])
    peak_candidates = equity_curve.loc[:trough_ts]
    peak_ts = peak_candidates[peak_candidates == peak_value].index[-1].to_pydatetime()
    trough_dt = trough_ts.to_pydatetime()
    trade_chain = tuple(
        trade for trade in result.trades if peak_ts <= trade.open_ts <= trough_dt
    )
    return EquityMetrics(
        sharpe_annualized=sharpe,
        sortino_annualized=sortino,
        max_drawdown_pct=max_drawdown_pct,
        max_drawdown_account_ccy=max_drawdown_account_ccy,
        worst_dd_peak_ts=peak_ts,
        worst_dd_trough_ts=trough_dt,
        worst_dd_trade_chain=trade_chain,
    )


def cohort_metrics(
    results: list[ChallengeResult],
    *,
    bootstrap_b: int = 1000,
    rng_seed: int = 0,
) -> CohortMetrics:
    """Compute cohort outcome counts plus a bootstrap 95% CI for pass rate."""

    if bootstrap_b <= 0:
        raise ValueError("bootstrap_b must be positive")

    n_runs = len(results)
    pass_count = sum(result.outcome == "passed" for result in results)
    fail_count = sum(result.outcome == "failed" for result in results)
    push_count = sum(result.outcome == "push" for result in results)
    in_progress_count = sum(result.outcome == "in_progress" for result in results)
    if n_runs == 0:
        return CohortMetrics(
            n_runs=0,
            pass_count=0,
            fail_count=0,
            push_count=0,
            in_progress_count=0,
            pass_rate=0.0,
            pass_rate_lower_ci_95=0.0,
            pass_rate_upper_ci_95=0.0,
            bootstrap_b=bootstrap_b,
        )

    outcomes = np.array([1.0 if result.outcome == "passed" else 0.0 for result in results], dtype=float)
    pass_rate = float(outcomes.mean())
    rng = np.random.default_rng(rng_seed)
    bootstrap_samples = rng.choice(outcomes, size=(bootstrap_b, n_runs), replace=True).mean(axis=1)
    lower, upper = np.percentile(bootstrap_samples, [2.5, 97.5])
    return CohortMetrics(
        n_runs=n_runs,
        pass_count=pass_count,
        fail_count=fail_count,
        push_count=push_count,
        in_progress_count=in_progress_count,
        pass_rate=pass_rate,
        pass_rate_lower_ci_95=float(lower),
        pass_rate_upper_ci_95=float(upper),
        bootstrap_b=bootstrap_b,
    )


def per_session_breakdown(result: ChallengeResult) -> dict[str, TradeMetrics]:
    """Group trades by open-session label and compute trade metrics for each."""

    if not result.trades:
        return {}

    trade_frame = pd.DataFrame({"open_ts": [trade.open_ts for trade in result.trades]})
    labels = session_label(trade_frame["open_ts"])
    grouped: dict[str, list[Trade]] = {}
    for trade, label in zip(result.trades, labels):
        grouped.setdefault(label.name, []).append(trade)
    return {
        session_name: _trade_metrics_for_trades(trades)
        for session_name, trades in sorted(grouped.items())
    }


def per_strategy_breakdown(results: list[ChallengeResult]) -> dict[str, TradeMetrics]:
    """Group all trades across results by ``Trade.strategy``."""

    grouped: dict[str, list[Trade]] = {}
    for result in results:
        for trade in result.trades:
            grouped.setdefault(trade.strategy, []).append(trade)
    return {
        strategy_name: _trade_metrics_for_trades(trades)
        for strategy_name, trades in sorted(grouped.items())
    }


def bootstrap_pass_rate_distribution(
    results: list[ChallengeResult],
    *,
    bootstrap_b: int = 1000,
    rng_seed: int = 0,
) -> np.ndarray:
    """Return the bootstrap pass-rate sample distribution for plotting."""

    if bootstrap_b <= 0:
        raise ValueError("bootstrap_b must be positive")
    if not results:
        return np.array([], dtype=float)

    outcomes = np.array([1.0 if result.outcome == "passed" else 0.0 for result in results], dtype=float)
    rng = np.random.default_rng(rng_seed)
    return rng.choice(outcomes, size=(bootstrap_b, len(outcomes)), replace=True).mean(axis=1)


def _annualized_ratio(mean_return: float, std_return: float) -> float:
    if np.isnan(mean_return) or np.isnan(std_return) or std_return <= 0.0:
        return float(np.nan)
    return float((mean_return / std_return) * np.sqrt(PERIODS_PER_YEAR_1H))


def _trade_metrics_for_trades(trades: tuple[Trade, ...] | list[Trade]) -> TradeMetrics:
    trades_seq = tuple(trades)
    n_trades = len(trades_seq)
    if n_trades == 0:
        return TradeMetrics(
            n_trades=0,
            n_wins=0,
            n_losses=0,
            n_breakeven=0,
            win_rate=0.0,
            profit_factor=0.0,
            r_expectancy=0.0,
            payoff_ratio=0.0,
            avg_trade_pnl=0.0,
            total_pnl=0.0,
        )

    pnl = np.array([trade.pnl_account_ccy for trade in trades_seq], dtype=float)
    wins = pnl > BREAKEVEN_EPSILON
    losses = pnl < -BREAKEVEN_EPSILON
    breakeven = ~(wins | losses)

    gross_wins = float(pnl[wins].sum())
    gross_losses = float(pnl[losses].sum())
    avg_win = float(pnl[wins].mean()) if wins.any() else 0.0
    avg_loss = float(pnl[losses].mean()) if losses.any() else 0.0

    if losses.any():
        profit_factor = gross_wins / abs(gross_losses)
    elif wins.any():
        profit_factor = float(np.inf)
    else:
        profit_factor = 0.0

    if losses.any() and wins.any():
        payoff_ratio = avg_win / abs(avg_loss)
    elif wins.any():
        payoff_ratio = float(np.inf)
    else:
        payoff_ratio = 0.0

    risk_values = np.array([trade.risk_at_open_account_ccy for trade in trades_seq], dtype=float)
    valid_risk = risk_values > BREAKEVEN_EPSILON
    if valid_risk.any():
        r_expectancy = float((pnl[valid_risk] / risk_values[valid_risk]).mean())
    else:
        r_expectancy = 0.0

    return TradeMetrics(
        n_trades=n_trades,
        n_wins=int(wins.sum()),
        n_losses=int(losses.sum()),
        n_breakeven=int(breakeven.sum()),
        win_rate=float(wins.sum() / n_trades),
        profit_factor=float(profit_factor),
        r_expectancy=r_expectancy,
        payoff_ratio=float(payoff_ratio),
        avg_trade_pnl=float(pnl.mean()),
        total_pnl=float(pnl.sum()),
    )
