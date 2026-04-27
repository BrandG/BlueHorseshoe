"""Immutable value types used by the BH FTMO backtest primitives layer.

These dataclasses are the stable contracts shared by the Phase 3 backtest
modules. They intentionally contain data only: no validation logic, mutation,
or engine orchestration lives here.
"""

from __future__ import annotations

# pylint: disable=too-many-instance-attributes

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

import pandas as pd

from bh_ftmo.analysis.strategy import Signal


@dataclass(frozen=True)
class PairSpec:
    """Static FX pair metadata required for pricing and sizing calculations."""

    symbol: str
    pip_size: float
    contract_size: int


@dataclass(frozen=True)
class Position:
    """An open simulated position with immutable entry and risk parameters."""

    id: int
    symbol: str
    strategy: str
    direction: int
    open_ts: datetime
    open_price: float
    stop: float
    target: float
    lots: float
    risk_at_open_account_ccy: float


@dataclass(frozen=True)
class Trade:
    """A realized trade ledger row emitted when a position fully closes."""

    symbol: str
    strategy: str
    direction: int
    open_ts: datetime
    open_price: float
    close_ts: datetime
    close_price: float
    stop: float
    target: float
    lots: float
    risk_at_open_account_ccy: float
    pnl_account_ccy: float
    swap_account_ccy: float
    commission_account_ccy: float
    exit_reason: Literal[
        "target",
        "stop",
        "ftmo_breach",
        "session_close",
        "weekend_flatten",
        "deadline_flatten",
    ]
    components: dict[str, float]


@dataclass(frozen=True)
class ExitEvent:
    """A timestamped position event used for deterministic portfolio ordering."""

    ts: datetime
    symbol: str
    kind: Literal["stop", "target", "swap", "weekend_flatten", "deadline", "session_close"]
    price: float
    position_id: int


@dataclass(frozen=True)
class RuleBreach:
    """A hard FTMO rule breach captured at the instant of failure."""

    rule: Literal["daily_loss", "max_loss", "max_trading_days"]
    timestamp: datetime
    equity_at_breach: float
    threshold: float


@dataclass(frozen=True)
class ChallengeResult:
    """Full outcome of a single FTMO challenge simulation.

    Per P3-17, equity_curve is the 1h-resampled canonical series — the basis
    for Sharpe/Sortino/MaxDD. equity_curve_daily is FTMO-day-end samples for
    reporter charts.
    """

    start_ts: datetime
    end_ts: datetime
    outcome: Literal["passed", "failed", "push", "in_progress"]
    failed_by: Optional[str]
    target_hit_at: Optional[datetime]
    trading_days: int
    final_equity_account_ccy: float
    trades: tuple[Trade, ...]
    breaches: tuple[RuleBreach, ...]
    equity_curve: pd.Series
    equity_curve_daily: pd.Series
    skipped_signals: tuple[tuple[Signal, str], ...]
    rng_seed: int
    non_convertible_position_events: int = 0


@dataclass(frozen=True)
class GateCriterion:
    """One locked Phase 3 gate criterion with threshold and actual value."""

    name: str
    threshold: float
    actual: float
    passed: bool


@dataclass(frozen=True)
class GateResult:
    """Structured verdict for the Phase 3 entry-edge gate."""

    overall_passed: bool
    criteria: tuple[GateCriterion, ...]
    bh_ftmo_pass_rate: float
    best_baseline_name: Optional[str]
    best_baseline_pass_rate: float
    margin_vs_best_baseline_pp: float
    notes: str
