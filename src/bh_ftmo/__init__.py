"""BUD · Lab — forex/FTMO research + backtest engine (H4 trading system).

Product map: docs/PROJECTS.md. This is BUD's research/backtest core; the live
channels that ride on it are the autonomous traders (BUD · Auto:
bh_ftmo_paper / bh_ftmo_v2_paper) and the human-in-loop briefing (BUD · Briefing: bh_briefing;
bh_briefing_ftmo was deleted 2026-08-17).

Isolated from the equities pipeline: OANDA data ingestion (``data/``),
forex-native indicators (``indicators/``), multi-pair scoring and strategies
(``analysis/``), and execution (``trading/``). See
docs/planning/BH_FTMO_PLAN.md for the multi-phase plan.

The Phase-0 seed (``bh_ftmo/main.py``, a copy of the now-retired ``bh_lite.py``)
was removed once the isolated H4 engine and the bh_briefing tools superseded it.
"""
