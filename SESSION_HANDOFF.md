# Session Handoff

**Date:** June 9, 2026
**Status:** **FIRST LIVE-BOOK CHANGE OF THE ARC.** Took the fundamentals/quality axis from prototype → full
validation → implementation → **DEPLOYED LIVE**. The bare `deep_oversold` sleeve is now **nonbull-gated + filtered
to skip financially-weak (Altman-Z″<1.1) companies.** Merged to master, both flags ON in `.env`, health data
loaded for 97% of liquid names, validated end-to-end on the live system. Memory: `project_fundamentals_quality_condition`.

## What this session did (in order)
1. **Full fundamentals pull** → `data/fundamentals.parquet` (research universe, 1,119 syms). De-risked the AV
   3-statement feed; PIT alignment to earnings `reportedDate` confirmed.
2. **Conditioning result:** balance-sheet **solvency (Altman-Z″, book-only)** cleanly splits the DeepOS bounce
   (safe +0.142R t4.6 vs distress +0.018 ~dead). Income INVERTS (junk bounces harder); Piotroski-F weak.
3. **All 3 deployment doors PASSED** (a first for the arc): **#1** year-block bootstrap — drop-distress lifts
   the BARE sleeve +0.062R nonbull, year-robust, CI excludes 0; HA sleeve subsumes it. **#3** orthogonal to
   price/vol/depth (nested residual Z″|cheapness +0.033 P=1.00; reverse ~0). **#2** the Z″ gradient is smooth/
   monotonic → belongs in a sizer, not a cliff.
4. **Full-book portfolio sim** (faithful to the live allocator) → then **full-universe re-validation** TEMPERED
   it: the solvency edge is real + significant ONLY on a **nonbull-gated** bare book (HARD +0.049–0.053R,
   P=0.97–1.00); it WASHES OUT on the current all-regime book (P~0.5). Net package-vs-production is a positive
   point estimate but NOT statistically certified over one decade (B−A P=0.59). **Honest read: modest, real,
   capacity-efficient — not a blockbuster.**
5. **Wiring spec** → `docs/planning/SOLVENCY_SLEEVE_WIRING.md` (UNTRACKED). Codex implemented on branch
   `feat/solvency-deepos`. **I reviewed + caught/fixed 2 real bugs** (R anchored to limit not fill in the sim;
   `load_solvency_asof` crashed `-p --no-paper` on the unseeded/read-only prod DB — added info_schema guard).
   Full test suite: 1682 passed, 0 regressions (21 failures all pre-existing bh_ftmo/ml_overlay, reproduce on master).
6. **DEPLOYED:** extended health-data coverage to the full liquid universe (`fundamentals_pull_liquid.py`,
   ~6k AV calls → 1,902/1,946 liquid names), seeded the prod DuckDB `fundamentals` table (141,216 rows),
   merged the branch (FF), flipped both flags ON. **Validated:** live `-p --no-paper` ran clean; SPY is BULL so
   the gate correctly sat out all 24 of today's oversold liquid names (0 candidates = correct). Spot-check: the
   filter would drop 6 weak-balance-sheet names (AT&T, HCA, WU…) and keep 17 healthy.

## LIVE NOW (the change)
- `.env`: `DEEP_OVERSOLD_NONBULL_GATE=true`, `DEEP_OVERSOLD_SOLVENCY_FILTER=true`.
- master HEAD `9586035` (Codex wiring `1eaddee` + my fix `9586035`). Branch merged, **not pushed to origin yet.**
- Behavior change: bare DeepOS now trades **only in nonbull regimes** AND skips Z″<1.1 names. Expect FEW/zero
  beaten-down trades until the market weakens. **Back-out = delete the two `.env` lines (instant)** or
  `git reset --hard 9e98207`.
- ⚠️ "Financially weak" = high leverage / thin book equity (catches big names like AT&T), NOT just near-bankrupt.

## In progress / leftovers (non-blocking)
- **Quarterly auto-refresh has a DB-lock bug — MUST FIX before scheduling the cron.** `src/bluehorseshoe/data/
  fundamentals_pull.py` opens the prod DuckDB read-write and HOLDS it for the whole multi-hour pull → would
  freeze live trading. Fix: open the store only briefly (read worklist; write at end). `cron_quarterly_fundamentals.sh`
  exists but is NOT scheduled — safe until it is.
