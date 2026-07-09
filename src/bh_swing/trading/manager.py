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
    # range_support sleeve exit (Phase C). RETIRED 2026-07-08: the monitor cannot modify the
    # PaperTrader-placed stop cross-session — every attempt was rejected by IBKR Error 103
    # ("Duplicate order id") and cancelled, so the stop never actually moved (and modify_order_stop
    # reported phantom success, re-firing every tick). Superseded by a native broker-managed
    # trailing stop placed at entry by PaperTrader (initial trigger 1xATR, trail 2xATR); the broker
    # ratchets it server-side, so the monitor no longer touches range_support stops. OFF by default.
    range_support_ratchet_enabled: bool = False
    range_support_ratchet_atr: float = 2.0     # stop -> close - this*ATR on up-close days
    range_support_hold_days: int = 25          # bar cap for the time-flatten
    time_flatten_enabled: bool = False
    store: object = None                        # read-only DuckDBStore for daily bars/ATR


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


def _to_date_str(dt) -> str:
    """Normalize a submitted_at (datetime or 'YYYY-MM-DD...' string) to a 'YYYY-MM-DD' date."""
    if dt is None:
        return ""
    if hasattr(dt, "strftime"):
        return dt.strftime("%Y-%m-%d")
    return str(dt)[:10]


