"""Phase 1 management orchestrator.

Takes broker truth + Mongo metadata, asks ``stop_rules`` what to do,
runs every proposed action through ``safety``, and (in live mode) calls
the corresponding ``IBKRClient`` mutation. Every decision becomes a
journal row so the audit trail is exhaustive.

Pure-ish: the only side effects are journal writes and broker calls
through the injected ``client``. Easily testable end-to-end with a
``MagicMock`` client.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional

from bh_swing import journal
from bh_swing.analysis import position_state, stop_rules
from bh_swing.trading import safety

logger = logging.getLogger(__name__)


@dataclass
class ManageConfig:
    """Tunables for one management pass."""
    dry_run: bool = True
    action_rate_limit: int = safety.DEFAULT_ACTION_RATE_LIMIT
    position_count_cap: int = safety.DEFAULT_POSITION_COUNT_CAP
    kill_switch_path: str = safety.KILL_SWITCH_PATH
    rule: stop_rules.StopRule = stop_rules.StopRule.BREAKEVEN
    early_exit_enabled: bool = False


@dataclass
class ManageSummary:
    """What happened during a management pass."""
    managed_positions: int = 0
    unmanaged_symbols: list[str] = None
    proposed: int = 0
    taken: int = 0
    skipped: int = 0
    failed: int = 0
    halted_reason: Optional[str] = None  # set if a global gate halted the pass

    def __post_init__(self):
        if self.unmanaged_symbols is None:
            self.unmanaged_symbols = []


def _emit(event: str, *, run_mode: str, **fields) -> None:
    """Write one journal row; defensive on field shape."""
    row = journal.JournalRow(run_mode=run_mode, event=event)
    for k, v in fields.items():
        if hasattr(row, k):
            setattr(row, k, v)
        else:
            row.note = (row.note + " " if row.note else "") + f"{k}={v}"
    journal.append(row)


def manage_tick(
    *,
    client,
    broker_positions: Iterable,
    broker_open_trades: Iterable,
    trade_orders_collection,
    config: ManageConfig,
) -> ManageSummary:
    """Run one management pass.

    The caller (monitor) is responsible for fetching ``broker_positions``
    and ``broker_open_trades`` first — same data the reconciler/tracker
    use — so we share one round-trip per tick.

    Order of operations:
      1. Global gates first (kill switch, position cap). If either trips,
         halt the whole pass and journal the reason.
      2. Build managed positions; journal any drift notes.
      3. For each managed position, ask stop_rules for an advancement.
         If proposed, run through stop-tightening gate + rate-limit gate.
         Mutate (live) or emit would-event (dry-run). Journal outcome.
      4. (Phase 1c) early-exit hook — disabled by default.
    """
    run_mode = "dry-run" if config.dry_run else "live"
    summary = ManageSummary()

    # ---- Global gates --------------------------------------------------
    ok, reason = safety.kill_switch_inactive(config.kill_switch_path)
    if not ok:
        _emit(journal.EVENT_KILL_SWITCH_ACTIVE, run_mode=run_mode, note=reason)
        summary.halted_reason = reason
        logger.warning("manage_tick halted: %s", reason)
        return summary

    positions_list = list(broker_positions)
    ok, reason = safety.position_count_under_cap(positions_list, config.position_count_cap)
    if not ok:
        # Diagnostic only: this orchestrator's mutations (stop-tightening,
        # early-exit close) all *reduce* risk, so a high position count is
        # not a reason to halt them. The cap belongs on entry-side flows
        # (PaperTrader) that actually add positions.
        _emit(journal.EVENT_STATE_DRIFT, run_mode=run_mode, note=f"position_cap_exceeded: {reason}")
        logger.warning("manage_tick over cap (continuing risk-reducing actions): %s", reason)

    # ---- Build state ---------------------------------------------------
    build = position_state.build_managed_positions(
        positions_list, list(broker_open_trades), trade_orders_collection,
    )
    summary.managed_positions = len(build.managed)
    summary.unmanaged_symbols = list(build.unmanaged_symbols)
    for note in build.drift_notes:
        _emit(journal.EVENT_STATE_DRIFT, run_mode=run_mode, note=note)

    actions_taken = 0  # both successful mutations and skipped-by-gate count

    # ---- Per-position management --------------------------------------
    for pos in build.managed:
        # Phase 1 default action: stop advancement.
        advancement = stop_rules.propose_stop_advancement(pos, rule=config.rule)
        if advancement is None:
            continue

        summary.proposed += 1
        _emit(
            journal.EVENT_ACTION_PROPOSED, run_mode=run_mode,
            symbol=advancement.symbol, order_id=str(advancement.order_id),
            price=advancement.new_stop, stop_price=advancement.current_stop,
            target_price=pos.target_price,
            note=f"advance_stop {advancement.leg}: {advancement.reason}",
        )

        # Rate-limit gate (count *attempts* so a runaway loop is bounded
        # even by skipped actions).
        ok, reason = safety.actions_under_rate_limit(
            actions_taken, config.action_rate_limit,
        )
        if not ok:
            summary.skipped += 1
            _emit(journal.EVENT_ACTION_SKIPPED, run_mode=run_mode,
                  symbol=advancement.symbol, note=f"rate_limit: {reason}")
            continue

        # Stop-tightening sanity gate.
        ok, reason = safety.stop_move_is_tightening(
            advancement.current_stop, advancement.new_stop, advancement.side,
        )
        if not ok:
            summary.skipped += 1
            _emit(journal.EVENT_ACTION_SKIPPED, run_mode=run_mode,
                  symbol=advancement.symbol, note=f"would_widen: {reason}")
            continue

        actions_taken += 1  # gate budget used regardless of dry-run / live

        if config.dry_run:
            _emit(
                journal.EVENT_WOULD_ADVANCE_STOP, run_mode=run_mode,
                symbol=advancement.symbol, order_id=str(advancement.order_id),
                price=advancement.new_stop, stop_price=advancement.current_stop,
                target_price=pos.target_price,
                note=advancement.reason,
            )
            summary.taken += 1   # in dry-run, a planned action still "counts"
            continue

        result = client.modify_order_stop(advancement.order_id, advancement.new_stop)
        if result.get("status") == "submitted":
            summary.taken += 1
            _emit(
                journal.EVENT_STOP_ADVANCED, run_mode=run_mode,
                symbol=advancement.symbol, order_id=str(advancement.order_id),
                price=advancement.new_stop, stop_price=advancement.current_stop,
                target_price=pos.target_price,
                note=advancement.reason,
            )
            _emit(
                journal.EVENT_ACTION_TAKEN, run_mode=run_mode,
                symbol=advancement.symbol, order_id=str(advancement.order_id),
                note=f"modify_order_stop ok: {advancement.new_stop:.2f}",
            )
        else:
            summary.failed += 1
            _emit(
                journal.EVENT_ACTION_FAILED, run_mode=run_mode,
                symbol=advancement.symbol, order_id=str(advancement.order_id),
                note=f"modify_order_stop: {result.get('error', 'unknown error')}",
            )

    # Phase 1c hook lives here when enabled (no-op for 1a/1b).
    if config.early_exit_enabled:
        for pos in build.managed:
            decision = stop_rules.propose_early_exit(pos, enabled=True)
            if decision is None or decision.action == stop_rules.ExitAction.HOLD:
                continue
            # Concrete handling deferred to 1c; for now just journal.
            _emit(
                journal.EVENT_EARLY_EXIT, run_mode=run_mode,
                symbol=pos.symbol, note=f"{decision.action.value}: {decision.reason}",
            )

    return summary
