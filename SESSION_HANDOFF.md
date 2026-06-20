# Session Handoff

**Date:** June 19, 2026  (+ June 20 follow-up — see "June 20 follow-up" section below)
**Status:** **SECOND LIVE-BOOK SLEEVE OF THE ARC.** Took the support/resistance idea from a validated research
result → wired into Gordon as the new **`range_support`** long-only paper sleeve, across 3 subsystems, and
**merged to master.** Entry = pull-back to a pure-support level (1-ATR stop, NO take-profit); exit = a bh_swing
**up-day ratchet** + ~25-bar time-flatten. Live-on-paper from the next `-p`. Memories: `project_range_support_live`,
`project_support_resistance_explored`, `feedback_long_only_eval_bar`. Research detail:
`research/support_resistance_v1/HANDOFF.md`. Plan: `/root/.claude/plans/linear-nibbling-meerkat.md`.

## What this session did (in order)
1. **Validated the S/R strategy** (research/support_resistance_v1/, all UNCOMMITTED there):
   - Tail-robustness CLEARED (+0.355R not a unicorn; random is the tail-dependent one).
   - Exit design: trailing/chandelier LOSE to a fixed stop (truncate the fat-tail runners); **short holds win on
     capital efficiency** (R/bar ~2× at H≈20-30 vs H120). **Brand's up-day ratchet (stop→close−2·ATR on up-close
     days)** wins R/bar across all validation splits incl. holdout → chosen exit.
   - Significance gate = SPLIT verdict: **(A) "makes money" PASSES** (cluster-t≈4.5, both interleaved halves +
     24mo holdout); **(B) "beats random timing" marginal/regime-tilted** (≈beta in flat markets).
   - Survivorship/gap probe PASSES: gap-aware fills cost only −0.055R (stop holds); DB is survivor-only so the
     dead-name test is anecdotal (5 decliners net ≈+1.6R; ACER −98%→−1.7R). One real loss mode = chronic bleeders
     (AENZ) — screened by ER filter + the future #8 regime filter.
   - **KEY REFRAME (`feedback_long_only_eval_bar`):** don't gate a ≤1mo stop-protected long-only sleeve on "beat
     random / bear-data / survivorship" — beta is the medium, Brand is the catastrophe switch. Valid bar = robust
     per-trade money in the normal regime. Brand corrected me on this twice; I'd been moving the goalposts.
2. **Wired it into Gordon (paper)** — plan-mode → 3 recon agents mapped the Engine/PaperTrader/bh_swing → 4 phases:
   - **Phase A (Engine):** `analysis/indicators/support_levels.py` (numeric port of the research detector,
     latest-bar only; **parity 585/585** vs research). `RangeSupportStrategy` in `strategy_interface.py`,
     registered `paper_tradeable=True`, `edge_weight=0.15` (conservative selection component, NOT gross +0.35R beta).
     Self-gates ER≤0.11 (PIT) + $3M $-vol + price $5-500 + pure-support proximity. `RANGE_SUPPORT_*` in `constants.py`.
   - **Phase B (PaperTrader):** `place_entry_stop_bracket` (2-leg entry+stop, no TP) in `ibkr_client.py`; `execute()`
     + staged path route `target≤0` to stop-only; `_validate_prices` accepts target≤0. trade_orders records
     `broker_order_ids=[entry, None, stop]`.
   - **Phase C (bh_swing — the live exit):** `stop_rules.propose_stop_ratchet` (up-close → stop=close−2·ATR,
     ratchet-only, idempotent per bar; passes the stop-tightening gate) + `propose_time_flatten` (CLOSE_NOW @25
     bars). `manager.py` range_support block (flatten-first then ratchet, scoped by idea_id strategy), loads daily
     close/ATR/bar-clock from a read-only DuckDBStore; `_flatten_position` = cancel stop + market-sell. New journal
     events stop_ratcheted/would_ratchet, position_flattened/would_flatten. Monitor flag `--enable-time-flatten`.
   - **Phase D (verify):** parity 585/585, offline end-to-end sleeve emission (no-TP, 1-ATR stop, PIT gates),
     13 new range_support tests + 2 no-TP tests, **146 bh_swing+trading regression green**, lint clean,
     deep_oversold management byte-for-byte unchanged.
3. **Committed + merged:** `f2f0a45` (A+B), `980870a` (C), `1be83fb` (the dangling prior-session email fix).
   Fast-forward merged to **master**. **NOT pushed to origin.**

