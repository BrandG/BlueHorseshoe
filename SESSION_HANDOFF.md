# Session Handoff

> **Research reset 2026-06-25.** The prior handoff (GORDON/BUD research findings — S/R,
> indicator teardown, contrarian, BUD H4 edges, etc.) was cleared along with the `research/`
> tree and its memory, so research can be regenerated cleanly under the current testing
> standards. Operational state below; research findings start fresh.

## Live / operational state

**GORDON (US equities / IBKR)**
- Engine (`bluehorseshoe/` + `main.py`): daily `-u` update + `-p` prediction pipeline on cron.
- Manager (`bh_swing/`): post-fill stop management, LIVE (`--manage`, BREAKEVEN moves) on paper acct.
- Data pulls that regenerate `data/*.parquet` now live in `src/bluehorseshoe/maintenance/data_pulls/`.

**BUD (forex / FTMO / OANDA)**
- Briefing (`src/bud/briefing.py` + `briefing_ftmo.py`): human-in-loop, emailed FTMO briefing on cron.
- Auto (`src/bud/auto_trader.py`): autonomous unified trader (V2 cells) on OANDA practice.
  Live cron = `run_bh_ftmo_trader.sh`, minute 16 every 4h session. **22 deployable cells** as of 2026-06-26.

## Session 2026-06-26 — BUD research arc (all MERGED + PUSHED to master)

Shared harness built this session: **`research/_lib/fx_replay.py`** — fire detection (vectorized for
all families, fidelity-checked vs live `evaluate_cell`, 0 logic mismatches) + bar loading. Standard:
bracketed R (worst −1R), spread cost from bid/ask, A/B interleaved-quarter + 24mo holdout splits,
expectancy-CI (`mean_R − 1.96·max(nw_se, clustered_se) > 0`), **matched-random-same-geometry drift
control**, throughput floor. Studies under `research/<name>/run.py` (run `--smoke` first; full ~1–7min).

| # | change | commit |
|---|---|---|
| 1 | Per-cell quarantine: restored 11 mid cells; `QUARANTINED_STRATEGIES` → per-cell `QUARANTINED_CELLS` (13 held) in `auto_trader.py`+`auto_v2.py`. Study: `cell_revalidation_v1` | `d4f4186` |
| 2 | bb/macd stop 1.0%→0.75%: `TIGHT_STOP_STRATEGIES={bb,macd}` in `compute_entry_stop_target` (briefing.py). Study: `exit_geometry_v2` | `b83e211` |
| — | `lint.sh` section-aware + `--changed` fast path (+ CLAUDE.md) | `d7fe777` |
| 4 | 2 new autonomous shorts `ichimoku:GBP_CAD` + `ichimoku:CAD_CHF` (default 9/26, GBP_CAD hedges existing ema:GBP_CAD long). Studies: `short_discovery_v1/_trend_v1`, `short_tuning_v1` | `b3b2056` |
| 3 | Direction-imbalance gate: **investigated, NO-OP.** Dormant for v2 (max net-long 2 vs cap 12); the 64 historical skips were retired `rising_3bar` (broad net-long, May 28–31). No change. |

**Methodology lessons (hard-won, apply to all future research):**
- **In-sample param tuning OVERFITS** → use textbook/default params (short_tuning_v1 degraded 2/5 vs defaults).
- **The matched-random-same-geometry drift control is essential** — it caught atr:short "wins" that were just riding pair downtrends (NZD_CHF −16%).
- **Cross-family pair agreement** is the real discovery filter (GBP_CAD: ichimoku+macd both agree).
- "Makes money after costs" is the bar; **worse-than-random is the only random concern.**
- Memory: `project_cell_revalidation_per_cell_quarantine`, `project_exit_geometry_v2`, `project_short_discovery`.

## Next session — queued work

