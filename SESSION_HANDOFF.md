# Session Handoff (consolidated)

**Consolidated:** 2026-06-22. This is the single root handoff. It merges every session-handoff
document that was scattered across the repo into one place, organized by product (GORDON = US
equities/IBKR; BUD = forex/FTMO/OANDA) and then by thread. Within each product, threads are listed
newest-activity first. The detailed research source-of-truth docs still live next to their code (see
each thread's "Source / files"); this file is the index + carry-forward state.

> **Sources consolidated** (the 8 originals below were merged into this file and deleted 2026-06-22):
> the prior root `SESSION_HANDOFF.md`, `docs/handoff/GORDON_TEARDOWN_NEXT.md`,
> `docs/handoff/CONTRARIAN_NEXT.md`, `docs/handoff/EXIT_GEOMETRY_NEXT.md`,
> `docs/handoff/ATR_REGIME_NEXT.md`, `docs/handoff/NEWEY_WEST_HARNESS_NEXT.md`,
> `research/support_resistance_v1/HANDOFF.md`, `research/support_resistance_v1/HANDOFF_2026-06-18.md`,
> `research/sr_forex_v1/HANDOFF.md`. (The now-empty `docs/handoff/` directory was removed.)

---

## Status board

| Thread | Product | State | Last active | Next action |
|---|---|---|---|---|
| [`range_support` sleeve](#gordon--range_support-sleeve-live) | GORDON | **LIVE on master (paper)** | Jun 20 | Watch first live `-p` nights; then `--enable-time-flatten`; #8 regime filter |
| [S/R research](#gordon--supportresistance-research-validated-feeds-range_support) | GORDON | Validated, **uncommitted** | Jun 19 | Frontier #8 — context/regime filter |
| [Indicator teardown](#gordon--indicator-teardown-open-research) | GORDON | Open research | Jun 6 | Long-short market-neutral prototype |
| [Contrarian / entry-distance](#gordon--contrarian--entry-distance-older-follow-ups) | GORDON | Older follow-ups | May 22 | Fill-rate-by-tier vs simulator; `ENTRY_DISCOUNT_BY_SIGNAL` retune |
| [S/R on H4 FX](#bud--sr-on-h4-fx-live-two-validated-edges) | BUD | **Live, 2 validated edges** | **Jun 22** | Pre-close "good bounce" proxy (entry timing) |
| [Exit-geometry](#bud--exit-geometry-deployed) | BUD | **Deployed on master** | Jun 14 | Watch live long-MR vs backtest |
| [ATR-regime sizing](#bud--atr-regime-sizing-deploy-candidate) | BUD | Deploy candidate | Jun 14 | P4 audited (modest); prod wiring approval-gated |

---

# GORDON (US equities / IBKR)

## GORDON — `range_support` sleeve (LIVE)

**Date:** June 19–20, 2026. **Status:** Second live-book sleeve of the arc. Took the support/resistance
research result → wired into Gordon as the **`range_support`** long-only paper sleeve across 3 subsystems
and **merged to master**. Entry = pull-back to a pure-support level (1-ATR stop, **NO take-profit**);
exit = a bh_swing **up-day ratchet** + ~25-bar time-flatten. Live-on-paper from the next `-p`.
Memories: `project_range_support_live`, `project_support_resistance_explored`, `feedback_long_only_eval_bar`.
Plan: `/root/.claude/plans/linear-nibbling-meerkat.md`.

### What shipped
1. **Validated the S/R strategy** (see the S/R research thread below for the full arc).
2. **Wired it into Gordon (paper)** — 4 phases:
   - **Phase A (Engine):** `analysis/indicators/support_levels.py` (numeric port of the research detector,
     latest-bar only; **parity 585/585** vs research). `RangeSupportStrategy` in `strategy_interface.py`,
     registered `paper_tradeable=True`, `edge_weight=0.15` (conservative selection component, NOT gross
     +0.35R beta). Self-gates ER≤0.11 (PIT) + $3M $-vol + price $5-500 + pure-support proximity.
     `RANGE_SUPPORT_*` in `constants.py`.
   - **Phase B (PaperTrader):** `place_entry_stop_bracket` (2-leg entry+stop, no TP) in `ibkr_client.py`;
     `execute()` + staged path route `target≤0` to stop-only; `_validate_prices` accepts target≤0.
     trade_orders records `broker_order_ids=[entry, None, stop]`.
   - **Phase C (bh_swing — the live exit):** `stop_rules.propose_stop_ratchet` (up-close → stop=close−2·ATR,
     ratchet-only, idempotent per bar; passes the stop-tightening gate) + `propose_time_flatten`
     (CLOSE_NOW @25 bars). `manager.py` range_support block (flatten-first then ratchet, scoped by idea_id),
     loads daily close/ATR/bar-clock from a read-only DuckDBStore; `_flatten_position` = cancel stop +
     market-sell. New journal events stop_ratcheted/would_ratchet, position_flattened/would_flatten.
     Monitor flag `--enable-time-flatten`.
   - **Phase D (verify):** parity 585/585, offline end-to-end sleeve emission (no-TP, 1-ATR stop, PIT gates),
     13 new range_support tests + 2 no-TP tests, **146 bh_swing+trading regression green**, lint clean,
     deep_oversold management byte-for-byte unchanged.
3. **Committed + merged:** `f2f0a45` (A+B), `980870a` (C), `1be83fb` (dangling prior-session email fix).
   Fast-forward merged to **master**. **NOT pushed to origin.**

### June 20 follow-up (polish + repo hygiene)
- **RangeSupport now sorts candidates by support `strength`** (recency×swing-depth) — commit `e24f76d`.
  The sleeve emitted a flat score, so within-sleeve ties fell out ALPHABETICALLY. Bake-off
  (`research/support_resistance_v1/sort_key_bakeoff.py`, n=1046, cluster-by-symbol robust SE) found
  `strength` the ONLY key that monotonically sorts per-trade R (top tercile +0.66R vs +0.21R bottom,
  both halves + 24mo holdout). Raw touch-count is dead. **Root fix:** `strength` was missing from
  `RangeSupportStrategy`'s components dict → persisted as 0.0, ranking inert. Now in components + used as
  the SECONDARY sort key (after edge-weighted score) at every site. It's a tiebreak, not new edge.
- **Split-gap scanner** `src/bluehorseshoe/maintenance/split_gap_sweep.py` — commit `15d59a6`. Read-only
  finder for unadjusted corporate-action steps; found AZN 83.83→165.91 (×~2). **DECISION (Brand): do NOT
  gate symbols on it** — the sleeve trades post-jump supports and the ER gate fails safe; ships UNWIRED as
  a forensic tool. Memory `project_split_gap_decision`.

### LIVE NOW
- **`range_support` is a live paper sleeve on master** (HEAD `1be83fb` + `e24f76d`). From the next `-p` it
  submits entry + 1-ATR stop + **NO take-profit**, tagged `range_support`, sized by `score×edge_weight`.
- **bh_swing ratchet is ON** (stop-tightening, auto). **Auto-flatten is OFF** until `--enable-time-flatten`
  is added to the bh_swing cron (first autonomous-SELL authority in bh_swing).
- **Expect 0 range_support picks on many days** — it only fires on a range-bound name pulled back to a
  pure-support level. Not a bug.
- **Back-out:** additive sleeve; mute via `edge_weight`→0 (tracking-only) or `git revert` the feature
  commits. Kill all bh_swing management: `touch .bh_swing_pause_management`.

### Next steps
1. Watch the first live `-p` nights — confirm an order shows entry + 1-ATR stop, no TP. (Few/zero picks a
   given day is expected.)
2. After a few clean paper days, dry-run the bh_swing flatten (`--manage-dry-run` → check `would_flatten`),
   then add `--enable-time-flatten` to the cron.
3. **#8 context/regime filter — THE live research lead.** Dual-purpose: lifts the over-random edge into both
   halves AND screens the chronic-bleeder loss case (AENZ). Fold in via `edge_weight` / a regime gate.
4. Tune `edge_weight` / `slots_deep_oversold` if range_support over/under-competes with deep_oversold.
5. Push master to origin when satisfied.

### Live strategy roster
| name | display | live orders? | exit | notes |
|---|---|---|---|---|
| deep_oversold | DeepOS | **yes** | 2:1 ATR bracket | edge 0.142; nonbull-gated + Z″<1.1 solvency-filtered (Jun 9) |
| deep_oversold_ha | DeepOS+HA | **yes** | 2:1 ATR bracket | edge 0.404; nonbull + HA-green (solvency subsumed) |
| **range_support** | **RangeSupport** | **yes (NEW)** | **up-day ratchet + 25-bar flatten (bh_swing)** | edge 0.15; ER≤0.11 + pure-support; no take-profit |
| baseline, mean_reversion | Baseline, MeanRev | **NO — tracking-only** | — | forward-R only |
| adx_didown | ADX-Down | **NO — tracking-only** | — | promote only on OOS record |
Allocation: global top-N by `score*edge_weight`; sizing ∝ edge_weight (cap 2.5×); whole-share floor.

### The synthesis
Mean-reversion is the equity edge — dislocation harvested long by DeepOS/DeepOS+HA (nonbull-gated,
solvency-filtered). `range_support` adds a SECOND long-only mean-reversion expression: **buy a pullback to a
real support level in a range-bound name, 1-ATR stop, let a short hold run under an up-day ratchet.** Its
"makes-money" edge is robust; its edge OVER random is modest/regime-tilted (mostly beta) — fine for a
long-only book we'd run anyway. Open lever from "good"→"sharp" = the **#8 regime/context filter** (also the
bleeder screen). Bigger carried levers (June-9 full-book sim): HA `edge_weight`/allocation, 10-slot
crash-cluster capacity.

### Prior equity-sleeve sessions (condensed)
- **June 9:** First live-book change — solvency package: bare `deep_oversold` now **nonbull-gated +
  Altman-Z″<1.1 filtered** (reversible via `.env`). Built `data/fundamentals.parquet`; `load_solvency_asof`
  PIT loader. Memory `project_fundamentals_quality_condition`.
- **June 8:** Reporter shipped to mirror live book (`9acc1a9`). Donchian/SuperTrend/volume-gap/knife/earnings
  arcs closed (null/redundant). Built `data/earnings.parquet`. Lesson: HA-green ≈ a near-complete bad-context
  filter.
- **June 7:** Live book productionized — Baseline/MR → tracking-only (`887ef10`); edge-weighted alloc +
  conviction sizing (`5383573`); fractional coded then BLOCKED by IBKR 10243; deep-OS ML selection NULL.

---

## GORDON — Support/Resistance research (validated; feeds `range_support`)

**Date:** June 19, 2026 (history from June 18 below). **Status:** Campaign's first positive long-only result,
**VALIDATED and fully shaped** — this is the research that became the live `range_support` sleeve above.
**Files UNCOMMITTED** in `research/support_resistance_v1/` (ask Brand before any git ops).

**Setup:** enter long when price approaches a **pure-support level** (reversal-point cluster touched ≥3×,
*only ever* as support); **stop 1 ATR below entry**; **exit = up-day ratchet, stop→close−2 ATR on every
up-close day, ratchet-only**, capped ~**H≈25 bars**. 60 range-bound names, ~1,046 PIT trades, gap-aware
fills. **Makes money robustly** (cluster-t≈4.5, 44/60 names +, positive in both interleaved halves AND the
24mo holdout, outlier-robust, stop holds through realistic gaps).

**The honest framing (`feedback_long_only_eval_bar` — Brand corrected me twice):** the valid bar for a
≤1mo stop-protected LONG-ONLY sleeve is *robust per-trade money in the normal regime*, NOT "beat a random
long / survive a decade of bear data / survivorship" — beta is the medium we trade and Brand is the
catastrophe switch. On that bar it passes decisively. Its edge *over random* is real but
marginal/regime-tilted (lives in carrying markets) — a "is the detector worth its complexity / simplify"
question, not a validity gate.

**THE EJECT (safeword, `feedback_the_eject`):** after productive incremental *visual* work I bail to opaque
aggregate stats and pronounce the theory dead on a marginal pooled number. When Brand says "The Eject,"
STOP and go back to concrete examples. Statistics are a clue to LOOK closer, not a verdict. The whole
positive result came from getting OUT of stats-mode and looking at events.

### This session's arc (June 19)
- **Doors #1 & #2 CLOSED null:** wait-for-confirmation bounce (`bounce_sim_confirm.py`) didn't beat a random
  line; follow-the-break (`break_sim.py`) null on range-bound AND trending. **S/R-as-entry-selection is now
  comprehensively closed** across detectors, both regimes, both baselines.
- **New thread — reversal-point detector → pure-support + EXIT edge:** build levels from **reversal turning
  points** (touch → leave → come back), not a price histogram. `reversal_profile.cluster_levels` clusters
  pivots within `tol_atr` (0.4 ATR); **≥3 touches = a level**; PIT-safe. Character by BEHAVIOR (only
  turn-ups → support, only turn-downs → resistance, both → flip). Proximity test: strength & flips
  ANTI-select; **pure-support is best**.

### Frontiers resolved (all June 19)
1. **Tail-robustness — CLEARED** (`tail_robustness.py`, n=1050). +0.355R not a unicorn; edge over random
   barely moves under de-tailing. REAL's top 1% = 31.8% of R-sum vs RANDOM's 69.7% → random is the
   tail-dependent one. Caveats: median trade = −1R (fat-tail let-it-run profile); CI uncorrected for clustering.
2 & 7. **Exit design — fixed-stop is expectancy-optimal; up-day ratchet wins on CAPITAL EFFICIENCY (chosen).**
   ATR-chandelier and ratchet both LOSE mean-R to the fixed stop (any trail truncates the fat-tail runners),
   but R/bar peaks at ratchet M≈2; `validate_ratchet.py` (fixed vs close−2ATR) — ratchet wins R/bar in ALL 4
   splits, beats fixed on BOTH metrics in the 24mo holdout. Break-even redeploy rate +0.0176 R/bar. By
   Brand's capital-efficiency objective → **EXIT = close−2ATR up-day ratchet**; fixed stop = the
   pure-per-trade-money alternative.
3. **Horizon — short holds win on THROUGHPUT** (`horizon_sweep.py`). Per-trade R climbs monotonically
   (+0.225 H10 → +0.653 H120) but **R/bar FALLS** (+0.0364 → +0.0201). Losers stop at median 3-4 bars;
   winners ride. edge/bar vs random peaks at H≈20-30. **Provisional pick: H≈20-30, no trailing, 1-ATR stop.**
   CAVEAT: +9R/slot/yr assumes a fresh setup is always available to recycle capital into — real cadence gates it.
4. **Portfolio sim — PARKED (Brand's steer).** A mechanical N-slot sim doesn't map Brand's discretionary
   interference. Standard = per-trade evaluation (`bud_eval_objective`). Don't auto-run it.
5. **Significance gate — SPLIT VERDICT** (`significance_bracket.py`). **(A) "makes money?" PASSES
   DECISIVELY** (cluster_t +4.5–4.9, both halves + holdout). **(B) "beats RANDOM timing?" FAILS as a clean
   gate** (cluster_t 1.35–1.89, regime-tilted: + in odd quarters / ≈0 in even). Reframe: (B) is the wrong
   gate for a long-only sleeve we'll trade anyway.
6. **Survivorship / gap-through-stop — PASSES** (`survivorship_gap.py`). Gap-aware fills cost only −0.055R;
   stop holds. DB is survivor-only (flag: ingest AV LISTING_STATUS delisted OHLCV for a clean dead-names
   test). One real failure mode = **chronic slow-bleeders** (AENZ −20R) — screened by the ER filter + #8.

### CURRENT FRONTIER — open next moves
8. **Context / regime filter — THE live lead (dual-purpose).** The even/odd split says support-alpha lives
   in carrying markets, and the survivorship study says chronic bleeders are the one real loss source. Both
   → **skip pure-support entries when the name is rolling over / gate on market regime.** GO LOOK first
   (`feedback_the_eject`): what separates even-vs-odd quarters (vol regime? SPY trend?). Then test a
   trend/health gate.
9. **Deployment shaping** (after #8): run alongside the live deep_oversold sleeve; support-as-mechanic may
   bolt onto deep_oversold rather than stand alone. Per-trade eval only.

### Key parameters as left
- cluster: `k=3` (fractal pivot half-window), `tol_atr=0.4`, `min_touch=3`, `halflife=126`.
- approach: `NEAR=0.5` ATR (price within this of the level, from above), `APPROACH=10`, `GAP=15`; horizon **H≈25**.
- bracket: stop **1.0 ATR** below entry. **EXIT = up-day ratchet** (close−2.0·ATR(entry) on up-close days,
  ratchet-only), else hold to H≈25. Gap-aware fills. Alternative (pure-per-trade money) = fixed 1-ATR stop.
- universe: `ER_MAX=0.11`, $3M median $-vol, $5–500, ≥900 bars → 60 names.

### Source / files (all in `research/support_resistance_v1/`, UNCOMMITTED)
- `reversal_profile.py` — **the detector** (`swing_pivots`, `build_pivots`, `cluster_pivots`/`cluster_levels`,
  `find_zones`, `build_reversal_profile`). `irregularities.py` — 2nd-derivative peak/shoulder finder.
- `proximity_test.py`, `significance.py`, `bracket_tally.py`, `target_sweep.py`, `tail_robustness.py`,
  `trailing_sweep.py`, `horizon_sweep.py`, `significance_bracket.py`, `survivorship_gap.py`,
  `exit_ratchet.py`, `ratchet_width.py`, `validate_ratchet.py`, `sort_key_bakeoff.py`.
- Charts (email PNGs — headless box): `chart_reversal_profile.py`, `chart_reversal_levels.py`,
  `chart_level_story.py`, `chart_gallery.py`. `build_trend_universe.py` — trending-universe builder.
- Doors: `bounce_sim_confirm.py` (#1 null), `break_sim.py` (#2 null).
- Reused: `detector.py` (`wilder_atr`), `detector_v3.py` (`range_score`, `detect_events`), `profile.py`, `fusion.py`.

### Pre-reversal-point history (June 18 — superseded detail, preserved)
- **v1** `detector.py` (swing-pivot + volume strength) — NULL: distance→R flat, "strength" anti-selects.
- **v2** `detector_v2.py` (rejection-confirmed zones, 68-combo respect sweep) → ~0 lift. Brand's critique was
  the breakthrough: anchored on single-bar SPIKES not consolidation SHELVES, one-sided touches, line locked
  to the pivot extreme, tested on a trend-heavy universe.
- **v3** `detector_v3.py` — shelf anchors, polarity-agnostic touches, magnet center (reproduced Brand's AAPL
  ~247), recency-weighted, NMS dedupe. Two bugs fixed (lookahead via evolving center; touches dated at
  departure not shelf bar). PIT-verified; Brand eyeball-validated (~17:7 AAPL).
- **profile** `profile.py` (Volume-Profile histogram + `find_peaks`) and **fusion** `fusion.py` (peak kept
  only if ≥2 shelf reactions within `snap_atr`) — Brand greenlit fusion.
- **recovery** `recovery.py` — +2 ATR win = median 7 trading days; full bounce peaks ~20 bars → "2–4 week
  swings" (ignored stops, too rosy).
- **bounce_sim** `bounce_sim.py` — the honest stop-aware test that showed the naive first-touch bounce is OUT
  (stopped 47–66%, loses to a random nearby line). That null pointed to "wait for the flatten" (door #1) and
  "follow the break" (door #2) — both since closed, leading to the reversal-point detector above.

---

## GORDON — Indicator teardown (open research)

**Date:** June 6, 2026. **Mission:** go through Gordon's ~41 indicators one at a time — decide for each
whether it carries real tradeable edge, is redundant, or removable — and build a **factor-based confidence
store** (edge-weighted, shrinkage) to replace the anti-selecting hand-weighted `weights.json`. Nothing
committed this session (research scripts in `research/indicator_screen/`).

**⚠️ METHOD SUPERSEDED 2026-06-05 — de-overlap was BIASED; the standard is now NEWEY-WEST.** Episode-start
de-overlap is a *biased* estimator for persisting dislocation signals (keeps the onset/knife bar, drops the
deeper-in-run bars where reversion lives) — it SIGN-FLIPPED real edge to null. New standard = **keep ALL
firings + Newey-West (Bartlett kernel, L=hold−1)** on the full population. Wired into `clean_harness.py`
PASS 2 (DE-OVERLAP | FULL-POP(cluster) | FULL-POP(NW)). Memory `project_deoverlap_signflip_newey_west`.

### NW re-audit results (the book is mapped)
- **RSI re-validated REAL under NW:** `rsi_oversold(<30)` NW +0.079R t6.6 nonbull / +0.080 t10.5 all
  (de-overlap had falsely read it −0.066). COVID-fragile (only neg year = 2020). Moderate oversold reverts;
  rsi<20 extreme is a knife (−0.156 t−4.0).
- **Dislocation factor is BROAD and SLOW:** whole slow-below family positive under NW both regimes
  (below_sma200 +0.053 t9.4, far_below_sma50 +0.069 t9.8 nonbull). Slow-MA version is all-regime year-stable
  (+11/−0 incl COVID), beats COVID-fragile RSI; monetizes (nonbull +0.06R post-cost) but SAME factor as the
  cloud (redundant, not new coverage).
- **TIMESCALE is the discriminant:** slow/smoothed/persistent dislocation = alpha; fast/sharp (stoch, cci,
  BB-break, gap-down) = bull-beta that knifes in nonbull. Confidence store must separate by timescale.
- **PSAR/ADX re-confirmed negative-for-LONG, rigorously** (NW *more* negative). ADX(21)-nonbull was a real
  de-overlap false-negative but incremental + depth-control tests proved it redundant with dislocation and
  NOT an amplifier (destroys the oversold edge within fixed depth). No standalone long edge.
- **TREND FAMILY = year-stable SHORT-selector, NOT dead** (`feedback_trend_family_not_dead`). Negative-long ⇒
  short leg of the mean-reversion factor (adx_uptrend short +0.102R t7.0 nonbull, +11/−0 yr; above_sma200/
  golden_cross/rsi_strong all +11/−0). RELATIVE + nonbull-only; not shortable outright (drift). Only
  persistent-state trend signals translate (breakout EVENTS don't).

### NEXT DOOR — market-neutral long-short prototype
Long dislocation (below_cloud/below_sma200) + short trend-extension (above_sma200/adx_uptrend),
dollar-neutral, nonbull-gated. Up-drift cancels in the pair → harvest the two alphas. Needs a REAL
paired-portfolio backtest (leg overlap, sizing, turnover, actual borrow), not two single-leg numbers added.
First deployable-product candidate of the teardown.

### What's settled (all in auto-memory)
- Indicator-based daily-equity SELECTION is closed (`project_why_believed_synthesis`,
  `project_indicator_edge_screen`): trend/breakout family robustly anti-predicts (daily returns mean-revert).
- ~41 indicators = ~5 independent factors (`project_signal_independence`): one giant 20-signal
  price-position/momentum cluster (no-edge) + ADX, volatility, volume, gap, candles. Diversification ceiling
  √5≈2.2×, NOT a linear sum. Confidence store must be FACTOR-based.
- Pruning needs EDGE not correlation (`project_pruning_edge_not_correlation`).
- ADX fully worked, weak (best config fails the time-split = regime-luck). PSAR fully closed (mechanistically
  understood; stays weight 0.0, don't delete code).
- Exit/geometry is the real lever: the 2:1 ATR runner ~doubles expectancy over 1:1 on RANDOM entries;
  nonbull + longer hold is the hot regime. Edge lives in structure, not entry selection.

### The clean harness (the bar for every indicator)
ATR-scaled bracket, 2:1 runner (TP=2·ATR14, SL=1·ATR14), entry at close, N=10/15d, same-bar tie =
stop-first, timeout = mark-to-market in R. Vol floor `ATR/close ≥ 0.5%` (kills cash/bond-ETF grinders).
Symbol-clustered paired stats + the BOTH-time-halves sign-stability gate + cost check (5/10/20 bps).
Templates in `research/indicator_screen/` (`adx_param_sweep_clean.py`, `psar_*.py`, `signal_independence*.py`).

### Newey-West harness column (June 5 — the precursor that set the NW standard)
`research/indicator_screen/clean_harness.py` PASS 2 now reports **three** numbers per signal side by side
(de-overlap path untouched; all additive: `BF`/`bumpF`, `NW`/`bumpNW`, `NW_W`/`L_NW`, `stNW`):
- **DE-OVERLAP** — existing production-faithful number (one position at a time).
- **FULL-POP (cluster)** — every firing kept, same symbol-clustering. Isolates whether de-overlap moves the
  point estimate.
- **FULL-POP (Newey-West)** — every firing kept, trade-weighted, Bartlett/HAC t. Bandwidth `L = BR_N−1`;
  the kernel weight `(BR_N−j)/BR_N` **is** the true forward-window overlap fraction. The honest-power t:
  keeps all data, corrects the SE for overlap instead of discarding rows.

**Why:** de-overlap with a flat N-bar block treats a day-1 re-fire (≈90% same bet) like a day-9 re-fire
(≈10% overlap, nearly a fresh later-window bet) — discarding nearly-independent signal. Overlapping forward
returns have a triangular autocorrelation dying at lag `BR_N` — that triangle IS the Bartlett kernel.

**How to run:** `cd /root/BlueHorseshoe && .venv/bin/python research/indicator_screen/clean_harness.py`
(real config `N_SYMBOLS=2000`, ~minutes, read-only DuckDB; **first check `pgrep -f main.py` is clear**).
**Reading it:** (1) RANDOM full-pop & full-NW must be ≈+0.000R t=0.0 (demeaning sanity). (2) DE-OVERLAP vs
FULL-POP(cluster) means agree → de-overlap unbiased; diverge → it's moving the estimate. (3) full-NW t = the
honest significance; collapse vs de-overlap t = leaning on overlap-correlated firings, stronger = the
keep-all-data power win. **Status (2026-06-05):** wired + smoke-verified (120 sym, plumbing only); NOT yet
run at full 2000-sym scale — pick up there. (Caveats: NW kernel mildly conservative; cluster=symbol-weighted
vs NW=trade-weighted, so a mean gap can be weighting not de-overlap; only PASS 2 treated.) Two unbuilt
follow-ons: conditional-on-persistence scale-in curve; rolling re-entry re-struck off current price.

### Guardrails / state
- Score-backfill cron PAUSED (`.score_backfill_pause` present). Live scorer UNTOUCHED.
- Nothing committed; new files are untracked research scripts. Don't commit without Brand's OK.

---

## GORDON — Contrarian / entry-distance (older follow-ups)

**Created:** 2026-05-22. **Originating session:** `9a48c5c7-fb77-4623-8bcd-20611dd14520`. Full doc:
`docs/results/CONTRARIAN_SHORT_v1_RESULTS.md`. Memory: `project_contrarian_short_v1`.

### Key findings (compressed)
1. **Limit-at-`entry_price` mechanic is load-bearing for production edge** (~+0.28 pp/trade vs market-buy at
   next-day open).
2. **Score ranking inverts under limit-entry**, but only because of `ENTRY_DISCOUNT_BY_SIGNAL` in
   `src/bluehorseshoe/analysis/constants.py:75` (EXTREME→0.05 ATR, WEAK→0.50 ATR). Wide entry-distance (low
   score, high ATR discount) → ~3.4× per-trade R vs narrow. Cross-tab: entry-distance has all the edge; score
   has zero residual.
3. **Provenance verified** — no look-ahead (`entry_price = close_on_score_date − atr_discount × atr`).
4. **TIF=DAY for the entry leg shipped** (`382fb91`); TP/SL remain GTC.

### What to gather before resuming
- **Fill rate by signal-strength tier** (query `trade_orders` + IBKR executions; group by tier derived from
  score). Expected if the simulator is right: EXTREME ~71% / MEDIUM ~60% / WEAK ~48%. Divergence = first data
  point that reshapes the thinking.
- **Per-tier per-trade R for filled positions** (tiny samples — directional only).
- **Orphan orders** (confirm IBKR auto-cancelled child legs when DAY entries expired unfilled).
- **Mongo audit-trail health** (rows stuck at `status:"submitted"` with no broker presence).

### Open follow-ups
- **Volatility confound:** `entry_dist_pct = atr_discount × atr / close` — Q5 might be "trade volatile names"
  not "trade wider pullback." Needs within-volatility-quintile decomposition.
- **Longer-window replication** (backfill `trade_scores`, currently only back to 2026-02-12).
- **`ENTRY_DISCOUNT_BY_SIGNAL` retuning** (invert / flatten / rank post-hoc — pick once live data arrives).
- **Mongo audit-trail sweep** (flip stale `submitted` → `cancelled_no_fill`).

### Incident log — 2026-05-26 Memorial Day silent failure
`check_market_status` in `bluehorseshoe/data/historical_data.py` had no US-holiday awareness. Memorial Day
(Mon) → Tue cron expected Mon SPY data, never got it, looped, aborted at 3 AM without a report. Recovery:
killed the loop, manually `-r 2026-05-22` + `send_report_email.py`. **Durable fix `c0b88b6`:**
`check_market_status` now walks `expected_date` back through weekends AND NYSE holidays (reusing
`core/market_calendar.nyse_holidays_for_year`); 3 regression tests added. Lesson: the cron `2-6` schedule
makes any Monday holiday a Tuesday silent failure unless the bellwether is holiday-aware — now covered.

---

# BUD (forex / FTMO / OANDA)

## BUD — S/R on H4 FX (live, two validated edges)

**Date:** June 22, 2026 (most recently active thread). **Status:** Live, promising, NOT closed — **two
validated edges in hand** (buying support AND selling resistance, both make money after costs across all 40
pairs). Files in `research/sr_forex_v1/`. Memory `project_sr_pivot_window_k3`.

**How Brand wants this worked (he has corrected these repeatedly):**
- **Plain language, no jargon** — "makes about +0.16 per trade," not "netR +0.16, t=9." Judge by total money
  after costs; beating random is NOT required.
- **Never eject.** A null closes ONE door. When a result looks negative, first ask "is my *test* wrong?" and
  "how could this differ across pairs/conditions?" (This session the "strength failed" headline was a
  measurement artifact.)
- **Don't drive / don't end with a binary.** Report state plainly; let Brand steer.
- **Shorts are allowed on FTMO** — use them (now a validated edge).
- Charts can't be seen in-terminal — **email them** (`EmailService().send_file(...)`; queued ≠ delivered).

### What's SOLID (build on it)
- **Recognition (settled — Brand's spec):** body-anchored pivots, **k=3** (±3-bar pivot window),
  **min_touches=3**, **recency-weighted** (halflife=400 H4 bars), tol=0.0012, min_gap=0.0025, top_n=12.
  Walk-forward: trailing 1200 bars, re-detect every 120.
- **Two validated edges** (full 40-pair, after real spread, positive in both halves + holdout):
  - **Buy the "good bounce" off support: ~+0.17 per trade** (n=7507, dirn `above`).
  - **Sell the "good bounce" off resistance (SHORT): ~+0.145 per trade** (n=7146, dirn `below`).
  - A "good bounce" = the tag bar is **low-volume AND has a big rejection wick** (`sel` flag).
  - Exit: 1-ATR stop + 2-ATR ratchet (ATR frozen at entry, cap 120 bars); a plain fixed 1-ATR-stop /
    2–3-ATR-target works nearly as well. **The exit is basically solved.**
- **Saved data** `tickets_strength.parquet` (58,321 tags, all 40 pairs): pair, ts, dirn, **strength**, volz,
  wick, **sel**, heldR (ratchet), bailR, nextR (next-open), br2R/br3R + win flags. Most analysis = read this
  file + a groupby (no re-walk).

### Killed this session (don't re-chase)
- **Stop-and-reverse / breakdown shorts** — dead end-to-end. The prior +0.51 was favorable *excursion*, not
  edge: symmetric run vs snap-back (~2.5 ATR each), reaches +2ATR before −1ATR only 32% (need >33%). No exit
  geometry fixes symmetric excursion. (`reverse_eval.py`, `reverse_mfe.py`)
- **Strength-stacking via ABSOLUTE gate (str≥6/≥8)** — great on 6 hand-picked pairs (+0.28→+0.67), FLAT
  (~+0.16) on all 40 (strength scale isn't comparable across pairs). **Within-pair normalization partially
  revives it** (top-quarter-within-pair → ~+0.23) — real but much smaller than the mirage. (`per_pair_strength.py`)
- **No-cleverness deployable versions** — "hold every strong support" / "buy every strong support with a
  fixed bracket" both LOSE on the full set (~−0.05). The 6-pair positives were flattering-pair selection.
- **Buy the bar AFTER the touch** — turns +0.16 into −0.24 (good bounces run up too fast; must rest at the
  level). (`entry_and_bracket.py`)
- **"Flip as a signal"** (strong-support-fails ⇒ short that pair) — no link (corr −0.03). (`long_vs_short.py`)

### The ONE open problem = the prize (entry timing)
The good-bounce edge needs two things that can't both be had: **knowing it's a good bounce** (only confirmed
once the H4 candle closes — low-vol & big-wick) AND **buying at the level** (price has moved off it by the
close). Waiting kills it (−0.24); strength was the hoped-for shortcut and doesn't generalize. **The gap is
worth ~+0.4 per trade.** The exit is solved; this is the whole game.

### Live forward doors (pick one, measure, stay honest)
1. **A pre-close proxy for "good bounce"** — features knowable BEFORE the candle closes (approach
   speed/geometry, prior-bar structure, where the level sits in range, distance travelled in). Highest value:
   directly attacks the entry-timing prize. Pre-tag volume regime was already flat — try the geometric ones.
2. **Per-pair DIRECTION map.** Shorts make money on ~11 pairs where longs don't (CAD_CHF, AUD_CHF, USD_PLN,
   USD_CZK, AUD_USD…); some buy-only (USD_NOK, CAD_JPY, USD_SEK); some both (USD_JPY, USD_CHF, EUR_CZK). Gate:
   **is a pair's buy/sell preference stable over time, or just history?** (persistence test — decides everything.)
3. **Within-pair strength** as a smaller secondary filter (needs a rolling/expanding rank to be
   look-ahead-free).

### Source / files (`research/sr_forex_v1/`)
- Detection: `srlook.py` (`cluster_pts` w/ recency, `thin`), `approaches.py` (`detect_levels_body`,
  `find_tags`, `atr`), `reversal_size.py` (`load_px`, `levels_from`).
- Ticket pipeline: `ticket_gen.py` → `tickets.parquet`. Bundled analysis (carries strength + all exits,
  saves `tickets_strength.parquet`): **`confirm_full.py`** — full 40-pair, ~25 min (`confirm_full.py PAIR`
  = single pair, ~25s). (Bug fixed: walk-forward `t += STEP` was once missing → infinite loop on block 1.)
- Slices (instant, read the parquet): `per_pair_strength.py`, `long_vs_short.py`, `size_by_strength.py`,
  `stacking_test.py`, `entry_and_bracket.py`. Charts (email): `chart_trades.py`, `latest_supports.py`,
  `why_no_touch.py`, `what_is_the_line.py`, `whats_special.py`. Diagnostics: `probe_blocks.py`.

### Genuinely settled (don't re-litigate)
- Recognition is good (k=3, 3-touch, recency, body-anchored) — Brand's spec, edge confirmed robust.
- S/R as a *selection* signal is closed; the value is the **bracket + exit on the good-bounce fade**, in
  **both directions**.
- The deployment blocker is **entry timing**, not level quality and not (pooled) strength.

### Process / safety
- Heavy runs OOM-risk the 7.8GB box during the **00:30–03:30 UTC** nightly maintenance window — run
  `confirm_full` outside it.
- `tickets_pre_recency.parquet` is the pre-recency baseline; safe to delete once done comparing.

---

## BUD — Exit-geometry (deployed)

**Date:** June 14, 2026. **Status:** Done and **deployed on master** (`c367ec1`, pushed). The exit sweep
found the best per-trade exit by *total money*, and the **steadier alt is wired LIVE** into the autonomous
trader + briefing, scoped to the long mean-reversion cells.

### What happened
1. **P4 — FTMO-constrained sim** (`60dd7a3`, `research/atr_regime_v1/atr_regime_p4_ftmo.py`). Audited off its
   misleading "no deploy / pass-rate" headline: pass-rate is push-dominated (a sizing/throughput proxy, not
   edge); the vol-regime filter is a modest risk/dead-weight trim; `hard_gate` is constraint-optimal (reverses
   P3's `size_down` preference). Per-trade re-cut: win rate monotone in calm (low 53% / high 49%).
2. **Exit-geometry sweep** (`a11e05c`/merge `53d0cb4`, `research/exit_geometry_v1/`). Swept TP×SL×hold
   (6×5×4=120) on the deployed long-MR book, ranked by **total money** (sum of per-trade R); parameterized sim
   asserted == `_lib.py` at 1%/1%/14d (154,083 fires). Winner BOTH books: **TP 1.5% / SL 0.6% / 10-day** —
   strong-4 +1308R vs 1:1/14d +1157R (+13%); full-6 +2085R vs +1745R (+20%); profitable A/B + holdout. Pattern:
   **shorter hold (10 not 14d) + target wider than stop**. Win rate falls (34.7%) while money rises — total
   money, not win rate, is the scoreboard.
3. **Deploy** (`c367ec1`, corrects `c4b50f7`). Wired the **steadier alt (TP 1.5% / SL 1.0% / 10-day)** into the
   **LIVE trader** + briefing, scoped to ONLY validated cells — long, MR (bb/rsi/ema/stoch), mid entry.
   Override baked into `briefing.compute_entry_stop_target` (keyed on cell); 10-day cap added to
   `auto_trader.close_aged_positions`. A live (non-dry) run closed the aged stoch/EUR_GBP long via the new cap.

### Critical gotchas — carry forward
- **The LIVE cron trader is `src/bud/auto_trader.py`** (`run_bh_ftmo_trader.sh`, :16), **NOT `auto_v2.py`**
  (legacy, unscheduled — a decoy name). `run_bh_ftmo_v2_paper.sh` is not in crontab. Trace the cron before
  claiming any trader change is live.
- **BUD per-trade-setup objective = TOTAL MONEY** (sum of R at constant risk), NOT win rate, NOT
  portfolio/account drawdown, NOT regime conditioning (`bud_eval_objective_total_pnl` — corrected twice).
- **Validation split** = interleaved calendar-quarter blocks (COVID in both halves) + last-24mo holdout;
  profit required in A AND B AND holdout (`bud_validation_split_interleaved`).

### Immediate next options
1. **Watch the live long-MR trades vs the backtest.** Deployed exits project ~+14% more total money on the
   strong-4 book; the reconciler (`src/bud/reconcile.py` → `bh_ftmo_outcomes.csv`) joins OANDA closes →
   placements. First matured long-MR trades land in ~weeks.
2. **The aggressive winner (TP 1.5% / SL 0.6% / 10-day)** — most total money but a tighter stop, uneven across
   eras on strong-4. **Parked**; deploy only if Brand wants more aggression after the steadier alt runs.
3. ~~**Relative-value / cointegration (door #2)**~~ **CLOSED 2026-06-15** — P0 opened (15 pairs), P1 in-sample
   promising (+113R), **P2 holdout FAILED (−61R OOS, 13/15 flipped)**, dynamic-β confirmed a static-β fitting
   artifact. **Last signal door of the campaign — all signal doors now dead; BUD edge = exits + execution +
   risk.** Commits `fb7d7ab`/`d00b148`/`50373f0` (`project_relative_value_door`).

---

## BUD — ATR-regime sizing (deploy candidate)

**Date:** June 14, 2026. **Status:** The BUD H4-forex edge-hunt reached its first deploy candidate — a
**volatility-regime sizing conditioner**. Everything through **P3 is committed on master** (`c18e7a2`).
**P4 has since been run + audited** (see the Exit-geometry thread): the R-space win is a modest
risk/dead-weight trim once FTMO-constrained, and `hard_gate` is constraint-optimal. Production wiring is
**approval-gated by Brand** — not an auto-proceed. Memory `project_confluence_closed_dislocation_depth`.

### The campaign arc (compressed)
| Door | Verdict | Doc |
|---|---|---|
| **Confluence** (combine 2 signals) | DEAD — controls beat candidates 7:1 | `docs/planning/CONFLUENCE_SWEEP_v1.md` |
| **Dislocation-depth** (deeper = better) | DEAD — 0/12; equity deep-oversold doesn't transfer | `docs/planning/DISLOCATION_DEPTH_v1.md` |
| **Volatility-regime** (MR works in calm vol) | **SURVIVED → deploy candidate** | `docs/planning/ATR_REGIME_v1.md` (§13–§16) |

Each null was a *constructive* close. **Method laws:** judge at the **book/sleeve level under Newey-West**,
not per-cell (per-cell collapses, the book survives); **audit the harness before accepting an agent's
verdict** (overruled false-negative gates in P1/P1b, tempered a too-rosy P2b). Argue from significance, not
point estimates.

### The deploy candidate
**`size_down_high_0_5`** — on the **causal/PIT w252 rolling ATR percentile** (per-pair, 252-bar), size MR
entries: **low 1.0× / mid 1.0× / high 0.5×** (half-size when the pair's vol is in its top third vs its own
recent ~6 weeks). Strong-4 long MR book (bb/rsi/ema/stoch, deduped one trade per pair-bar): **return/DD
1.74→2.37 (+36%), maxDD −21%, throughput-neutral, stable both halves.** Alpha arbiter (vs same conditioner
on a random-entry book): return/return-DD gain = MR cell-alpha; DD reduction = generic vol-beta. Both
deployable. **Caveats:** return-alpha is strong-4-specific (full-6 adds only +4.6R → mostly DD control on the
broad book); `hard_gate` (skip high) has better risk numbers at −36% throughput — a real deploy choice vs the
throughput-neutral `size_down`.

### Reusable harness (reuse, don't rebuild)
- `research/atr_regime_v1/atr_regime_{p1b,p2,p2b,p3}.py` — sleeve construction, w252 regime bucketing,
  all-bars baseline, NW + date-cluster SE, book sim, sizing forms.
- `research/dislocation_depth_v1/depth_fires.csv` — **154k fires** (the trade universe + regime).
  `depth_extract.py`, `research/confluence_v1/{factor_grouping,co_fire}.py` (`DIR_MASKERS`, `choose_params`,
  `deployed_cells`, faithful to production `_EVALUATORS`).
- `research/v2_executable_regate/harness/_lib.py` (`sim_{long,short}_{mid,limit}`, 1%/1% R);
  `.../seed/nw_regate.py` (Newey-West).
- FTMO sim: `src/bh_ftmo/backtest/ftmo_rules.py` (`load_ftmo_config`, `FtmoRuleEngine`, `ChallengeState`).
  **Never hand-type FTMO limits** — hard-stop if the config is placeholder (`FtmoConfigUnverifiedError`).

### Pending decision / fences
- **Production wiring** = a **w252 vol-regime sizing multiplier in the v2 sizing path (`bud/`)** — a
  production change, **approval-gated by Brand + needs validation**, NOT auto-proceed.
- If the R-space win doesn't survive constraints (P4 indicated it's modest), the vol-regime thread closes as a
  risk-control footnote. Relative-value door #2 has since also closed (see Exit-geometry thread).

---

# Global carry-forward (applies across threads)

## Standing corrections (DO NOT repeat) — see memory
- **`feedback_long_only_eval_bar`:** don't gate a long-only ≤1mo stop-protected sleeve on "beats random /
  needs bear data / survivorship"; beta is harvestable, Brand is the catastrophe switch. Valid bar = robust
  per-trade money in the normal regime.
- **`feedback_the_eject`:** after productive visual work I bail to aggregate stats and pronounce a theory dead
  on a marginal number. When Brand says "The Eject," STOP and go look at concrete examples. Stats = a clue to LOOK.
- **`feedback_makes_money_not_beats_random`:** pass bar = profitable after costs; beating random is NOT
  required; worse-than-random is the only random concern.
- **`feedback_trend_family_not_dead`:** don't call the trend family "dead"; long-only 10d tests mean-revert;
  negative-long-R = SHORT-selector candidate.
- **`feedback_no_premature_indicator_verdicts`:** explain the result + audit the harness before any verdict.
- **`bud_eval_objective_total_pnl`:** judge BUD exits/setups by individual-trade total R; NO
  portfolio/account-drawdown, NO regime conditioning.
- **`bud_validation_split_interleaved`:** interleaved calendar-quarter blocks (COVID in both halves) +
  last-24mo recent holdout; must profit in A AND B AND holdout.
- **Plain language with Brand** — concrete, jargon-free; DO the validation rather than repeatedly asking.
- **`feedback_ask_before_every_commit`:** show diff+validation then ASK; a prior "commit it" does NOT carry to
  the next change. **No PRs (solo dev)** — branch+commit+push is the publish step; git ops via
  `/tmp/humanaction.sh` for Brand to run in tmux.
- `PYTHONPATH=src` (or `./run.sh`) for any direct python. `pgrep -f main.py` false-positives on its own
  command line — verify with `ps -eo pid,etime,cmd`. **Background `until ! pgrep -f "<name>"` self-matches**
  if the loop's own command contains `<name>` → infinite sleep; rely on the task-completion notification.

## Ops state (still live)
- **bh_swing monitor lives at `src/gordon/swing_monitor.py`** (NOT the `bh_swing/bh_swing_monitor.py` path in
  CLAUDE.md — that ref is stale). Cron `1-59/5` during US hours, `--manage` live (client_id=7).
- **Solvency sleeve is LIVE** (June 9): bare DeepOS nonbull-gated + Altman-Z″<1.1 filtered (`.env` flags,
  defaulted True in code by `175b82b`). Weekly fundamentals refresh cron added (`175b82b`) — verify it never
  holds the prod DuckDB write-lock during its AV pull.
- **Equity cron** `run_daily_pipeline.sh` Tue–Sat 01:00 UTC (`-u→-p→journal→--evaluate→report→email`).
- **BUD live cron trader** = `src/bud/auto_trader.py` (`run_bh_ftmo_trader.sh`), NOT `auto_v2.py`.
- **PAPER_TRADING_ENABLED=true** — `-p` submits orders unless `--no-paper`.
- **Fractional deploy BLOCKED** (IBKR 10243) — whole-share floor until the account enables fractional +
  `src/verify_fractional_bracket.py` PASS.

## Process safety
- **~8GB box:** serialize backtests; NEVER run heavy jobs concurrent with `-p`/`-u` (DuckDB lock + OOM). Check
  `pgrep -af "main.py"` and try a read-only DuckDB connect before launching heavy scripts; the watcher-wait
  pattern (`while kill -0 <PID>; do sleep 30; done`, run_in_background) works well. Long AV pulls →
  parquet/cache, then a BRIEF write to seed the prod DB; never hold the prod lock during the network pull.
- **Blackout is day-gated:** Tue–Sat 01:00 UTC (`run_daily_pipeline.sh`) + the 00:30–03:30 UTC maintenance
  window. Sun/Mon are clear — don't park ~2.5h on a Sunday.
- **Headless box:** Brand cannot view images locally — email PNG charts (`EmailService`; Brevo, queued ≠
  delivered, verify via Gmail MCP) or give an scp path (`scp root@134.122.15.186:<abs/path> .`).
- Async sub-agents are DENIED Bash → run sweeps as local `run_in_background` procs, not via the Agent tool.

## Memory pointers (auto-memory index = MEMORY.md)
- Gordon: `project_range_support_live`, `project_support_resistance_explored`, `project_split_gap_decision`,
  `project_deoverlap_signflip_newey_west`, `project_why_believed_synthesis`, `project_indicator_edge_screen`,
  `project_signal_independence`, `project_pruning_edge_not_correlation`, `project_contrarian_short_v1`,
  `project_rsi_oversold_bracket_edge`, `project_fundamentals_quality_condition`.
- Bud: `project_sr_pivot_window_k3`, `project_confluence_closed_dislocation_depth`,
  `project_relative_value_door`, `project_v2_methodology`, `project_v2_nw_regate`,
  `bud_eval_objective_total_pnl`, `bud_validation_split_interleaved`.
- Feedback: `feedback_long_only_eval_bar`, `feedback_the_eject`, `feedback_makes_money_not_beats_random`,
  `feedback_trend_family_not_dead`, `feedback_no_premature_indicator_verdicts`, `feedback_ask_before_every_commit`.
