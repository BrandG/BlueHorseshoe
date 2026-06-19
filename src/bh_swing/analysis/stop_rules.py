"""Stop-management and exit decision logic.

Pure functions — no IBKR calls, no Mongo writes. The monitor calls these,
feeds the result through safety gates, and only then mutates the broker.

Phase 1 ships **breakeven** advancement: when a T1 half fills on a split
bracket, move the T2 leg's stop up to the entry price. This locks in $0
minimum on the remainder. The midpoint and ATR-clamped variants stay as
config-swappable alternatives.

Dynamic early-exit lives here too but the rule is intentionally **off by
default** until sub-phase 1c. The hook exists so the monitor wiring is
forward-compatible.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from bh_swing.analysis.position_state import ManagedPosition


# ---------------------------------------------------------------------------
# Stop advancement
# ---------------------------------------------------------------------------

class StopRule(str, Enum):
    """Which advancement policy to apply when T1 fills."""
    BREAKEVEN = "breakeven"
    MIDPOINT = "midpoint"        # not yet enabled
    ATR_CLAMPED = "atr_clamped"  # not yet enabled


@dataclass(frozen=True)
class StopAdvancement:
    """A proposed stop modification for one bracket leg."""
    symbol: str
    leg: str                # "T1" | "T2" — whose stop are we moving?
    order_id: int           # the STP order to modify at IBKR
    current_stop: float
    new_stop: float
    side: str               # "long" | "short"
    reason: str             # human-readable; lands in journal note


def propose_stop_advancement(
    position: ManagedPosition, rule: StopRule = StopRule.BREAKEVEN,
) -> Optional[StopAdvancement]:
    """Decide whether to move the T2 leg's stop, and where to.

    Trigger: T1's *take-profit* has fired (half-position sold at a profit).
    Action (breakeven): move T2's remaining stop up to the original entry
    price, locking the rest of the trade into "free roll" territory.

    Returns None if no advancement is warranted (T1 TP not filled, T2 stop
    already at-or-past breakeven, T2 stop missing, etc.). The monitor
    treats None as "leave it alone."
    """
    if rule != StopRule.BREAKEVEN:
        # Other rules are placeholders — explicit "not yet" rather than silent default.
        return None

    t1 = position.t1
    t2 = position.t2
    if t1 is None or t2 is None:
        return None
    if not position.t1_take_profit_filled:
        return None  # T1 hasn't taken profit yet — nothing to advance
    if t2.stop_order is None or not t2.stop_is_alive:
        return None  # nothing to move

    current_stop = t2.stop_order.stop_price
    # Already at or past breakeven? (>= for long, <= for short.) No-op.
    if position.side == "long" and current_stop >= position.entry_price:
        return None
    if position.side == "short" and current_stop <= position.entry_price:
        return None

    return StopAdvancement(
        symbol=position.symbol,
        leg="T2",
        order_id=t2.stop_order.order_id,
        current_stop=current_stop,
        new_stop=round(position.entry_price, 2),
        side=position.side,
        reason=(
            f"T1 TP filled @ {t1.take_profit_price:.2f} "
            f"-> advance T2 stop to breakeven {position.entry_price:.2f}"
        ),
    )


# ---------------------------------------------------------------------------
# Dynamic early-exit (Phase 1c — wired but disabled by default)
# ---------------------------------------------------------------------------

class ExitAction(str, Enum):
    HOLD = "hold"
    TIGHTEN_STOP = "tighten_stop"
    CLOSE_NOW = "close_now"


@dataclass(frozen=True)
class EarlyExitDecision:
    """The outcome of a per-position EOD re-score."""
    symbol: str
    action: ExitAction
    reason: str
    # Populated only when action == TIGHTEN_STOP
    proposed_stop: Optional[float] = None


def propose_early_exit(
    position: ManagedPosition,
    *,
    current_score: Optional[float] = None,
    entry_score: Optional[float] = None,
    enabled: bool = False,
) -> Optional[EarlyExitDecision]:
    """Decide whether to close or tighten a position at end-of-day.

    Disabled by default until Phase 1c. When ``enabled=False`` returns
    None unconditionally so the monitor's call path is no-op until we
    deliberately flip the switch.

    The rule (when enabled) mirrors bh_lite.check_position_health's
    structure: score collapse OR price-vs-stop proximity drives a tighten
    or close decision. Stubbed here; concrete thresholds get added in 1c
    after live mechanical management has run clean for a week.
    """
    if not enabled:
        return None
    # Concrete implementation deferred to sub-phase 1c.
    # Returning a HOLD ensures the rest of the pipeline can be wired and
    # smoke-tested before the rule itself is tuned.
    return EarlyExitDecision(
        symbol=position.symbol,
        action=ExitAction.HOLD,
        reason="early-exit rule not yet calibrated; holding",
    )


# ---------------------------------------------------------------------------
# range_support sleeve exit (Phase C) — up-day ratchet + ~25-bar time flatten
# ---------------------------------------------------------------------------
# Pure functions: the manager loads the daily bars from DuckDB and passes scalars
# (last_close, prior_close, atr, bars_since_entry) so these stay unit-testable with
# no I/O. Scoping to the range_support sleeve is the manager's job; these assume the
# position is a single-stop, no-take-profit long bracket (recorded as the "T2" leg).

def _single_stop_leg(position: ManagedPosition):
    """The lone exit leg of a no-take-profit bracket (recorded as T2; fall back to T1)."""
    return position.t2 or position.t1


def propose_stop_ratchet(
    position: ManagedPosition,
    *,
    last_close: float,
    prior_close: float,
    atr: float,
    ratchet_atr: float = 2.0,
) -> Optional[StopAdvancement]:
    """Up-day ratchet (the validated range_support exit): on a completed UP-close daily bar,
    move the single stop up to ``last_close - ratchet_atr*ATR``, ratchet-only.

    Long-only. Idempotent per daily bar — proposes only when the new stop is strictly higher
    than the current one, so re-ticks within the same day (same close) are no-ops, and it only
    moves again when a fresh higher up-close bar arrives. Returns None when not warranted.
    """
    if position.side != "long":
        return None
    leg = _single_stop_leg(position)
    if leg is None or leg.stop_order is None or not leg.stop_is_alive:
        return None
    if not (atr > 0) or last_close <= 0 or prior_close <= 0:
        return None
    if last_close <= prior_close:                 # only ratchet on an up-close day
        return None
    current_stop = leg.stop_order.stop_price
    new_stop = round(last_close - ratchet_atr * atr, 2)
    if new_stop <= current_stop:                  # ratchet-only — never lower / never re-fire flat
        return None
    return StopAdvancement(
        symbol=position.symbol,
        leg=leg.leg,
        order_id=leg.stop_order.order_id,
        current_stop=current_stop,
        new_stop=new_stop,
        side=position.side,
        reason=(
            f"up-day ratchet: close {last_close:.2f} > prior {prior_close:.2f} "
            f"-> stop {new_stop:.2f} (close - {ratchet_atr:g}*ATR)"
        ),
    )


def propose_time_flatten(
    position: ManagedPosition,
    *,
    bars_since_entry: Optional[int],
    hold_days: int = 25,
    enabled: bool = False,
) -> Optional[EarlyExitDecision]:
    """Flatten the position once ~``hold_days`` completed daily bars have elapsed since entry
    (the validated time cap). Returns a CLOSE_NOW decision, or None.

    Disabled by default: the manager must pass ``enabled=True`` (gated behind the monitor's
    --enable-time-flatten) because this is an autonomous market-sell, not just a stop move.
    """
    if not enabled:
        return None
    if bars_since_entry is None or bars_since_entry < hold_days:
        return None
    return EarlyExitDecision(
        symbol=position.symbol,
        action=ExitAction.CLOSE_NOW,
        reason=f"time exit: {bars_since_entry} bars held >= {hold_days}-bar cap",
    )
