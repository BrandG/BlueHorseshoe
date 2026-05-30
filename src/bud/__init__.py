"""BUD · Entry scripts — forex/FTMO autonomous + human-in-loop CLIs.

Product map: docs/PROJECTS.md. These are the cron/operator entry points that
ride on the ``bh_ftmo`` package (BUD · Lab):
  - Auto:      auto_rising3bar.py, auto_v2.py  (autonomous OANDA paper traders)
  - Briefing:  briefing.py, briefing_ftmo.py   (human-in-loop FTMO orders)
  - Operator:  flatten.py, status.py            (operator dashboards/tools)
  - Envelope:  envelope.py                      (config + state helpers)

Two known-not-yet-here:
  - src/bh_ftmo_trader.py (unified auto, newer than the rename plan) — pending
    naming decision; for now stays at src/ but imports from this package.
  - src/bh_positions.py + src/bh_lite_*.json — deferred to Tier 3 along with
    the config/state-file rename.
"""
