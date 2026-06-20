# Support/Resistance research — session handoff (2026-06-19)

## TL;DR — where we are
The campaign's **first positive, long-only result is now VALIDATED and fully shaped** (2026-06-19 session).
**Setup:** enter long when price approaches a **pure-support level** (reversal-point cluster touched ≥3×,
*only ever* as support); **stop 1 ATR below entry**; **exit = up-day ratchet, stop→close−2 ATR on every
up-close day, ratchet-only**, capped at a ~**H≈25-bar** horizon. 60 range-bound names, ~1,046 PIT trades,
gap-aware fills. **It makes money robustly** (cluster-t≈4.5, 44/60 names +, positive in both interleaved
halves AND the 24mo holdout, outlier-robust, stop holds through realistic gaps).
**The honest framing (Brand corrected me on this — see [[feedback_long_only_eval_bar]]):** the valid bar
for a ≤1mo stop-protected LONG-ONLY sleeve is *robust per-trade money in the normal regime*, NOT "beat a
random long" / "survive a decade of bear data" — beta is the medium we trade and Brand is the catastrophe
switch. On THAT bar it passes decisively. The signal's edge *over random* is real but marginal/regime-tilted
(lives in carrying markets) — that's a "is the detector worth its complexity / can we simplify" question,
not a validity gate. **Remaining open:** context/regime filter (frontier #8 — also the bleeder risk-control),
then deployment shaping alongside deep_oversold. Files UNCOMMITTED. **Don't eject** (see below).

## The goal (Brand's idea) — unchanged
Measure how close a symbol is to a support/resistance line and how *strong* that line is,
and use proximity-to-a-strong-support as a signal of an upward move. Brand validates levels
**by eye** and steers; surface findings honestly, lead with the next constructive move.

## Environment / hard constraints (read before doing anything)
- **Long-only** (Gordon/IBKR paper can't short).
- **Range-bound universe**: `range_score` = Kaufman efficiency ratio; keep ER ≤ 0.11. Liquidity
  $5–500 price, $3M median dollar-vol, ≥900 bars since 2016 → **60 names** from `symbols.txt`.
  For a TRENDING universe use `build_trend_universe.py` → `symbols_trend.txt` (vol-floored, ER-ranked;
  needed because `symbols.txt` is all rangey and the raw ER-leaders are cash/bond ETFs).
- **Brand is on a headless box — cannot view images locally.** Email PNGs (now reliable, see Email),
  or give an scp path: `scp root@134.122.15.186:<abs/path> .`
- Run scripts: `source .venv/bin/activate && PYTHONPATH=src:research/support_resistance_v1 python research/support_resistance_v1/<script>.py [args]`
- OHLCV: `data/ohlcv.duckdb` (symbol,date,open,high,low,close,volume); 12,320 symbols, 7,463 with ≥900 bars.
- **Never run heavy work during the `-u`/`-p` pipeline** (OOM + it holds the DuckDB *write* lock —
  even `-u --active-only`). Check `pgrep -af "src/main.py"`; if a writer holds the lock, wait it out
  (`while kill -0 <pid>; do sleep 5; done` in a bg proc, then run).
- Async sub-agents are DENIED Bash → run sweeps as local `run_in_background` procs.

## Email (FIXED this session — verify, don't trust)
- Brevo SMTP relay. `EmailService.send()` now returns a **GUID** (or None), tags every subject with
  `[id:<uuid>]` + an `X-BH-Message-Id` header, and logs "QUEUED at relay (delivery NOT confirmed)".
  **A 250 from the relay ≠ delivered.** ALWAYS verify via the Gmail MCP:
  `search_threads query:"subject:<guid-prefix> in:anywhere newer_than:1h"`.
- Root cause of the 2026-06-19 silent-drop outage: a **deactivated Brevo API key** blackholed accepted
  mail while SMTP kept returning 250-queued (auth uses the separate SMTP key, which stayed live).
  Brand reactivated the API key → delivery restored. It was NOT a quota (we'd sent ~14 vs a 300/day cap).
- EmailService + test change committed via `/tmp/humanaction.sh` (confirm it landed). Recipient
  `brandg@gmail.com`; load `.env` into `os.environ` first.

## THE EJECT — safeword / critical working-mode note
Brand named my recurring failure mode **"The Eject"** (memory `feedback_the_eject.md`): after productive
incremental **visual** work, I bail to opaque aggregate stats and pronounce the theory dead on a marginal
pooled number. When he says "The Eject," STOP and go back to showing concrete examples. **Statistics are a
clue to LOOK closer, not a verdict.** Significance testing is the LATE gate on a *well-understood* signal,
not a guillotine on an incompletely-understood one. The whole positive result below came from getting OUT
of stats-mode and looking at events.

## This session's arc
### Doors #1 & #2 (from the prior handoff) — CLOSED, null
- **Door #1** wait-for-confirmation bounce (`bounce_sim_confirm.py`): shelf-confirm entry didn't beat a
  random line; a shelf-floor stop helped but generically (non-S/R). Sharpened anti-structure baseline confirmed.
- **Door #2** follow-the-break (`break_sim.py`): null on range-bound (real-level breaks are WORSE than a
  random line — a false-breakout machine) AND on a trending universe (positive but still worse than random).
  **S/R-as-entry-selection is now comprehensively closed** across detectors, both regimes, both baselines.

### New thread — reversal-point detector → pure-support + EXIT edge
1. **Reframe (Brand):** the price histogram smears because it projects onto price and only sees *horizontal*
   congestion. Build levels from **reversal turning points** (touch → leave → come back) instead.
2. **Second-derivative irregularity detector** (`irregularities.py`): finds peaks AND **shoulders** — the
   VZ 42/49 levels that prominence-based `find_peaks` threw away.
3. **Direct tight clustering** (`reversal_profile.cluster_levels`/`cluster_pivots`): cluster reversal pivots
   within `tol_atr` (0.4 ATR); **≥3 touches = a level**. Point-in-time safe (a fractal pivot at bar *b* is
   only visible at *b+k*). Recency/magnitude are a strength **score, never a gate** (so old-but-real and
   sharp few-touch extremes both survive). Catches the 42/52 the histogram-peak method missed.
4. **Character by BEHAVIOR, not position:** only turn-downs → resistance, only turn-ups → support, both →
   **flip** (respected from both sides). My earlier below/above-current-price coloring was a *regime-gap
   artifact* — Brand caught it. Flips dominate (4–6 of 8 across VZ/KO/PFE/T).
5. **Proximity test** (`proximity_test.py`): broad "near any level" edge is mostly the *pullback* confound;
   pullback-matched residual +0.083(10d)/+0.196(20d). **Strength & flips ANTI-select; pure-support is best.**
6. **Significance** (`significance.py`): broad edge FAILED (cluster/NW_t ≈ 0.5, front-loaded). **Pure-support
   survived 2 of 3** (cluster_t 2.3–2.6, per-symbol_t 2.5–2.8, NW marginal ~1.5). *(I ejected here; Brand
   corrected → go look.)*
7. **Look, don't summarize** — gallery + level-story charts (`chart_gallery.py`, `chart_level_story.py`):
   actual pure-support approaches, in context, fully axed.
8. **Stop-aware scoring (Brand's insight):** a dip below support is only a failure **if it would have
   stopped you out**. Score each approach as a bracket: stop *S* below entry, target = 1.5× stop.
9. `bracket_tally.py`: a **1% stop is the only LOSING config** (it sits inside the noise — naive, as Brand
   said). Every sane stop is positive AND beats random entry. **1-ATR stop best: +0.104 R/trade, +0.064 over
   random, 44% wins** (40% is breakeven at 1.5:1).
10. **MFE / target sweep** (`target_sweep.py`): survivors run a **median 4R**; fixed targets always cap too
    early (expectancy climbs monotonically with target); **no target — let it run, 1-ATR stop, time exit =
    +0.355 R/trade, edge +0.223 over random**; oracle (exit at the peak) ceiling **+0.90R** → a trailing
    stop has a lot of room.

## CURRENT FRONTIER — open next moves (in order)
1. ~~**Tail-robustness** on the no-target +0.355R~~ **CLEARED 2026-06-19** (`tail_robustness.py`,
   n=1050). The +0.355R is NOT a unicorn artifact — the edge over random barely moves under de-tailing:
   mean edge +0.222 → winsor-1% +0.210 → winsor-5% +0.205 → drop-top-10 +0.203. Drop the 10 biggest
   winners outright and REAL still = +0.237R (vs random's intact +0.133). The tell: REAL's top 1% is only
   **31.8%** of its R-sum vs RANDOM's **69.7%** — random is the tail-dependent one, not the signal.
   Bootstrap 95%CI [+0.21,+0.50] excludes 0. **Two caveats:** (i) median trade = −1R for BOTH real and
   random → this is a fat-tail let-it-run profile by design (win rate 31.8% vs 27.5%), profit is all in the
   right tail; (ii) CI uses NO overlap/cluster correction — that's the frontier-#3 significance gate, still
   pending. This check answers "few outliers?" (no), not "clustered-SE significant?" (untested). Out: `tail_robustness.out`.
2. ~~**Trailing-stop exit sweep**~~ **DONE 2026-06-19 — trailing is NOT the lever; HOLD LENGTH is**
   (`trailing_sweep.py`, ATR-chandelier, caches entry contexts once then sweeps M×A×H cheaply). Within-run
   real-vs-real across exits (clean; same entries — the random baseline wobbles ±0.1 between runs on one MC
   draw, don't over-read its absolute edge). At H=20 NO chandelier config beats the plain no-target time exit:
   tight trails (M=1) whipsaw (+0.14R — these are deliberately low-vol range names, chop stops you before the
   move matures), wide trails (M=4) just converge to the time exit (+0.353 ≈ +0.347). breakeven@1R also worse
   (+0.258). **The surprise: extending the horizon 20→40 bars lifts the no-target from +0.347→+0.456R and
   edge-over-random +0.148→+0.270** (real rises faster than random; win% drops 32→25 but winners run further).
   The 20-bar cap was TRUNCATING winners; downside is capped at −1 by the fixed stop the whole time, so longer
   hold = pure upside optionality. Out: `trailing_sweep.out`.
   - **Caveat on edge numbers:** the random-entry baseline is one MC draw of ~1043 entries (bootstrap CI on
     its mean was huge, ~[+0.01,+0.26]); edge point-estimates swing ±0.1 just from the draw. Rely on within-run
     real-vs-real comparisons, not the absolute edge, until the significance gate (frontier #3).
3. ~~**Horizon sweep + smarter exit**~~ **DONE 2026-06-19 — short holds win on THROUGHPUT** (`horizon_sweep.py`,
   adds exit-timing-by-outcome + R-per-bar-of-deployed-capital; H∈{10,20,30,40,60,80,120}, n=1015). Two curves
   move OPPOSITE: per-trade R climbs monotonically and never plateaus (+0.225 H10 → +0.653 H120), but **R/bar
   FALLS monotonically (+0.0364 → +0.0201)** → annualized R/slot (R/bar×252) is ~+9.2R at H10-20 vs +5.1R at
   H120. **Short holds ~2× the capital efficiency.** Brand's capital intuition CONFIRMED + quantified: losers
   stop at median **3-4 bars** (56-79% within 5 bars), winners ride the full hold, losers consume only ~⅓ of
   deployed bar-capital. **edge/bar (vs random) peaks at H≈20-30** (+0.0228) → throughput sweet spot. Second
   reason short wins: random R ALSO climbs with H (+0.10→+0.24) = the rangey universe drifts up, so long holds
   harvest BETA; the support-bounce ALPHA is concentrated in the first ~20-30 bars (H10 real +0.225 ≫ rand +0.102).
   **Provisional pick: H≈20-30, no trailing, 1-ATR stop.** Out: `horizon_sweep.out`.
   - **CAVEAT (the binding constraint):** +9R/slot/yr assumes a fresh pure-support setup is ALWAYS available to
     recycle freed capital into — real cadence (GAP=15/name, support-proximity) gates it. Same ceiling that
     killed BUD's $100/day. **Next move below answers this before any deploy framing.**
4. **Portfolio sim — PARKED 2026-06-19 (Brand's steer).** A mechanical N-slot fill-recycle sim doesn't map
   Brand's discretionary interference (he skips/holds/sizes by hand), so it would either over-precise or rule
   out trades he'd actually take. Standard here = **per-trade evaluation** (same as `bud_eval_objective`). Note
   the throughput insight (R/bar, capital recycling) is ALREADY per-trade-derived — it did NOT need the sim;
   the sim only addressed "is +9R/slot reachable," which his interference makes unanswerable mechanically. Don't
   auto-run it. (A concurrent-availability *count* — purely descriptive, no fill assumptions — is still fair game
   if Brand wants to eyeball cadence.)
5. ~~**Significance gate**~~ **DONE 2026-06-19 — SPLIT VERDICT** (`significance_bracket.py`: cluster-by-symbol
   + per-symbol t + Newey-West + interleaved-quarter split + 24mo holdout; n=1046 real vs 1046 random; H∈{20,25,30}).
   - **(A) "makes money?" PASSES DECISIVELY.** mean R +0.35→+0.42; cluster_t **+4.5–4.9**, per-symbol t +4.5–4.8
     (**44-45/60 names +**), NW_t +2.8–3.1; positive in BOTH interleaved halves AND the 24mo holdout.
   - **(B) "beats RANDOM timing?" FAILS as a clean gate.** edge +0.13→+0.22 but cluster_t only +1.35→+1.89 (<2),
     ~half the symbols +, and edge is NEGATIVE in even quarters / strongly + in odd quarters → **regime-tilted**
     (support adds value when the market carries; ≈beta otherwise). Consistent with [[project_entry_signal_alpha_absent]].
   - **Reframe (Brand, [[feedback_long_only_eval_bar]]):** "beats random" is the wrong gate for a long-only sleeve
     we'll trade anyway — it's a complexity/simplify question, not validity. On the right bar (A) it's validated.
     Out: `significance_bracket.out`.
6. ~~**Survivorship / gap-through-stop**~~ **DONE 2026-06-19 — PASSES** (`survivorship_gap.py`). Brand's thesis
   ("dying name, but stop caps the one bad touch → per-trade still fine"): **confirmed.** (A) Gap-aware fills on
   survivors (if a bar opens below the stop you fill at the open): mean R_ideal +0.392 → **R_gap +0.338, slippage
   only −0.055R**; 16% of stops gap through, worst −3 to −5.5R but rare; the stop HOLDS, expectancy isn't gap-
   inflated. (B) **The DB is survivor-only** (only ~3 real crashed delistings w/ history — all A-names, an ingestion
   remnant; can't run a clean dead-names test — flag: proper fix = ingest AV LISTING_STATUS delisted OHLCV). Case
   study of 5 decliners (94 trades on names that fell to −98%): net **≈+1.6R total** — ACER −98%→only −1.7R, ADMS
   −81%→**+20.3R**. The one failure mode = **chronic slow-bleeders** (AENZ −20R: every "support" fails, −1R stops
   stack) — but that's exactly the rolling-over name the ER filter + context-filter (#8) screen out. Out: `survivorship_gap.out`.
7. ~~**Exit design**~~ **DONE 2026-06-19 — fixed-stop is expectancy-optimal; Brand's up-day ratchet wins on
   CAPITAL EFFICIENCY (now the chosen exit).** Three exit families tested, all gap-aware:
   - ATR-chandelier off the running high (`trailing_sweep.py`) and 1-ATR up-day ratchet (`exit_ratchet.py`): both
     LOSE to the fixed stop — any pullback-trail truncates the runners, and the runners ARE the fat-tail edge.
   - **Ratchet-width sweep** (`ratchet_width.py`, stop→close−M·ATR on up days): mean R climbs monotonically to
     fixed as M→4 (best trail = no trail, on money). BUT **R/bar peaks at M≈2** (+0.0322 vs fixed +0.0295).
   - **Validation** (`validate_ratchet.py`, fixed vs close−2ATR across splits): **ratchet wins R/bar in ALL 4**
     (FULL/A/B/holdout), never loses; mean-R cost shows ONLY in the strong-trend odd-Q half; in the **24mo holdout
     the ratchet beats fixed on BOTH metrics** (+0.492 vs +0.438 meanR, +0.0508 vs +0.0372 R/bar). Robust, not overfit.
   - **Math reconciliation (Brand's challenge):** per-trade R (fixed higher) vs R/bar (ratchet higher) differ by
     denominator. Break-even redeploy rate = +0.0176 R/bar (~60% of the strategy's own rate) — clear it and the
     ratchet wins; pure idle-cash worst case costs only +0.037R/trade. By Brand's capital-efficiency objective →
     **EXIT = close−2ATR up-day ratchet.** Fixed stop documented as the pure-per-trade-money alternative.
     Outs: `trailing_sweep.out`, `exit_ratchet.out`, `ratchet_width.out`, `validate_ratchet.out`.
8. **Context / regime filter — THE live lead (dual-purpose).** Motivated twice over: the (B) even/odd split says
   support-alpha lives in carrying markets, AND the survivorship case study says chronic bleeders (AENZ) are the
   one real loss source. Both point to: **skip pure-support entries when the name is rolling over / gate on market
   regime.** GO LOOK first (per [[feedback_the_eject]]): what separates even-vs-odd quarters (vol regime? SPY trend?).
   Then test a trend/health gate; target = pull the over-random edge into both halves AND screen the bleeders.
9. **Deployment shaping** (after #8): how to run this alongside the live deep_oversold sleeve — support-as-mechanic
   (principled stop + cadence) may bolt onto deep_oversold rather than stand alone. Per-trade eval only; Brand sizes/skips.

## Key parameters as left
- cluster: `k=3` (fractal pivot half-window), `tol_atr=0.4`, `min_touch=3`, `halflife=126`.
- approach: `NEAR=0.5` ATR (price within this of the level, from above), `APPROACH=10`, `GAP=15`; horizon **H≈25** bars.
- bracket (as left): stop **1.0 ATR** below entry. **EXIT = up-day ratchet** — on every up-close day raise the stop
  to `close − 2.0·ATR(entry)`, ratchet-only (never lower), else hold to the H≈25 horizon. Gap-aware fills assumed
  (fill at the open if a bar opens below the stop). Alternative for a pure-per-trade-money objective = fixed 1-ATR
  stop, no trail, same horizon (higher mean R, lower R/bar). Earlier "no fixed target 1.5× stop" is superseded.
- universe filter: `ER_MAX=0.11`, $3M median dollar-vol, $5–500, ≥900 bars → 60 names.

## File map (all in research/support_resistance_v1/, all UNCOMMITTED to git)
- `reversal_profile.py` — **the detector**: `swing_pivots`, `build_pivots`, `cluster_pivots`/`cluster_levels`
  (PIT clustering + character), `find_zones`, `build_reversal_profile`.
- `irregularities.py` — second-derivative peak/shoulder finder.
- `chart_reversal_profile.py`, `chart_reversal_levels.py` — reversal histogram + by-character level charts.
- `chart_level_story.py` — ONE continuous chart: level + defining turn-ups + every test as a bracket.
  CLI: `SYM NDAYS STOP` where STOP is `1.0atr` or `0.02` (pct). `--email`.
- `chart_gallery.py` — wins-vs-stops gallery under the 1-ATR bracket (full axes). `--email`.
- `proximity_test.py`, `significance.py` — proximity edge + its (broad-failed / pure-support-marginal) stats.
- `bracket_tally.py` — stop-width sweep + random baseline.
- `target_sweep.py` — MFE distribution + target sweep + no-target/oracle. (Exports the shared entry constants
  START/ER_MAX/WARMUP/NEAR/APPROACH/GAP that the 2026-06-19 scripts import.)
- `tail_robustness.py` — de-tailing the no-target +0.355R (frontier #1, CLEARED).
- `trailing_sweep.py` — ATR-chandelier M×A×H sweep (frontier #2/#7); surfaced hold-length>trailing.
- `horizon_sweep.py` — exit-timing-by-outcome + R-per-bar capital efficiency (frontier #3).
- `significance_bracket.py` — the bracket significance gate, cluster/perSym/NW + interleaved split + holdout (frontier #5).
- `survivorship_gap.py` — gap-aware fills on survivors + dead-name case study (frontier #6).
- `exit_ratchet.py` — Brand's up-day ratchet (close−M·ATR) vs fixed; `ratchet_width.py` — M sweep;
  `validate_ratchet.py` — fixed vs close−2ATR across splits (frontier #7, ratchet validated on R/bar).
- `build_trend_universe.py` — trending-universe builder (vol-floored).
- `bounce_sim_confirm.py` (door #1, null), `break_sim.py` (door #2, null).
- Reused earlier stack: `detector.py` (`wilder_atr`), `detector_v3.py` (`range_score`, `detect_events`),
  `profile.py` (`compute_profile`, now with `weight_mode='frequency'`), `fusion.py`.
- Emailed PNGs live in this dir (`*_level_story.png`, `pure_support_gallery.png`, `*_reversal_levels.png`, …).

## Pre-reversal-point history
Earlier detector evolution (v1/v2/v3, profile/fusion, recovery, the original door framing) is in
`HANDOFF_2026-06-18.md` (preserved this session) and memory `project_support_resistance_explored.md`. The
v1/v2/v3 nulls were all about S/R-as-entry-*selection*, now comprehensively closed; the live thread is
**reversal-point detection + exit edge**.

## Suggested first move next session
Entry/stop/exit are settled and validated (setup in the TL;DR; exit = close−2ATR up-day ratchet, H≈25). The
live lead is **frontier #8 — the context/regime filter**: first GO LOOK at what separates the even-Q (flat,
edge≈0) from odd-Q (carrying, edge strong) quarters — vol regime? SPY/market trend? — then test a trend/health
gate that (a) pulls the over-random edge into both halves and (b) screens chronic bleeders like AENZ. Keep
per-trade eval; don't re-run the parked portfolio sim; don't eject on a marginal sub-cut. After #8, frontier #9
= deployment shaping alongside deep_oversold. NOTE: all files still UNCOMMITTED — ask Brand before any git ops.