- **Planning doc uncommitted:** `docs/planning/SOLVENCY_SLEEVE_WIRING.md` (untracked). Commit or discard.
- **Branch not pushed to origin.** Push master when ready.

## Next steps
1. **Watch the first live nights** — given the bull regime, likely few/no DeepOS trades; that's expected.
2. **Fix the cron lock bug** (above), then schedule the quarterly fundamentals refresh so coverage stays fresh.
3. **The bigger levers the sim surfaced (likely > this filter):** (a) HA `edge_weight`/allocation — the allocator
   pours 2.85× capital into a thin, low-frequency sleeve; (b) 10-slot capacity during crash clusters (slots fill
   with early-fallers, miss the bounce). Both plausibly worth more than the solvency filter.
4. **Carried orthogonal frontier:** sentiment (shallow history) / implied-vol (no feed); market-neutral
   long-short prototype (long dislocation / short trend-extension, dollar-neutral, nonbull-gated — needs a real
   PAIRED backtest).
5. (Carry) efficiency lever: retire Baseline/MR + indicator suite from `-p` (computed only to feed tracking-only).

## Key decisions this session
- **Deployed the PACKAGE {nonbull-gate bare + HARD Z″<1.1 filter}** — solvency washes without the gate, so the
  gate is a prerequisite, not optional.
- **HARD filter over graded TILT** — simpler, ≥ tilt on the full universe, and needs no Z″ winsorization (book-Z″
  blowups = solvent = kept anyway).
- **Bare sleeve ONLY** — HA already subsumes solvency (`DeepOversoldHAStrategy._solvency_ok` no-ops).
- **Shipped despite modest/uncertain net-of-production payoff** — the within-sleeve edge is certain (P=1.00) and
  the package is capacity-efficient (3× the $ on ~25% of the trades in sim); reversible via one `.env` flip.
- **Flags default False in code; enabled only via `.env`** — zero behavior change until explicitly turned on.

## Blockers / open questions
- **Cron lock bug** (above) gates the auto-refresh.
- **Coverage is a snapshot** — 1,902 liquid names seeded as of 2026-06-08 data; without the (lock-fixed) cron it
  goes stale. Names with no health data are KEPT (unfiltered), so staleness fails safe.
- **Statistical uncertainty** — net-of-production effect not certified over one decade; deployed as a reversible,
  well-motivated change, watch live.
- **Fractional deploy gate (carry, BLOCKED):** IBKR 10243 — account can't place fractional via API. Enable
  fractional on the IBKR account → `src/verify_fractional_bracket.py` PASS → `paper_fractional_shares=True`.
- **Survivorship** caps the distress tail (delisted names absent from AV) → filter conservative, leans on the
  quality-recovery side.

## Live strategy roster (CHANGED this session)
| name | display | live orders? | notes |
|---|---|---|---|
| deep_oversold | DeepOS | **yes** | edge_weight 0.142 — **NOW nonbull-gated + Z″<1.1 solvency-filtered** |
| deep_oversold_ha | DeepOS+HA | **yes** | edge_weight 0.404; nonbull+HA-green (solvency NOT applied — subsumed) |
| baseline, mean_reversion | Baseline, MeanRev | **NO — tracking-only** | forward-R only |
| adx_didown | ADX-Down | **NO — tracking-only** | promote only if OOS record justifies |
Allocation: global top-N by `score*edge_weight`; sizing ∝ edge_weight (cap 2.5×); **whole-share floor**.

## Standing corrections (DO NOT repeat) — see memory
- `feedback_trend_family_not_dead`: don't call the trend family "dead/closed." Long-only 10d tests mean-revert;
  a negative long = a SHORT-selector candidate. Report measurements, not verdicts; let Brand steer.
- `feedback_no_premature_indicator_verdicts`: explain an indicator + audit the harness before any verdict.
- **Plain language with Brand** — he got lost in jargon (solvency/PIT/Z″) this session; explain in concrete
  terms, and DO the validation step rather than repeatedly asking permission.
