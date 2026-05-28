"""Account-level safety gates for OANDA paper-trading deployments.

Two fail-closed gates, shared by all paper traders:

  margin_gate_allows()    — run-level. Aborts the whole tick if marginUsed/NAV
                            is already over the cap. Uses NAV (not balance) so
                            the check reacts to unrealized drawdown immediately.
  direction_gate_allows() — per-order. Refuses any order that would push
                            |n_long - n_short| above the imbalance cap.
                            Prevents broad-regime signals (e.g. USD weakness
                            firing across the universe) from stacking the
                            account net-long the same correlated basket.
"""
from __future__ import annotations

from typing import Iterable, Mapping

MAX_MARGIN_UTILIZATION = 0.40
MAX_NET_DIRECTION_IMBALANCE = 12


def margin_utilization(summary: Mapping) -> float:
    nav = float(summary.get("NAV", summary.get("balance", 0.0)))
    if nav <= 0:
        return float("inf")
    return float(summary.get("marginUsed", 0.0)) / nav


def margin_gate_allows(summary: Mapping) -> tuple[bool, str]:
    util = margin_utilization(summary)
    if util > MAX_MARGIN_UTILIZATION:
        return False, (f"margin utilization {util:.1%} > cap "
                       f"{MAX_MARGIN_UTILIZATION:.0%}")
    return True, f"margin utilization {util:.1%} ok"


def margin_headroom(summary: Mapping, cap: float = MAX_MARGIN_UTILIZATION) -> float:
    """Return remaining account-currency margin budget under ``cap``.

    Negative/zero headroom is intentional: callers can continue evaluating
    candidates while naturally refusing new orders that do not fit.
    """
    nav = float(summary.get("NAV", summary.get("balance", 0.0)))
    if nav <= 0:
        return float("-inf")
    return (cap * nav) - float(summary.get("marginUsed", 0.0))


def estimate_order_margin(
    units: int,
    entry_price: float,
    quote_to_account: float,
    margin_rate: float,
) -> float:
    """Estimate margin for a forex order in account currency."""
    return abs(units) * entry_price * quote_to_account * margin_rate


def count_open_directions(positions: Iterable[Mapping]) -> tuple[int, int]:
    n_long = 0
    n_short = 0
    for p in positions:
        try:
            if int(p.get("long", {}).get("units", "0")) != 0:
                n_long += 1
            if int(p.get("short", {}).get("units", "0")) != 0:
                n_short += 1
        except (TypeError, ValueError):
            continue
    return n_long, n_short


def direction_gate_allows(
    direction: str, n_long: int, n_short: int,
) -> tuple[bool, str]:
    if direction == "long":
        new_imbalance = (n_long + 1) - n_short
        side = "long"
    elif direction == "short":
        new_imbalance = (n_short + 1) - n_long
        side = "short"
    else:
        raise ValueError(f"direction must be 'long'|'short', got {direction!r}")
    if new_imbalance > MAX_NET_DIRECTION_IMBALANCE:
        return False, (f"would push net {side} imbalance to {new_imbalance} "
                       f"(cap {MAX_NET_DIRECTION_IMBALANCE})")
    return True, ""
