"""Commission helpers for FTMO-style half-at-open, half-at-close charging."""

from __future__ import annotations



def _validate_lots(lots: float) -> None:
    """Reject negative lot sizes because they are not valid trade quantities."""

    if lots < 0:
        raise ValueError("lots must be non-negative")



def commission_at_open(lots: float, per_lot_round_turn: float) -> float:
    """Return the opening half of the round-turn commission in account currency."""

    _validate_lots(lots)
    return 0.5 * lots * per_lot_round_turn



def commission_at_close(lots: float, per_lot_round_turn: float) -> float:
    """Return the closing half of the round-turn commission in account currency."""

    _validate_lots(lots)
    return 0.5 * lots * per_lot_round_turn