- `PYTHONPATH=src` (or `./run.sh`) for any direct python — bare `python` fails import (`bh_ftmo`, `bluehorseshoe`).
- `pgrep -f main.py` / awk checks **false-positive on their own command line** — verify with `ps -eo pid,etime,cmd`.

## Carry-forward ops state (still live)
- **Equity cron** `run_daily_pipeline.sh` Tue–Sat 01:00 UTC (`-u→-p→journal→--evaluate→report→email`).
  **Weekly retrain** `cron_weekly_retrain.sh` Sun 02:00 UTC.
- **PAPER_TRADING_ENABLED=true** — `-p` submits orders unless `--no-paper`.
- **Score-backfill PAUSED** — sentinel `.score_backfill_pause`; do NOT remove.
- **Workflow:** solo, no PRs — branch/commit/push to `master`; git ops via `/tmp/humanaction.sh` for Brand.
  ~8GB box; serialize backtests; NEVER run heavy jobs concurrent with `-p`/`-u` (DuckDB lock + OOM). Research
  backtests are read-only/safe; pin the 2000-sym sample via `ORDER BY symbol` + SEED=7. Long AV pulls write to
  parquet/cache then seed the prod DB with a BRIEF write — never hold the prod lock during the network pull.

## Relevant files
- **Code (merged to master):** `analysis/strategy_interface.py` (bare nonbull gate + `_solvency_ok`; HA no-op),
  `analysis/strategy.py` (solvency threaded via `StrategyContext`/`shared_ctx`/`_worker_state`),
  `core/config.py` (2 flags), `analysis/constants.py` (`DEEP_OVERSOLD_Z_DISTRESS=1.1`),
  `data/duckdb_store.py` (`fundamentals` table, `load_solvency_asof` PIT loader + fail-safe guard, seeder),
  `data/fundamentals_pull.py` (production puller — **has the lock bug**), `cron_quarterly_fundamentals.sh`.
- **Data (gitignored):** `data/fundamentals.parquet` (141k rows, 2,597 syms), prod `fundamentals` table seeded.
  Caches: `research/indicator_screen/{earnings_cache_full,fund_cache_full}.json`.
- **Research scripts (UNTRACKED, the regression oracles):** `research/indicator_screen/fundamentals_*.py`
  (`condition`, `bare_sleeve_confirm`, `orthogonality_gauntlet`, `sizing_tilt`, `fullbook_sim`,
  `fullbook_sim_alluniv`, `package_revalidate`, `pull_full`, `pull_liquid`).
- **Spec (untracked):** `docs/planning/SOLVENCY_SLEEVE_WIRING.md`.

## The synthesis (updated)
Mean-reversion is the edge — one dislocation factor, harvested long by DeepOS/DeepOS+HA, nonbull-gated. Selection
WITHIN the oversold setup (ML, volume, gaps, earnings) adds nothing HA-green doesn't already capture — EXCEPT
**company solvency, the first genuinely-orthogonal axis to ship** (modest, on the bare sleeve only, behind the
regime gate). Remaining frontier: sentiment/IV, the market-neutral short leg, and the **allocation/capacity**
levers (HA edge_weight, 10-slot crash capacity) the full-book sim surfaced as bigger than any single filter.

---
## Prior sessions (condensed)
**June 8:** Reporter shipped to mirror live book (`9acc1a9`). Research arc — Donchian, SuperTrend, volume/gap,
knife re-audit, earnings — all closed (null/redundant/not-deployable). Built `data/earnings.parquet`; prototyped
fundamentals (the thread this session deployed). Lesson: HA-green is a near-complete "bad-context" filter.
**June 7:** Live book productionized — Baseline/MR → tracking-only (`887ef10`), edge-weighted alloc + conviction
sizing (`5383573`), fractional coded then BLOCKED by IBKR 10243 (`85cc4dd`/`816f6b5`), deep-OS ML selection NULL
(`ba37e77`). HA deep dive → DeepOS+HA sleeve; PSAR/ADX → adx_diDown tracking-only. See named memories.
