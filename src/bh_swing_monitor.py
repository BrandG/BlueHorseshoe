"""BH Swing — intraday monitor (Phase 0: read-only).

One-shot script meant to be invoked by cron every ~5 min during US market
hours. Reconciles broker truth into the append-only journal and regenerates
src/graphs/swing_tracker.html. Takes no order actions in Phase 0.

Usage:
  python src/bh_swing_monitor.py             # live read
  python src/bh_swing_monitor.py --dry-run   # same as live in Phase 0 (no writes to broker)
  python src/bh_swing_monitor.py --once      # default; placeholder for Phase 1 loops
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from bluehorseshoe.core.config import get_settings
from bluehorseshoe.data.ibkr_client import IBKRClient, IBKRConfig

from bh_swing import journal
from bh_swing.trading import reconciler, tracker_html

logger = logging.getLogger("bh_swing.monitor")

DEFAULT_CLIENT_ID = int(os.environ.get("BH_SWING_CLIENT_ID", "7"))


def _build_client() -> IBKRClient:
    """Build IBKRClient using settings + a dedicated client_id for bh_swing."""
    s = get_settings()
    config = IBKRConfig(
        host=s.ibkr_host,
        port=s.ibkr_port,
        client_id=DEFAULT_CLIENT_ID,
        read_only=True,  # Phase 0 is always read-only
    )
    return IBKRClient(config=config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BH Swing monitor (Phase 0: read-only).")
    parser.add_argument("--dry-run", action="store_true",
                        help="No-op in Phase 0 (kept for parity with later phases).")
    parser.add_argument("--lookback-hours", type=int, default=24,
                        help="How far back to fetch executions.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s: %(message)s",
    )
    logging.Formatter.converter = __import__("time").gmtime

    run_mode = "dry-run" if args.dry_run else "live"

    journal.append(journal.JournalRow(
        run_mode=run_mode, event=journal.EVENT_RUN_START,
        note=f"bh_swing_monitor lookback={args.lookback_hours}h",
    ))

    client = _build_client()
    try:
        # Account snapshot first so we can tag fills with NAV / settled cash.
        account, positions, open_trades = reconciler.snapshot_account(client)
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

    journal.append(journal.JournalRow(
        run_mode=run_mode, event=journal.EVENT_RUN_END,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
