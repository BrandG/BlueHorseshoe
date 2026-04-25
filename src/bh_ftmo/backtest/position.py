"""Pure position P&L helpers for bid/ask-aware backtest bookkeeping.

These functions keep the long/short sign conventions in one place so the engine
and equity tracker can reuse the same pricing logic consistently.
"""

from __future__ import annotations

from bh_ftmo.backtest.types import Position


JPY_STYLE_QUOTES = {"JPY", "HUF"}



def _pip_size_for_symbol(symbol: str) -> float:
    """Infer the conventional pip size from the pair quote currency."""

    quote = symbol.split("_", 1)[1]
    return 0.01 if quote in JPY_STYLE_QUOTES else 0.0001



def pip_distance(
    entry_price: float,
    other_price: float,
    pip_size: float,
) -> float:
    """Return the signed pip distance between two prices."""

    return (other_price - entry_price) / pip_size



def realized_pnl_account_ccy(
    pos: Position,
    close_price: float,
    pip_value: float,
) -> float:
    """Return realized P&L in account currency for a closing price.

    The open and close prices are already side-of-spread prices, so no extra
    spread adjustment is applied here.
    """

    price_pips = pip_distance(pos.open_price, close_price, _pip_size_for_symbol(pos.symbol))
    direction_multiplier = 1.0 if pos.direction > 0 else -1.0
    return direction_multiplier * price_pips * pip_value * pos.lots



def floating_pnl_account_ccy(
    pos: Position,
    bid: float,
    ask: float,
    pip_value: float,
) -> float:
    """Return mark-to-market P&L using bid for longs and ask for shorts."""

    mark_price = bid if pos.direction > 0 else ask
    price_pips = pip_distance(pos.open_price, mark_price, _pip_size_for_symbol(pos.symbol))
    direction_multiplier = 1.0 if pos.direction > 0 else -1.0
    return direction_multiplier * price_pips * pip_value * pos.lots
