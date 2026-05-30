"""BUD · forex/FTMO entry scripts + shared trade envelope.

Product map: docs/PROJECTS.md. The cron/operator entry points + the live
trading envelope, all riding on the ``bh_ftmo`` package (BUD · Lab):
  - Auto:      auto_trader.py (live, unified rising_3bar + v2),
               auto_rising3bar.py + auto_v2.py (legacy single-strategy traders)
  - Briefing:  briefing.py, briefing_ftmo.py    (human-in-loop FTMO orders)
  - Operator:  flatten.py, status.py             (operator dashboards/tools)
  - Envelope:  envelope.py (loaders) + config.json (account/risk/instruments/
               clusters) + positions.json (live FTMO position state) +
               orders.json (last MT5 paste) + positions_closed.json
  - Position CLI: positions.py  (list/add/close commands; manages positions.json)

Tier 1 (entry scripts) + Tier 3 (config/state files) both shipped 2026-05-30.
See docs/planning/GORDON_BUD_RENAME_PLAN.md.
"""