**(A) Lint cleanup (general).** Two parts:
  1. *Finish the lint papercut.* `lint.sh --changed` fixed the tree-wide HANG, but `pylint` still exits
     non-zero whenever the changed file has ANY pre-existing findings — so Codex/validation keeps reporting
     "lint failed / Partially Passed" even on clean additions. Fix: make `--changed` **diff-aware** (fail
     only on findings on the changed lines), or report-only / baseline-score compare. File: `lint.sh` (root).
  2. *Clean the actual findings.* `src/bud/briefing.py` is 9.39/10 with pre-existing: missing docstrings
     (C0115/C0116), broad-except (W0718 ~line 831), redundant `pct == pct` (R0124 ~lines 636/757), unused
     `import json` (line 20), too-many-locals/statements/args. Clean `src/bud/` first (`./run.sh ./lint.sh bud`),
     then broaden. NOT trading logic — pure hygiene.

**(B) Deferred: `atr:long` wider-target (validated, not yet deployed).** From `exit_geometry_v2`, the
  `atr:long:limit` grid winner was **2% TP / 0.5% SL / 14d**: holdout meanR 0.053→0.078, **edge-over-random
  +0.098**, throughput improved (R/day 0.013→0.026), positive A∧B∧holdout. Deferred in #2 because it's a
  TARGET change (a different knob than the bb/macd stop). Next: re-run `research/exit_geometry_v2/run.py`,
  confirm the `atr:long:limit` row still wins, then deploy as a per-strategy override in
  `compute_entry_stop_target` (atr-long → TP 2% / SL 0.5%), mirroring `TIGHT_STOP_STRATEGIES`. Sizing is
  stop-distance based (`auto_trader.compute_units` uses abs(entry−stop)) so the tighter stop keeps $-risk
  constant. Note: atr:SHORT was a drift-rider (KEEP at baseline) — scope to atr long only.

**(C) Deferred: reconcile-label anomaly (data hygiene).** Live atr "target" exits in
  `src/logs/bh_ftmo_outcomes.csv` are logged at ~0.5R even though deployed atr geometry is 1%/1% (a target
  hit should be +1R). Example: NZD_CHF short entry 0.46768 → exit 0.46534 = +0.5%, `close_reason="target"`.
  Either `src/bud/reconcile.py`'s `close_reason` classification is loose (labels by proximity, not exact
  stop/target match) or there's a fill/geometry discrepancy. Investigate the `close_reason` / `r_multiple_price`
  vs `realized_r` logic in reconcile.py. Muddied the #2 audit, so worth fixing for trustworthy outcome labels.

## Housekeeping for the restart
- **Leftover worktree** `/root/bh-worktrees/per-cell-quarantine` (branch `bud/per-cell-quarantine`, `edbfe1d`)
  was never cleaned up after the #1 merge. Safe to remove (CONFIRM first): `git worktree remove
  /root/bh-worktrees/per-cell-quarantine --force && git branch -D bud/per-cell-quarantine`.
- **Codex workflow:** branch + `/tmp/nextaction.md` + `/tmp/humanaction.sh`; **launch `codex` FROM inside the
  worktree dir** (`cd <wt> && codex`) or it blocks on the master-branch guard. Validation in nextaction should
  use `./run.sh ./lint.sh --changed`, not the tree-wide lint. Merge scripts must `rm` the untracked research
  copies in the master working tree before merging (they collide).
- master is in sync with origin; nothing pending to push.

## Operational incident log (preserved)

### 2026-05-26 Memorial Day silent failure
`check_market_status` in `bluehorseshoe/data/historical_data.py` had no US-holiday awareness.
Memorial Day (Mon) → Tue cron expected Mon SPY data, never got it, looped, aborted at 3 AM without a
report. **Durable fix `c0b88b6`:** `check_market_status` now walks `expected_date` back through
weekends AND NYSE holidays (reusing `core/market_calendar.nyse_holidays_for_year`); 3 regression tests
added. Lesson: the cron `2-6` schedule makes any Monday holiday a Tuesday silent failure unless the
bellwether is holiday-aware — now covered.
