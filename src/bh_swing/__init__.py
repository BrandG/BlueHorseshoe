"""BH Swing — autonomous IBKR equities trader.

Mirrors the bh_ftmo/ pattern: cron-driven, stateless-per-run, broker-truth-first.
Phase 0 (current): read-only — reconciliation + HTML tracker + operator CLI.
No order actions are taken from this package in Phase 0.
"""