## LIVE NOW (the change)
- **`range_support` is a live paper sleeve on master** (HEAD `1be83fb`). From the next `-p` it submits entry +
  1-ATR stop + **NO take-profit**, tagged `range_support`, sized by `score×edge_weight` (≈2.1, ~even with
  deep_oversold 2.06; deep_oversold_ha 5.86 outranks; 3/10 slots reserved for deep_oversold).
- **bh_swing ratchet is ON** for range_support (stop-tightening, auto). **Auto-flatten is OFF** until
  `--enable-time-flatten` is added to the bh_swing cron (first autonomous-SELL authority in bh_swing).
- **Expect 0 range_support picks on many days** — it only fires when a range-bound name is pulled back to a
  pure-support level. Not a bug.
- **Back-out:** the sleeve is additive; to mute it set `edge_weight`→0 (tracking-only) or `git revert` the two
  feature commits. Kill all bh_swing management: `touch .bh_swing_pause_management`.

## June 20 follow-up (range_support polish + repo hygiene)
- **RangeSupport now sorts candidates by support `strength`** (recency×swing-depth) — commit `e24f76d`. The sleeve
  emitted a flat score, so within-sleeve ties fell out ALPHABETICALLY. Bake-off (`research/support_resistance_v1/
  sort_key_bakeoff.py`, n=1046, cluster-by-symbol robust SE) found `strength` the ONLY key that monotonically sorts
  per-trade R (top tercile +0.66R vs +0.21R bottom, both interleaved halves + 24mo holdout). Raw touch-count is dead
  (non-monotone, sign-flips). **Root fix:** `strength` was missing from `RangeSupportStrategy`'s components dict →
  persisted as 0.0, ranking was inert (caught by a regen, not the unit test). Now in components + used as the
  SECONDARY sort key (after edge-weighted score) at every site (html_reporter, paper_trader both branches). It's a
  tiebreak, not new edge (baseline R flat across terciles; t≈1.90). Verified on a full `-p` for 2026-06-18 (paper:
  0 new submitted — book already 10/10 occupied, expected). Memory `project_range_support_live`.
- **Split-gap scanner** `src/bluehorseshoe/maintenance/split_gap_sweep.py` — commit `15d59a6`. Read-only finder for
  unadjusted corporate-action steps (whole OHLC bar ×~constant tidy ratio on flat volume); found AZN 83.83→165.91
  (×~2). **DECISION (Brand): do NOT gate symbols on it** — the sleeve trades post-jump supports and the ER gate
  fails safe; ships UNWIRED as a forensic tool only. Memory `project_split_gap_decision`.

## In progress / leftovers (non-blocking)
- **master NOT pushed to origin** — push when ready.
- **research/support_resistance_v1/ is now COMMITTED** (`4b7967d`, June 20) — scripts + HANDOFF/RESULTS docs +
  symbols.txt; regenerable artifacts (PNG/CSV/.out/.log/combos) are `.gitignore`d. HANDOFF.md there = S/R source of truth.
- **`--enable-time-flatten` not yet in the bh_swing crontab** (crontab not in git) — add after watching ratchet+entries clean.

## Next steps
1. **Watch the first live `-p` nights** with range_support — confirm an order shows entry + 1-ATR stop, no TP in
   `trade_orders`/IBKR paper. (Few/zero picks on a given day is expected.)
2. **After a few clean paper days,** dry-run the bh_swing flatten (`--manage-dry-run` → check `would_flatten`),
   then add `--enable-time-flatten` to the cron.
3. **#8 context/regime filter — THE live research lead.** Dual-purpose: lifts the over-random edge into both
   halves AND screens the chronic-bleeder loss case (AENZ). When it lands, fold in via `edge_weight` / a regime
   gate on the sleeve. (First GO LOOK at what separates the even-vs-odd quarters — vol regime? SPY trend?)
4. **Tune** `edge_weight` / `slots_deep_oversold` if range_support over/under-competes with deep_oversold.
5. **Push master to origin** when satisfied.

## Live strategy roster
| name | display | live orders? | exit | notes |
|---|---|---|---|---|
| deep_oversold | DeepOS | **yes** | 2:1 ATR bracket | edge 0.142; nonbull-gated + Z″<1.1 solvency-filtered (June 9) |
| deep_oversold_ha | DeepOS+HA | **yes** | 2:1 ATR bracket | edge 0.404; nonbull + HA-green (solvency subsumed) |
| **range_support** | **RangeSupport** | **yes (NEW)** | **up-day ratchet + 25-bar flatten (bh_swing)** | edge 0.15; ER≤0.11 + pure-support; no take-profit |
| baseline, mean_reversion | Baseline, MeanRev | **NO — tracking-only** | — | forward-R only |
| adx_didown | ADX-Down | **NO — tracking-only** | — | promote only on OOS record |
Allocation: global top-N by `score*edge_weight`; sizing ∝ edge_weight (cap 2.5×); whole-share floor.