def _daily_features(store, symbol: str, entry_datetime) -> Optional[dict]:
    """Load recent daily bars for ``symbol`` and derive the scalars the range_support rules need.

    Returns {last_close, prior_close, atr, bars_since_entry, last_date} from the latest COMPLETED
    daily bars in DuckDB (updated by the -u pipeline after each close), or None if unavailable.
    """
    if store is None:
        return None
    try:
        import numpy as np
        from bluehorseshoe.analysis.indicators import support_levels as sl
        df = store.load_symbol(symbol)
        if df is None or len(df) < 16:
            return None
        close = df["close"].to_numpy(float)
        high = df["high"].to_numpy(float)
        low = df["low"].to_numpy(float)
        atr_arr = sl.wilder_atr(high, low, close, 14)
        atr = float(atr_arr[-1])
        if np.isnan(atr) or atr <= 0:
            atr = float(np.nanmedian(atr_arr))
        dates = df["date"].astype(str).tolist()
        bars_since_entry = None
        edate = _to_date_str(entry_datetime)
        if edate:
            bars_since_entry = sum(1 for d in dates if d > edate)   # completed bars after entry
        return {
            "last_close": float(close[-1]),
            "prior_close": float(close[-2]),
            "atr": atr,
            "bars_since_entry": bars_since_entry,
            "last_date": dates[-1],
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("daily features unavailable for %s: %s", symbol, e)
        return None


def _flatten_position(client, pos, leg) -> dict:
    """Close a range_support position at the time-cap: cancel its working stop, then market-sell
    the held quantity. Cancelling first prevents the stop from firing into a no-longer-held position
    (which would open a short). Returns {status, error}.
    """
    qty = abs(int(pos.broker_position_qty))
    if qty <= 0:
        return {"status": "error", "error": "no shares to flatten"}
    if leg is not None and leg.stop_order is not None:
        cancel = client.cancel_order(leg.stop_order.order_id)
        if cancel.get("status") not in ("submitted", "cancelled", "Cancelled", "PendingCancel"):
            return {"status": "error", "error": f"stop cancel failed: {cancel.get('error')}"}
    sell = client.place_market_order(pos.symbol, "SELL", qty)
    return sell


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

    # ---- range_support sleeve exit (Phase C): time flatten + up-day ratchet ----
    for pos in build.managed:
        if pos.strategy != "range_support":
            continue
        feats = _daily_features(config.store, pos.symbol, pos.entry_datetime)
        if feats is None:
            _emit(journal.EVENT_STATE_DRIFT, run_mode=run_mode, symbol=pos.symbol,
                  note="range_support: daily features unavailable; skip ratchet/flatten")
            continue
        leg = pos.t2 or pos.t1

        # (1) Time flatten first — if the position is at the bar cap we close it and skip the
        #     ratchet (no point modifying a stop we're about to cancel). Autonomous sell, gated.
        if config.time_flatten_enabled:
            flat = stop_rules.propose_time_flatten(
                pos, bars_since_entry=feats["bars_since_entry"],
                hold_days=config.range_support_hold_days, enabled=True,
            )
            if flat is not None:
                qty = abs(int(pos.broker_position_qty))
                summary.proposed += 1
                _emit(journal.EVENT_ACTION_PROPOSED, run_mode=run_mode, symbol=pos.symbol,
                      quantity=qty, note=f"flatten: {flat.reason}")
                ok, reason = safety.actions_under_rate_limit(actions_taken, config.action_rate_limit)
                if not ok:
                    summary.skipped += 1
                    _emit(journal.EVENT_ACTION_SKIPPED, run_mode=run_mode, symbol=pos.symbol,
                          note=f"rate_limit: {reason}")
                    continue
                actions_taken += 1
                if config.dry_run:
                    _emit(journal.EVENT_WOULD_FLATTEN, run_mode=run_mode, symbol=pos.symbol,
                          quantity=qty, note=flat.reason)
                    summary.taken += 1
                else:
                    result = _flatten_position(client, pos, leg)
                    if result.get("status") in ("submitted", "filled", "Filled"):
                        summary.taken += 1
                        _emit(journal.EVENT_POSITION_FLATTENED, run_mode=run_mode, symbol=pos.symbol,
                              quantity=qty, note=flat.reason)
                    else:
                        summary.failed += 1
                        _emit(journal.EVENT_ACTION_FAILED, run_mode=run_mode, symbol=pos.symbol,
                              note=f"flatten failed: {result.get('error', 'unknown')}")
                continue  # flattened (or attempted) — don't also ratchet this position

        # (2) Up-day ratchet — a stop-tightening move; flows through the same gates as breakeven.
        if config.range_support_ratchet_enabled:
            ratchet = stop_rules.propose_stop_ratchet(
                pos, last_close=feats["last_close"], prior_close=feats["prior_close"],
                atr=feats["atr"], ratchet_atr=config.range_support_ratchet_atr,
            )
            if ratchet is None:
                continue
            summary.proposed += 1
            _emit(journal.EVENT_ACTION_PROPOSED, run_mode=run_mode, symbol=ratchet.symbol,
                  order_id=str(ratchet.order_id), price=ratchet.new_stop,
                  stop_price=ratchet.current_stop, note=f"ratchet: {ratchet.reason}")
            ok, reason = safety.actions_under_rate_limit(actions_taken, config.action_rate_limit)
            if not ok:
                summary.skipped += 1
                _emit(journal.EVENT_ACTION_SKIPPED, run_mode=run_mode, symbol=ratchet.symbol,
                      note=f"rate_limit: {reason}")
                continue
            ok, reason = safety.stop_move_is_tightening(
                ratchet.current_stop, ratchet.new_stop, ratchet.side)
            if not ok:
                summary.skipped += 1
                _emit(journal.EVENT_ACTION_SKIPPED, run_mode=run_mode, symbol=ratchet.symbol,
                      note=f"would_widen: {reason}")
                continue
            actions_taken += 1
            if config.dry_run:
                _emit(journal.EVENT_WOULD_RATCHET, run_mode=run_mode, symbol=ratchet.symbol,
                      order_id=str(ratchet.order_id), price=ratchet.new_stop,
                      stop_price=ratchet.current_stop, note=ratchet.reason)
                summary.taken += 1
            else:
                result = client.modify_order_stop(ratchet.order_id, ratchet.new_stop)
                if result.get("status") == "submitted":
                    summary.taken += 1
                    _emit(journal.EVENT_STOP_RATCHETED, run_mode=run_mode, symbol=ratchet.symbol,
                          order_id=str(ratchet.order_id), price=ratchet.new_stop,
                          stop_price=ratchet.current_stop, note=ratchet.reason)
                else:
                    summary.failed += 1
                    _emit(journal.EVENT_ACTION_FAILED, run_mode=run_mode, symbol=ratchet.symbol,
                          order_id=str(ratchet.order_id),
                          note=f"modify_order_stop: {result.get('error', 'unknown')}")

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
