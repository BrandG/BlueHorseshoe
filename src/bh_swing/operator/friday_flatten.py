"""Scheduled Friday-close flatten — closes every open swing position before
the US weekend, journals each as a ``friday_flatten`` event.

Triggered on a cron at ~19:55 UTC Fri (≈15:55 ET, 5 min before US close).
Re-entries come from Monday's normal ``-p`` pipeline if the signal still ranks.

Built on the policy result in ``WEEKEND_FLATTEN_EQUITIES_v1_RESULTS.md``
(2026-05-21): uniform Friday-flatten cut equity max drawdown by 41% on an
11,163-trade ledger while improving time-adjusted return. The asymmetric
"flatten winners only" variant was rejected on bootstrap instability.

Guards:
  - **Day-of-week gate.** Refuses to run unless NY-local time is Friday.
    Overridable with ``--force`` for one-off operator use.
  - **Kill switch.** Touch ``.bh_swing_pause_friday_flatten`` at repo root
    to disable without touching cron. Separate from
    ``.bh_swing_pause_management`` so the two policies can be toggled
    independently.
  - **Distinct client_id.** Uses ``BH_SWING_FRIDAY_CLIENT_ID`` (default 8)
    so it can run alongside ``bh_swing_monitor`` (client_id 7) without
    IBKR connection collision.

Defaults to ``--execute`` (since cron expects mutation by design). Use
``--dry-run`` for inspection without sending orders.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover — Python 3.9+ ships zoneinfo
    ZoneInfo = None  # type: ignore

from bluehorseshoe.core.config import REPO_ROOT, get_settings
from bluehorseshoe.data.ibkr_client import IBKRClient, IBKRConfig

from bh_swing.operator import flatten

logger = logging.getLogger("bh_swing.friday_flatten")

KILL_SWITCH_PATH = os.path.join(REPO_ROOT, ".bh_swing_pause_friday_flatten")
DEFAULT_CLIENT_ID = int(os.environ.get("BH_SWING_FRIDAY_CLIENT_ID", "8"))

# Use distinct event names so the journal is filterable. Schema unchanged.
FRIDAY_EVENT_NAMES = {
    "would_close":   "friday_flatten_proposed",
    "flattened":     "friday_flatten",
    "failed":        "friday_flatten_failed",
}

# How many positions to close per Friday. PaperTrader's cap is 10; we use a
# large number to ensure we never partially flatten (the policy is "no
# position over the weekend, period").
MAX_CLOSES = 999


def is_friday_in_ny(now: Optional[datetime] = None) -> bool:
    """True iff America/New_York thinks it's currently Friday.

    ``now`` is injected for tests; otherwise uses the live wall clock.
    """
    if ZoneInfo is None:
        # Fallback for the unlikely no-zoneinfo case: use UTC weekday.
        # Friday in UTC after 13:30 should always correspond to Friday in NY.
        logger.warning("zoneinfo unavailable; falling back to UTC weekday check")
        now = now or datetime.utcnow()
    elif now is None:
        now = datetime.now(ZoneInfo("America/New_York"))
    return now.weekday() == 4  # Mon=0..Fri=4


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Plan only; do not submit any orders. Default is to execute.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Run even if today is not Friday in NY. For one-off operator use.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s: %(message)s",
    )

    # ---- Kill switch ------------------------------------------------------
    if os.path.exists(KILL_SWITCH_PATH):
        print(f"[friday_flatten] kill switch present at {KILL_SWITCH_PATH} — exiting.")
        return 0

    # ---- Day-of-week gate -------------------------------------------------
    if not is_friday_in_ny() and not args.force:
        print(f"[friday_flatten] today is not Friday in NY — exiting (use --force to override).")
        return 0

    settings = get_settings()
    client = IBKRClient(config=IBKRConfig(
        host=settings.ibkr_host,
        port=settings.ibkr_port,
        client_id=DEFAULT_CLIENT_ID,
        read_only=False,
    ))
    try:
        closed = flatten.run(
            client,
            execute=not args.dry_run,
            max_closes=MAX_CLOSES,
            sort_by="biggest",  # close largest positions first to limit blast radius if interrupted
            event_names=FRIDAY_EVENT_NAMES,
        )
        print(f"[friday_flatten] closed {closed} positions.")
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
