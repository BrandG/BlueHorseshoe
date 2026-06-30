"""Watch the bh_swing journal for live range_support ratchet events and email the operator.

The up-day ratchet (live ``--manage``) emits a ``stop_ratcheted`` row when it actually moves a
broker stop. This watcher reports the first such event (and any subsequent ones) by email, so the
Stage-0 milestone — "see the ratchet fire for real on the paper book" — doesn't need babysitting.

Stateful: each event is reported exactly once (keyed by ts+symbol+order_id, persisted to
ratchet_watcher_state.json). On its very first run it seeds state from existing events WITHOUT
emailing, so historical rows never spam. Read-only on the journal; fail-safe; cron-friendly.
"""
import csv
import json
import logging
import os
import sys

from bh_swing import journal
from bluehorseshoe.core.email_service import EmailService

JOURNAL_PATH = journal.JOURNAL_PATH
_LOGDIR = os.path.dirname(JOURNAL_PATH)
STATE_PATH = os.path.join(_LOGDIR, "ratchet_watcher_state.json")
LOG_PATH = os.path.join(_LOGDIR, "ratchet_watcher.log")
WATCH_EVENT = "stop_ratcheted"

# Explicit logger config — basicConfig() no-ops once an imported module configures root.
logger = logging.getLogger("ratchet_watcher")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    _fmt = logging.Formatter("%(asctime)sZ %(levelname)s ratchet_watcher: %(message)s")
    _fmt.converter = __import__("time").gmtime
    _fh = logging.FileHandler(LOG_PATH)
    _fh.setFormatter(_fmt)
    logger.addHandler(_fh)


def _key(row: dict) -> str:
    return f"{row.get('ts_utc')}|{row.get('symbol')}|{row.get('order_id')}"


def _load_seen() -> set:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return set(json.load(f).get("seen", []))
    except (OSError, ValueError):
        return set()


def _save_seen(seen: set) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"seen": sorted(seen)}, f)


def _ratchet_rows() -> list:
    if not os.path.exists(JOURNAL_PATH):
        return []
    with open(JOURNAL_PATH, encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("event") == WATCH_EVENT]


def _email(new_rows: list, first_ever: bool) -> None:
    svc = EmailService()
    if not svc.is_configured():
        logger.warning("email not configured; %d ratchet event(s) unsent", len(new_rows))
        return
    lead = "FIRST live ratchet has fired" if first_ever else f"{len(new_rows)} new ratchet event(s)"
    lines = [f"{lead} on the paper book.\n"]
    for r in new_rows:
        lines.append(
            f"  {r.get('symbol')}: stop ${r.get('stop_price')} -> ${r.get('price')}  "
            f"at {r.get('ts_utc')}\n    {r.get('note', '')}"
        )
    lines.append("\nThe up-day ratchet is now demonstrably working live (paper). "
                 "This is the Stage-0 gate before the live-account migration.")
    subject = ("[BH Ratchet] FIRST live ratchet fired" if first_ever
               else f"[BH Ratchet] {len(new_rows)} new ratchet event(s)")
    svc.send(subject=subject, text_body="\n".join(lines))


def main() -> int:
    try:
        rows = _ratchet_rows()
        state_exists = os.path.exists(STATE_PATH)
        seen = _load_seen()
        fresh = [r for r in rows if _key(r) not in seen]
        if not state_exists:
            # First run ever: seed silently (even with zero events) and ALWAYS write
            # the state file, so the next ratchet is correctly detected as new.
            for r in fresh:
                seen.add(_key(r))
            _save_seen(seen)
            logger.info("bootstrapped state with %d existing ratchet event(s) (no email)", len(fresh))
            return 0
        if not fresh:
            return 0
        for r in fresh:
            seen.add(_key(r))
        first_ever = (len(seen) == len(fresh))   # nothing was ever seen before this batch
        _email(fresh, first_ever)
        _save_seen(seen)
        logger.info("reported %d new ratchet event(s)%s", len(fresh),
                    " (FIRST)" if first_ever else "")
        return 0
    except Exception as e:  # noqa: BLE001 — fail-safe: never crash the cron
        logger.error("ratchet watcher failed: %s", e)
        return 0


if __name__ == "__main__":
    sys.exit(main())
