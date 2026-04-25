"""Signal-to-position conversion and trade-admission rules.

This module derives concrete entry, stop, target, and lot size values from a
Phase 2 signal and enforces the conservative Phase 3 entry skip conditions.
"""

from __future__ import annotations

# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,too-many-return-statements

from datetime import datetime
import math
from typing import Optional

import pandas as pd

from bh_ftmo.analysis.strategy import Signal
from bh_ftmo.backtest.calendar_provider import CalendarProvider
from bh_ftmo.backtest.pip_value import pip_value_in_account_ccy
from bh_ftmo.backtest.types import PairSpec, Position



def _split_symbol(symbol: str) -> tuple[str, str]:
    """Return ``(base, quote)`` for canonical pair symbols."""

    base, quote = symbol.split("_", 1)
    return base, quote



def derive_position(
    signal: Signal,
    next_bar: pd.Series,
    atr_14: float,
    pair_spec: PairSpec,
    sizing_config: dict,
    account_currency: str,
    current_equity: float,
    quote_to_account: float,
    next_position_id: int,
) -> Optional[Position]:
    """Convert a tradeable signal into an immutable open-position description."""

    if signal.direction == 0 or atr_14 <= 0 or math.isnan(atr_14):
        return None

    entry_price = float(next_bar["open_ask"] if signal.direction > 0 else next_bar["open_bid"])
    k_stop = float(sizing_config.get("k_stop", 1.5))
    k_target = float(sizing_config.get("k_target", 2.5))
    risk_pct = float(sizing_config.get("risk_pct_per_trade", 0.005))

    if signal.direction > 0:
        stop = entry_price - (k_stop * atr_14)
        target = entry_price + (k_target * atr_14)
    else:
        stop = entry_price + (k_stop * atr_14)
        target = entry_price - (k_target * atr_14)

    stop_distance_pips = abs(entry_price - stop) / pair_spec.pip_size
    if stop_distance_pips <= 0:
        return None

    pip_value = pip_value_in_account_ccy(pair_spec, account_currency, quote_to_account)
    risk_amount = current_equity * risk_pct
    lots = risk_amount / (stop_distance_pips * pip_value)
    risk_at_open = stop_distance_pips * pip_value * lots

    return Position(
        id=next_position_id,
        symbol=signal.symbol,
        strategy=signal.strategy,
        direction=signal.direction,
        open_ts=pd.Timestamp(next_bar["timestamp"]).to_pydatetime(),
        open_price=entry_price,
        stop=stop,
        target=target,
        lots=lots,
        risk_at_open_account_ccy=risk_at_open,
    )



def can_open(
    signal: Signal,
    open_positions: list[Position],
    concurrency_config: dict,
    calendar: CalendarProvider,
    bars_1h_available_for_pair: bool,
    ts_now: datetime,
) -> tuple[bool, Optional[str]]:
    """Return whether a signal may open a new position under Phase 3 rules."""

    if not bars_1h_available_for_pair:
        return False, "missing_1h_data"

    currencies = set(_split_symbol(signal.symbol))
    if calendar.is_blackout(ts_now, currencies):
        return False, "calendar_blackout"

    for pos in open_positions:
        if pos.symbol != signal.symbol:
            continue
        if pos.direction == signal.direction:
            return False, "repeat_same_direction"
        return False, "opposing_direction"

    max_positions = int(concurrency_config.get("max_concurrent_positions", 5))
    if len(open_positions) >= max_positions:
        return False, "max_concurrent_positions"

    max_per_currency = int(concurrency_config.get("max_concurrent_per_currency", 2))
    for currency in currencies:
        count = sum(currency in _split_symbol(pos.symbol) for pos in open_positions)
        if count >= max_per_currency:
            return False, "max_concurrent_per_currency"

    max_usd_basket = int(concurrency_config.get("max_concurrent_per_usd_basket", 3))
    if "USD" in currencies:
        usd_count = sum("USD" in _split_symbol(pos.symbol) for pos in open_positions)
        if usd_count >= max_usd_basket:
            return False, "max_concurrent_per_usd_basket"

    return True, None
