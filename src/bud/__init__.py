"""BUD · Entry scripts — forex/FTMO autonomous + human-in-loop CLIs.

Product map: docs/PROJECTS.md. These are the cron/operator entry points that
ride on the ``bh_ftmo`` package (BUD · Lab):
  - Auto:      auto_trader.py (live, unified rising_3bar + v2),
               auto_rising3bar.py + auto_v2.py (legacy single-strategy traders)
  - Briefing:  briefing.py, briefing_ftmo.py   (human-in-loop FTMO orders)
  - Operator:  flatten.py, status.py            (operator dashboards/tools)
  - Envelope:  envelope.py                      (config + state helpers)

One known-not-yet-here:
  - src/bh_positions.py + src/bh_lite_*.json — deferred to Tier 3 along with
    the config/state-file rename.
"""
