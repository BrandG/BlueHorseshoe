"""Lightweight research tools for early-stage signal discovery.

This module is deliberately separate from the production backtest harness
(``bh_ftmo.backtest``) and the predict CLI (``bh_ftmo.predict``). Use it for
quick "does this signal have positive R expectancy?" checks before spending
time on the full FTMO challenge simulation.

If a signal passes a `test_signal` smoke (positive avg R after spread, not a
fluke under bootstrap CI), then it's worth wiring it into a strategy class
and running the production gate.
"""
