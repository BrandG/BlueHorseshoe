"""BH Swing — intraday monitor.

One-shot script meant to be invoked by cron every ~5 min during US market
hours. Reconciles broker truth into the append-only journal and regenerates
src/graphs/swing_tracker.html.

Two modes, gated by flags:
  default                — Phase 0 behavior: read-only reconcile + render
  --manage-dry-run       — Phase 1a: propose management actions, journal
                           would_* events, no broker mutations
  --manage               — Phase 1b: live management. Advances stops on
                           T1 fills via stop_rules + safety gates.

Read-only mode stays the cron default until 1b is approved.

Usage:
  python src/bh_swing_monitor.py                  # Phase 0 read-only
  python src/bh_swing_monitor.py --manage-dry-run # Phase 1a shadow management
  python src/bh_swing_monitor.py --manage         # Phase 1b live management
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from bluehorseshoe.core.config import get_settings
from bluehorseshoe.core.container import create_app_container
from bluehorseshoe.data.ibkr_client import IBKRClient, IBKRConfig

from bh_swing import journal
from bh_swing.trading import manager, reconciler, tracker_html

logger = logging.getLogger("bh_swing.monitor")

DEFAULT_CLIENT_ID = int(os.environ.get("BH_SWING_CLIENT_ID", "7"))


def _build_client(read_only: bool) -> IBKRClient:
    """Build IBKRClient using settings + a dedicated client_id for bh_swing."""
    s = get_settings()
    config = IBKRConfig(
        host=s.ibkr_host,
        port=s.ibkr_port,
        client_id=DEFAULT_CLIENT_ID,
        read_only=read_only,
    )
    return IBKRClient(config=config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BH Swing monitor.")
    parser.add_argument("--manage", action="store_true",
                        help="Live management: advance stops, etc. via IBKR mutations.")
    parser.add_argument("--manage-dry-run", action="store_true",
                        help="Shadow management: journal would_* events without mutating.")
    parser.add_argument("--lookback-hours", type=int, default=24,
                        help="How far back to fetch executions for reconcile.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    if args.manage and args.manage_dry_run:
        parser.error("--manage and --manage-dry-run are mutually exclusive")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s: %(message)s",
    )
    logging.Formatter.converter = __import__("time").gmtime

    # run_mode tag in the journal reflects whether mutations are possible.
    # "live" only when --manage is set; everything else (default, dry-run) is "dry-run".
    run_mode = "live" if args.manage else "dry-run"
    manage_mode = "off"
    if args.manage:
        manage_mode = "live"
    elif args.manage_dry_run:
        manage_mode = "dry-run"

    journal.append(journal.JournalRow(
        run_mode=run_mode, event=journal.EVENT_RUN_START,
        note=f"bh_swing_monitor lookback={args.lookback_hours}h manage={manage_mode}",
    ))

    # Read-only client unless we're actually placing mutations.
    client = _build_client(read_only=(not args.manage))
    container = None
    try:
        # Account snapshot first so we can tag fills with NAV / settled cash.
        account, positions, open_trades = reconciler.snapshot_account(client)

        if not reconciler.is_broker_reachable(account):
            # Broker unreachable. Skip reconcile + tracker render so the
            # last-known-good HTML stays on disk (its stale mtime is the
            # operator's cue). Exit non-zero so cron flags the run.
            logger.error(
                "Broker unreachable — empty account summary. "
                "Skipping reconcile and HTML render."
            )
            journal.append(journal.JournalRow(
                run_mode=run_mode, event=journal.EVENT_RUN_ERROR,
                note="broker unreachable (empty account_id)",
            ))
            return 2

        nav = float(account.get("net_liquidation", 0.0) or 0.0)
        settled = float(account.get("settled_cash", 0.0) or 0.0)
        logger.info(
            "Account snapshot: NAV=%.2f settled=%.2f positions=%d open_orders=%d",
            nav, settled, len(positions), len(open_trades),
        )

        summary = reconciler.reconcile(
            client,
            run_mode=run_mode,
            lookback_hours=args.lookback_hours,
            nav=nav,
            settled_cash=settled,
        )
        logger.info("Reconciler: %s", summary)

        if manage_mode != "off":
            try:
                container = create_app_container()
                db = container.get_database()
                trade_orders = db["trade_orders"]
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Could not connect to Mongo for management metadata: %s. "
                    "Falling back to unmanaged-only.", e,
                )
                trade_orders = None

            ms = manager.manage_tick(
                client=client,
                broker_positions=positions,
                broker_open_trades=open_trades,
                trade_orders_collection=trade_orders,
                config=manager.ManageConfig(dry_run=(manage_mode == "dry-run")),
            )
            logger.info(
                "Manage: positions=%d unmanaged=%d proposed=%d taken=%d "
                "skipped=%d failed=%d halted=%s",
                ms.managed_positions, len(ms.unmanaged_symbols),
                ms.proposed, ms.taken, ms.skipped, ms.failed, ms.halted_reason,
            )

        recent = journal.read_recent(limit=50)
        path = tracker_html.render(
            account=account,
            positions=positions,
            open_trades=open_trades,
            recent_events=recent,
        )
        logger.info("Tracker written: %s", path)

    except Exception as e:  # noqa: BLE001 — cron-safe top-level guard
        logger.exception("Monitor run failed: %s", e)
        journal.append(journal.JournalRow(
            run_mode=run_mode, event=journal.EVENT_RUN_ERROR,
            note=f"{type(e).__name__}: {e}",
        ))
        return 2
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
        if container is not None:
            try:
                container.close()
            except Exception:  # noqa: BLE001
                pass

    journal.append(journal.JournalRow(
        run_mode=run_mode, event=journal.EVENT_RUN_END,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