## Standing corrections (DO NOT repeat) — see memory
- **`feedback_long_only_eval_bar` (NEW):** don't gate a long-only ≤1mo stop-protected sleeve on "beats random /
  needs bear data / survivorship"; beta is harvestable, Brand is the catastrophe switch. Valid bar = robust
  per-trade money in the normal regime. ("Beats random" is a complexity/simplify question, not validity.)
- **`feedback_the_eject`:** after productive visual work I bail to aggregate stats and pronounce a theory dead on
  a marginal number. When Brand says "The Eject," STOP and go look at concrete examples. Stats = a clue to LOOK.
- `feedback_trend_family_not_dead`: don't call the trend family "dead"; long-only 10d tests mean-revert.
- `feedback_no_premature_indicator_verdicts`: explain the result + audit the harness before any verdict.
- **Plain language with Brand** — explain in concrete terms, jargon-free; DO the validation rather than repeatedly asking.
- `feedback_ask_before_every_commit`: show diff+validation then ASK; a prior "commit it" does NOT carry to the next.
- **git ops via `/tmp/humanaction.sh`** for Brand to run in tmux (solo dev, no PRs; branch/commit/merge to master).
- `PYTHONPATH=src` (or `./run.sh`) for any direct python. `pgrep -f main.py` false-positives on its own command
  line — verify with `ps -eo pid,etime,cmd`. **Background `until ! pgrep -f "<name>"` self-matches** if the loop's
  own command contains `<name>` → infinite sleep; rely on the task-completion notification instead.

## Carry-forward ops state (still live)
- **bh_swing monitor lives at `src/gordon/swing_monitor.py`** (NOT the `bh_swing/bh_swing_monitor.py` path in
  CLAUDE.md — that ref is stale). Cron `1-59/5` during US hours, `--manage` live (client_id=7).
- **Solvency sleeve is LIVE** (June 9): bare DeepOS nonbull-gated + Altman-Z″<1.1 filtered (`.env` flags, defaulted
  True in code by 175b82b). Weekly fundamentals refresh cron added (175b82b) — verify it never holds the prod
  DuckDB write-lock during its AV pull.
- **Equity cron** `run_daily_pipeline.sh` Tue–Sat 01:00 UTC (`-u→-p→journal→--evaluate→report→email`).
- **PAPER_TRADING_ENABLED=true** — `-p` submits orders unless `--no-paper`.
- **~8GB box:** serialize backtests; NEVER run heavy jobs concurrent with `-p`/`-u` (DuckDB lock + OOM). Long AV
  pulls → parquet/cache, then a BRIEF write to seed the prod DB; never hold the prod lock during the network pull.
- **Fractional deploy BLOCKED** (IBKR 10243) — whole-share floor until the account enables fractional +
  `src/verify_fractional_bracket.py` PASS.

## The synthesis (updated)
Mean-reversion is the equity edge — dislocation harvested long by DeepOS/DeepOS+HA (nonbull-gated, solvency-filtered).
This session adds a SECOND long-only mean-reversion expression: **buy a pullback to a real support level in a
range-bound name, 1-ATR stop, let a short hold run under an up-day ratchet.** Its "makes-money" edge is robust; its
edge OVER random is modest/regime-tilted (mostly beta) — which is fine for a long-only book we'd run anyway. The
open lever that would turn it from "good" to "sharp" is the **#8 regime/context filter** (also the bleeder screen).
Bigger carried levers (from the June-9 full-book sim): HA `edge_weight`/allocation, and 10-slot crash-cluster capacity.

---
## Prior sessions (condensed)
**June 9:** First live-book change — deployed the solvency package: bare `deep_oversold` now **nonbull-gated +
Altman-Z″<1.1 filtered** (within-sleeve edge certain P=1.00; net-of-production modest/uncertain; reversible via
`.env`). Built `data/fundamentals.parquet`; `load_solvency_asof` PIT loader. Memory `project_fundamentals_quality_condition`.
**June 8:** Reporter shipped to mirror live book (`9acc1a9`). Donchian/SuperTrend/volume-gap/knife/earnings arcs
all closed (null/redundant). Built `data/earnings.parquet`. Lesson: HA-green is a near-complete bad-context filter.
**June 7:** Live book productionized — Baseline/MR → tracking-only (`887ef10`); edge-weighted alloc + conviction
sizing (`5383573`); fractional coded then BLOCKED by IBKR 10243; deep-OS ML selection NULL. HA deep dive → DeepOS+HA.
