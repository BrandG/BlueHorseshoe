"""Portfolio-level collection and deterministic ordering of exit events.

Intrabar events are extracted per position, but FTMO rule enforcement depends on
account-wide chronological ordering. This module produces the sorted event list
consumed by the future engine loop.
"""

from __future__ import annotations

# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import pandas as pd

from bh_ftmo.backtest import intrabar
from bh_ftmo.backtest.commission import commission_at_close
from bh_ftmo.backtest.equity import EquityCurve, equity
from bh_ftmo.backtest.position import realized_pnl_account_ccy
from bh_ftmo.backtest.types import ExitEvent, PairSpec, Position, RuleBreach, Trade

if TYPE_CHECKING:
    from bh_ftmo.backtest.ftmo_rules import FtmoRuleEngine

_KIND_PRIORITY = {
    "stop": 0,
    "target": 1,
    "swap": 2,
    "weekend_flatten": 3,
    "deadline": 4,
    "session_close": 5,
}


def collect_and_sort(
    open_positions: list[Position],
    bar_4h_by_symbol: dict[str, pd.Series],
    bars_1h_by_symbol: dict[str, pd.DataFrame],
    pip_sizes: dict[str, float],
) -> list[ExitEvent]:
    """Collect all candidate events for open positions and sort deterministically."""

    events: list[ExitEvent] = []
    for position in open_positions:
        events.extend(
            intrabar.extract_events(
                position,
                bar_4h=bar_4h_by_symbol[position.symbol],
                bars_1h=bars_1h_by_symbol[position.symbol],
                pip_size=pip_sizes[position.symbol],
            )
        )
    return sorted(events, key=lambda event: (event.ts, event.symbol, _KIND_PRIORITY.get(event.kind, 99)))


def _exit_reason_for(kind: str) -> str:
    if kind == "stop":
        return "stop"
    if kind == "target":
        return "target"
    if kind == "weekend_flatten":
        return "weekend_flatten"
    if kind == "deadline":
        return "deadline_flatten"
    if kind == "session_close":
        return "session_close"
    raise ValueError(f"unsupported exit event kind: {kind}")


def apply_in_order(
    events: list[ExitEvent],
    open_positions: dict[int, Position],
    cash: float,
    pip_specs: dict[str, PairSpec],
    pip_values_at: Callable[[datetime, str], float],
    commission_per_lot_round_turn: float,
    equity_curve: EquityCurve,
    rule_engine: FtmoRuleEngine,
    bid_at: dict[str, float],
    ask_at: dict[str, float],
) -> tuple[dict[int, Position], float, list[Trade], Optional[RuleBreach]]:
    """Apply chronologically-sorted events to portfolio state.

    For each event the function realizes P&L, debits close commission, emits a
    trade ledger row, records the resulting account equity, and checks FTMO
    rules immediately. The first returned breach halts further event processing.

    The ``pip_specs`` argument is carried for API compatibility with the engine
    contracts and to make symbol coverage explicit to callers.
    """

    del pip_specs
    updated_positions = dict(open_positions)
    new_trades: list[Trade] = []

    for event in events:
        if event.kind == "swap":
            raise ValueError("swap ExitEvent is invalid in apply_in_order; swap is cash-only")

        position = updated_positions.pop(event.position_id, None)
        if position is None:
            continue

        pip_value = float(pip_values_at(event.ts, position.symbol))
        realized_pnl = realized_pnl_account_ccy(position, close_price=event.price, pip_value=pip_value)
        close_commission = commission_at_close(position.lots, commission_per_lot_round_turn)
        net_pnl = realized_pnl - close_commission
        cash += net_pnl

        new_trades.append(
            Trade(
                symbol=position.symbol,
                strategy=position.strategy,
                direction=position.direction,
                open_ts=position.open_ts,
                open_price=position.open_price,
                close_ts=event.ts,
                close_price=event.price,
                stop=position.stop,
                target=position.target,
                lots=position.lots,
                risk_at_open_account_ccy=position.risk_at_open_account_ccy,
                pnl_account_ccy=net_pnl,
                swap_account_ccy=0.0,
                commission_account_ccy=close_commission,
                exit_reason=_exit_reason_for(event.kind),
                components={},
            )
        )

        rule_engine.on_trade_event(event.ts)
        remaining_pip_values = {
            position_.symbol: float(pip_values_at(event.ts, position_.symbol))
            for position_ in updated_positions.values()
        }
        current_equity = equity(
            cash=cash,
            positions=list(updated_positions.values()),
            bid_at=bid_at,
            ask_at=ask_at,
            pip_values=remaining_pip_values,
        )
        equity_curve.record(event.ts, current_equity)
        breach = rule_engine.on_equity_update(event.ts, current_equity)
        if breach is not None:
            return updated_positions, cash, new_trades, breach

    return updated_positions, cash, new_trades, None
