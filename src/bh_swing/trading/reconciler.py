"""Broker truth -> journal events.

Stateless per run: every tick we ask IBKR for executions in a rolling window
and dedup against exec_ids we've already journaled. There is no local mirror
of broker state — IBKR is authoritative; the journal is an append-only audit
of state-change events as we observed them.

In Phase 0 the reconciler only emits `fill_detected` rows. Position-opened /
closed events are derivable from current positions + fill history and will be
emitted in Phase 1 when the monitor needs them to drive stop-management.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Mapping

from bluehorseshoe.data.ibkr_client import IBKRClient

from bh_swing import journal

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_HOURS = 24


def reconcile(
    client: IBKRClient,
    run_mode: str = "live",
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    nav: float = 0.0,
    settled_cash: float = 0.0,
) -> dict:
    """Fetch broker truth, emit journal events for any new state.

    Args:
        client: Connected (or auto-connecting) IBKRClient.
        run_mode: Tag stamped on emitted rows. "live" or "dry-run".
        lookback_hours: How far back to ask IBKR for executions.
        nav, settled_cash: Account snapshot for the journal rows.

    Returns:
        Summary dict: {fills_seen, fills_new, dup_skipped}.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    fills = client.get_executions(since=since)

    seen = journal.last_seen_exec_ids()
    new_rows: list[journal.JournalRow] = []
    dup_skipped = 0
    for fill in fills:
        exec_id = fill.get("exec_id", "")
        if not exec_id:
            continue
        if exec_id in seen:
            dup_skipped += 1
            continue

        side_raw = (fill.get("side") or "").lower()
        # IBKR returns "BOT" / "SLD"; normalize to buy/sell
        if side_raw.startswith("bot") or side_raw == "buy":
            side = "buy"
        elif side_raw.startswith("sld") or side_raw == "sell":
            side = "sell"
        else:
            side = side_raw

        new_rows.append(journal.JournalRow(
            run_mode=run_mode,
            event=journal.EVENT_FILL_DETECTED,
            symbol=fill.get("symbol", ""),
            side=side,
            quantity=int(fill.get("quantity") or 0),
            price=float(fill.get("price") or 0.0),
            order_id=str(fill.get("order_id") or ""),
            exec_id=exec_id,
            nav=nav,
            settled_cash=settled_cash,
            note=f"exec_time={fill.get('exec_time', '')}",
        ))

    if new_rows:
        journal.append_many(new_rows)
        logger.info(
            "reconciler: %d new fills journaled (%d duplicates skipped)",
            len(new_rows), dup_skipped,
        )
    else:
        logger.debug(
            "reconciler: 0 new fills (%d total in window, %d duplicates)",
            len(fills), dup_skipped,
        )

    return {
        "fills_seen": len(fills),
        "fills_new": len(new_rows),
        "dup_skipped": dup_skipped,
    }


def is_broker_reachable(account: Mapping) -> bool:
    """Did the account-summary call actually reach IBKR?

    IBKRClient.get_account_summary() returns a blank account_id only when the
    underlying connection failed (timeout, refused, etc.). A real account
    snapshot always carries the IBKR-issued account id. This is the cheapest
    signal we have for "the gateway answered" vs "we got a stub of zeros".
    """
    return bool(account.get("account_id"))


def snapshot_account(
    client: IBKRClient,
) -> tuple[dict, list[dict], list]:
    """One-shot read of broker state for HTML / status rendering.

    Returns (account_summary, positions, open_trades).
    open_trades is the raw ib_async Trade list — the renderer extracts what it
    needs without forcing a schema on the reconciler.
    """
    account = client.get_account_summary()
    positions = client.get_positions()
    open_trades = client.get_open_trades()
    return account, positions, open_trades
