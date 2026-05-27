# BH Lite Sundown — refactor spec (DRAFT)

**Status:** Phase 1 COMMITTED (`d6be70f`). Phases 2–3 EXECUTED 2026-05-27 (staged, not yet committed) — concurrent bh_lite.py session was shut down, unblocking the deletes. Decisions: hard delete (not shim); retire `bh_ftmo/main.py` too. Track A reverted.
**Owner:** Brand
**Rationale:** bh_lite's scoring is superseded by `bh_briefing.py` / `bh_briefing_ftmo.py` (H4, cell-based, directional, in production). bh_lite is unscheduled and log-dormant since 2026-05-12, and daily-bar forex scoring with the equity model was never valid (see `project_bh_lite_vs_briefing`, `BH_LITE_FOREX_SCORER_MIGRATION.md`). Retire the scoring tool; preserve the bits that are still load-bearing.

---

## What is actually load-bearing in bh_lite today

1. **`bh_lite_config.json`** — account/risk/instruments/clusters. Read by `bh_briefing_ftmo.py` as the FTMO trade envelope. **KEEP.**
2. **`bh_lite_positions.json`** — open-position state. Read by `bh_briefing_ftmo.py` to skip/size around live positions. **KEEP.**
3. **5 Python symbols imported by `bh_briefing_ftmo.py`** (the only real code dependency):
   `DEFAULT_CONFIG_PATH`, `DEFAULT_POSITIONS_PATH`, `load_config`, `load_positions`, `_symbol_to_clusters_map` — all small, pure helpers.

Everything else in `bh_lite.py` is dead scoring/CLI: `LiteTrader`, `score_instrument`, `asset_class_for_instrument`, `_build_signal`, `fetch_ohlcv`/`fetch_intraday_ohlcv`, `enrich_dataframe`, `rank_signals`, `_candidate_for_strategy`, `check_position_health`, `_calculate_position_pnl`, `calculate_*_setup`, `calculate_position_size`, `calculate_t1_t2`, `compute_occupied_clusters`, `apply_cluster_filter`, `format_output`, `_write_csv`, `_write_orders`, `main`.

**Note — the comment in `bh_ftmo/__init__.py`** ("frozen as the parallel-comparison system") is just a comment, not an import. Update it during cleanup.

---

## Target end state

- A small shared module holds the 5 helpers (proposed: `src/ftmo_envelope.py` — "the FTMO trade-envelope config/position loaders"). Name is an open decision.
- `bh_briefing_ftmo.py` imports from that module instead of `bh_lite`.
- `bh_lite.py` is removed (or reduced to a deprecation shim — open decision).
- `bh_lite_config.json` + `bh_lite_positions.json` keep their names (renaming has blast radius across briefing code; defer).
- The Track A `asset_class` patch on the equities `TechnicalAnalyzer` is reverted (bh_lite was its only forex consumer). The A3 `context` block in `bh_lite_config.json` can stay or go with bh_lite.

---

## Steps

**Phase 1 — Decouple (non-destructive, collision-free; bh_lite.py untouched) ✅ DONE 2026-05-27**
1. ✅ Created `src/ftmo_envelope.py` with `DEFAULT_CONFIG_PATH`, `DEFAULT_POSITIONS_PATH`, `load_config`, `load_positions`, `symbol_to_clusters_map` (cluster-map promoted from the private `_symbol_to_clusters_map`).
2. ✅ Repointed `bh_briefing_ftmo.py`'s import to `from ftmo_envelope import (...)` and updated its one call site; fixed the now-stale "import bh_lite" comment.
3. ✅ Added `src/tests/test_ftmo_envelope.py` (6 tests, green).
4. ✅ `bh_briefing_ftmo.py --dry-run` runs; no `import bh_lite` remains; lint 9.26. **bh_briefing_ftmo no longer depends on bh_lite.py.** (bh_lite.py never touched → no collision with the concurrent agent.)

**Phase 2 — Retire bh_lite scoring (destructive) ✅ EXECUTED 2026-05-27 (staged)**
5. ✅ Concurrent bh_lite.py session shut down by Brand; its uncommitted work (drop_forming_bar / health-check) intentionally discarded (drop_forming_bar's purpose is already covered in bh_briefing via `include_incomplete=False`).
6. ✅ Hard-deleted `bh_lite.py`, `run_bh_lite.sh`. (`bh_lite_orders.json` was untracked/gitignored — left on disk, harmless.)
7. ✅ Deleted `src/tests/test_bh_lite.py` (surviving helpers covered by `test_ftmo_envelope.py`).
8. ✅ Reverted the Track A `asset_class` changes in `technical_analyzer.py` + the forex tests in `test_technical_scenarios.py` + the A3 `context` block in `bh_lite_config.json` (no remaining consumer; confirmed nothing passes `asset_class="forex"`).
9. ✅ Rewrote `bh_ftmo/__init__.py` docstring (no longer describes the deleted Phase-0 seed; describes the H4 system).

**Phase 3 — Retire sibling ✅ EXECUTED 2026-05-27 (staged)**
10. ✅ Hard-deleted `bh_ftmo/main.py` (frozen Phase-0 copy, dead equity-scorer path, not cronned) + its only consumer `src/tests/test_bh_ftmo.py`. Confirmed no other importer.

**Verification:** `bh_briefing_ftmo --dry-run` runs; no dangling imports of `bh_lite`/`bh_ftmo.main`; full suite shows only the 8 pre-existing failures (test_strategy/test_signal_generator stale-threshold drift + 1 research-dir error), none new.

---

## Risks / coordination
- **Concurrent edits:** `bh_lite.py` and `test_bh_lite.py` are being edited by another agent right now. Phase 1 avoids both files entirely (only adds a new module + edits the clean `bh_briefing_ftmo.py`), so it's safe to do immediately. Phase 2 must wait for that work to land.
- **Config filenames:** keep `bh_lite_config.json` / `bh_lite_positions.json` for now; renaming touches multiple call sites and the operator's muscle memory. Optional later cleanup.
- **Don't break the live briefing:** `bh_briefing_ftmo.py` is cronned (H4 + daily 22:30). Verify with `--dry-run` after each phase.

## Open decisions (for Brand)
1. Shared module name — `ftmo_envelope.py`? something else?
2. bh_lite.py: hard-delete vs deprecation shim?
3. Rename the config/positions JSONs, or keep the `bh_lite_*` names?
4. Deprecate `bh_ftmo/main.py` in the same pass, or leave for later?
5. Revert the Track A equity-scorer patch now, or keep it as a harmless defaulted no-op?
