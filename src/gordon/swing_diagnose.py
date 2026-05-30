"""Diagnose why the bh_swing orchestrator isn't proposing what you expect.

When the monitor goes silent on a position you thought should advance — or
proposes a move that doesn't match your mental model — run this. It pulls
live broker state, queries Mongo trade_orders, runs build_managed_positions
the same way manage_tick does, and prints exactly which None-return path
inside propose_stop_advancement is firing per position.

Usage:
    ./run.sh python src/bh_swing_diagnose.py

This is operator infrastructure — no mutations, no journal writes. Uses
its own client_id (42) so it can run alongside the cron monitor (7) and
PaperTrader (1) without collision.

Originally written 2026-05-20 to catch the missing-advancement bug (entry
orders fell out of reqAllOpenOrders() once filled, making entry_filled
permanently False). Kept around as a standing tool because that class of
"orchestrator silently does nothing" bug is unlikely to be the last of
its kind.
"""
from __future__ import annotations

import sys

from bh_swing.analysis import position_state, stop_rules
from bluehorseshoe.core.config import get_settings
from bluehorseshoe.core.container import create_app_container
from bluehorseshoe.data.ibkr_client import IBKRClient, IBKRConfig


DIAGNOSE_CLIENT_ID = 42


def _diagnose_none_reason(pos):
    """Mirror propose_stop_advancement's None-return logic to name the path."""
    t1, t2 = pos.t1, pos.t2
    if t1 is None or t2 is None:
        return "t1 or t2 leg missing in build_managed_positions"
    if not t1.entry_filled:
        return "t1.entry_filled is False (entry order absent and no broker qty?)"
    if t2.stop_order is None or not t2.stop_is_alive:
        return "t2.stop_order missing or not alive (already triggered?)"
    if pos.side == "long" and t2.stop_order.stop_price >= pos.entry_price:
        return f"long stop {t2.stop_order.stop_price} already >= entry {pos.entry_price}"
    if pos.side == "short" and t2.stop_order.stop_price <= pos.entry_price:
        return f"short stop {t2.stop_order.stop_price} already <= entry {pos.entry_price}"
    return "unknown — propose_stop_advancement bailed for a reason this script doesn't model"


def _print_leg(name: str, leg) -> None:
    if leg is None:
        print(f"  {name}: MISSING")
        return
    entry = leg.entry_order
    stop = leg.stop_order
    print(f"  {name}: qty={leg.quantity} entry_price={leg.entry_price}")
    print(f"     entry_order={entry!r}")
    print(f"     stop_order={stop!r}")
    print(f"     entry_filled={leg.entry_filled}  stop_alive={leg.stop_is_alive}")


def main() -> int:
    settings = get_settings()
    client = IBKRClient(IBKRConfig(
        host=settings.ibkr_host,
        port=settings.ibkr_port,
        client_id=DIAGNOSE_CLIENT_ID,
        read_only=True,
    ))
    positions = client.get_positions()
    open_trades = client.get_open_trades()
    print(f"Broker: {len(positions)} positions, {len(open_trades)} open trades")

    container = create_app_container()
    db = container.get_database()
    trade_orders = db["trade_orders"]

    build = position_state.build_managed_positions(positions, open_trades, trade_orders)
    print(f"\nManaged: {len(build.managed)}, Unmanaged: {len(build.unmanaged_symbols)}")
    if build.unmanaged_symbols:
        print(f"  unmanaged symbols: {build.unmanaged_symbols}")
    if build.drift_notes:
        print(f"\nDrift notes ({len(build.drift_notes)}):")
        for note in build.drift_notes:
            print(f"  - {note}")

    print("\n--- Per-position diagnosis ---")
    advanced = 0
    skipped = 0
    for pos in build.managed:
        print(f"\n{pos.symbol}  idea={pos.idea_id}  side={pos.side}  "
              f"qty={pos.broker_position_qty}  entry={pos.entry_price}")
        _print_leg("T1", pos.t1)
        _print_leg("T2", pos.t2)

        decision = stop_rules.propose_stop_advancement(pos)
        if decision is None:
            print(f"  -> NO ADVANCEMENT — {_diagnose_none_reason(pos)}")
            skipped += 1
        else:
            print(f"  -> ADVANCE order_id={decision.order_id} "
                  f"stop {decision.current_stop} -> {decision.new_stop}")
            advanced += 1

    print(f"\nSummary: {advanced} would-advance, {skipped} no-op "
          f"(of {len(build.managed)} managed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
