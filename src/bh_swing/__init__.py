"""GORDON · Manager — post-fill management of GORDON · Engine's IBKR positions.

Product map: docs/PROJECTS.md. Not its own trading universe — it babysits the
bracket orders the ``bluehorseshoe`` engine (GORDON · Engine) opens on IBKR.

Mirrors the bh_ftmo/ pattern: cron-driven, stateless-per-run, broker-truth-first.
Phase 0 (current): read-only — reconciliation + HTML tracker + operator CLI.
No order actions are taken from this package in Phase 0.
"""
