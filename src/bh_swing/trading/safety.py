"""Account- and action-level safety gates for bh_swing management.

Same shape as ``src/bh_ftmo/trading/safety.py``: pure functions returning
``(allowed: bool, reason: str)``. Composed by the monitor before any
broker-mutating call; each gate's reason string lands in the journal so
audits are reviewable later.

Gates included in Phase 1:

  ``stop_move_is_tightening``  — refuse stop moves that loosen the stop
                                  (raises for shorts, lowers for longs).
                                  Hardest invariant we have. A bug that
                                  tries to widen a stop gets blocked here.
  ``actions_under_rate_limit`` — limit total broker mutations per tick.
                                  Bounds blast radius of a runaway loop.
  ``position_count_under_cap`` — diagnostic check: returns False when the
                                  account holds more positions than the
                                  system expects. Callers that *add* risk
                                  (e.g. PaperTrader) should halt on a
                                  False return; callers that only *reduce*
                                  risk (the management orchestrator) should
                                  log it and continue — stop-tightening on
                                  a 15-position book is safer than letting
                                  those positions go unmanaged.
  ``kill_switch_inactive``     — checks for a sentinel file. Touch the
                                  file from any SSH session and all
                                  mutations pause within one tick.
"""
from __future__ import annotations

import os
from typing import Iterable

from bluehorseshoe.core.config import REPO_ROOT

# Defaults — overridable from monitor via env vars or config later.
# Rate limit bumped from 3 to 15 on 2026-05-20: with 9 T1 fires observed in a
# single trading session, a cap of 3 means stops trickle to breakeven across
# 3 ticks (15 min). The tightening gate is the real safety net (widening is
# structurally impossible), so the rate cap is just belt-and-suspenders
# against a runaway bug. 15 covers the realistic worst case (all 10 positions
# need an advancement in one tick, with room to spare).
DEFAULT_ACTION_RATE_LIMIT = 15
DEFAULT_POSITION_COUNT_CAP = 10
KILL_SWITCH_PATH = os.path.join(REPO_ROOT, ".bh_swing_pause_management")


def stop_move_is_tightening(
    current_stop: float, proposed_stop: float, side: str,
) -> tuple[bool, str]:
    """A stop move must always **tighten** — for longs that means raising
    the stop, for shorts lowering it. Returns (allowed, reason).

    A "widening" move can only ever loosen risk, never reduce it; if a
    rule ever produces one, that's a bug — refuse before sending to IBKR.
    """
    if proposed_stop <= 0:
        return False, f"proposed stop {proposed_stop} is non-positive"
    if current_stop <= 0:
        return False, f"current stop {current_stop} is non-positive (cannot tighten safely)"
    if side == "long":
        if proposed_stop > current_stop:
            return True, f"long stop {current_stop:.4f} -> {proposed_stop:.4f} tightens"
        return False, (
            f"long stop move {current_stop:.4f} -> {proposed_stop:.4f} would not tighten"
        )
    if side == "short":
        if proposed_stop < current_stop:
            return True, f"short stop {current_stop:.4f} -> {proposed_stop:.4f} tightens"
        return False, (
            f"short stop move {current_stop:.4f} -> {proposed_stop:.4f} would not tighten"
        )
    return False, f"unknown side: {side!r}"


def actions_under_rate_limit(
    actions_this_tick: int, cap: int = DEFAULT_ACTION_RATE_LIMIT,
) -> tuple[bool, str]:
    """At most N broker mutations per tick. Bounds the blast radius of a
    runaway loop or a bug that decides to advance every stop on the account.
    """
    if actions_this_tick < 0:
        return False, f"action counter is negative: {actions_this_tick}"
    if actions_this_tick >= cap:
        return False, (
            f"rate limit reached: {actions_this_tick}/{cap} actions this tick"
        )
    return True, f"{actions_this_tick}/{cap} actions used this tick"


def position_count_under_cap(
    open_positions: Iterable, cap: int = DEFAULT_POSITION_COUNT_CAP,
) -> tuple[bool, str]:
    """Refuse all mutation if the account holds more positions than the
    system expects. Tripping this is a signal that something else opened
    positions, or that the cap is misconfigured.
    """
    count = sum(1 for _ in open_positions)
    if count > cap:
        # No "halting" verb in the message — the caller decides whether to
        # halt (PaperTrader / entry-side flows) or just log and proceed (the
        # management orchestrator). See docstring above for the contract.
        return False, f"{count} open positions exceeds cap {cap}"
    return True, f"{count}/{cap} open positions"


def kill_switch_inactive(path: str = KILL_SWITCH_PATH) -> tuple[bool, str]:
    """Pause all mutations if the sentinel file exists.

    Touch ``/root/BlueHorseshoe/.bh_swing_pause_management`` from any SSH
    session to halt management within one tick. ``rm`` resumes.
    """
    if os.path.exists(path):
        return False, f"kill switch active: {path} exists"
    return True, "kill switch clear"
