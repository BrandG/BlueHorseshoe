"""Swap-charge primitives for FTMO rollover accounting.

These helpers model one rollover event at a time. The caller is responsible for
providing already-resolved per-symbol swap rates and for applying the resulting
cash adjustments before capturing the new FTMO-day baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from bh_ftmo.backtest.types import Position


@dataclass(frozen=True)
class SwapRates:
    """Directional daily swap rates for one instrument."""

    long_rate: float
    short_rate: float



def is_wednesday(day: date) -> bool:
    """Return whether the supplied rollover date is a Wednesday."""

    return day.weekday() == 2



def daily_swap_charge(
    position: Position,
    rates: SwapRates,
    rollover_date: date,
    bar_duration_days: float = 1.0,
) -> float:
    """Return the swap cashflow for one rollover event and one open position.

    Wednesday rollovers carry triple financing per FTMO convention. Positive
    rates return credits and negative rates return charges.
    """

    rate = rates.long_rate if position.direction > 0 else rates.short_rate
    multiplier = 3.0 if is_wednesday(rollover_date) else 1.0
    return position.lots * rate * bar_duration_days * multiplier



def apply_swap_to_positions(
    positions: list[Position],
    rates_by_symbol: dict[str, SwapRates],
    rollover_date: date,
) -> dict[int, float]:
    """Return one rollover cashflow per open position keyed by position id."""

    return {
        position.id: daily_swap_charge(position, rates_by_symbol[position.symbol], rollover_date)
        for position in positions
    }
