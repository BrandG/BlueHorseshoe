# Gordon indicator teardown — session handoff (updated 2026-06-06)

## ⚠️ METHOD SUPERSEDED 2026-06-05 — de-overlap was BIASED; the standard is now NEWEY-WEST
The "honest measurement method" below used **episode-start de-overlap**, which we proved is a *biased*
estimator for persisting dislocation signals (keeps the onset/falling-knife bar, drops the deeper-in-run
bars where reversion lives). It SIGN-FLIPPED real edge to null. **New standard = keep ALL firings +
Newey-West (Bartlett kernel, L=hold−1)** on the full population. Wired into `clean_harness.py` PASS 2 as
three columns: DE-OVERLAP | FULL-POP(cluster) | FULL-POP(NW). Re-read everything below through that lens.
Full story + all results: memory `project_deoverlap_signflip_newey_west` (the owning thread).

## NW RE-AUDIT RESULTS (2026-06-06) — the book is mapped
- **RSI (the load-bearing one): re-validated REAL under NW.** `rsi_oversold(<30)` NW +0.079R t6.6 nonbull /
  +0.080 t10.5 all (de-overlap had falsely read it −0.066 t−3.2). COVID-fragile (only neg year = 2020).
  Moderate oversold reverts; rsi<20 extreme is a knife (−0.156 t−4.0 nonbull).
- **The dislocation factor is BROAD and SLOW.** Whole slow-below family positive under NW both regimes
  (below_sma200 +0.053 t9.4, far_below_sma50 +0.069 t9.8 nonbull) — the cloud is just its visible tip.
  Slow-MA version is all-regime year-stable (+11/−0 incl COVID), beats COVID-fragile RSI. Monetizes
  (nonbull +0.06R lift post-cost) but is the SAME factor as the cloud (redundant, not new coverage).
- **TIMESCALE is the discriminant.** Slow/smoothed/persistent dislocation = alpha; fast/sharp (stoch, cci,
  BB-break, gap-down) = bull-beta that knifes in nonbull. Confidence store must separate by timescale.
- **PSAR/ADX: re-confirmed negative-for-LONG, rigorously** (NW *more* negative). ADX(21)-nonbull was a real
  de-overlap false-negative but the incremental + depth-control tests proved it redundant with dislocation
  and NOT an amplifier (it *destroys* the oversold edge within fixed depth). No standalone long edge.
- **TREND FAMILY = year-stable SHORT-selector, NOT dead** (`feedback_trend_family_not_dead` — Brand's
  correction, substantiated). Negative-long ⇒ short leg of the mean-reversion factor. adx_uptrend short
  +0.102R t7.0 nonbull (+11/−0 yr); above_sma200/golden_cross/rsi_strong all +11/−0. RELATIVE + nonbull-only;
  not shortable outright (drift). Only persistent-state trend signals translate (breakout EVENTS don't).

## NEXT DOOR — market-neutral long-short prototype
Long dislocation (below_cloud/below_sma200) + short trend-extension (above_sma200/adx_uptrend), dollar-neutral,
nonbull-gated. Up-drift cancels in the pair → harvest the two alphas. Needs a REAL paired-portfolio backtest
(leg overlap, sizing, turnover, actual borrow), not two single-leg numbers added. First deployable-product
candidate of the teardown. (The original "NEXT ACTION — RSI" below is DONE; kept for method context.)

## The mission
Going through Gordon's ~41 indicators **one at a time** to decide, for each, whether it carries
a real tradeable edge, is redundant, or can be removed — and to build a **factor-based confidence
store** (edge-weighted, with shrinkage) to replace the anti-selecting hand-weighted `weights.json`.

## The honest measurement method (use this for every indicator — it's the bar now)
Earlier findings were inflated by methodology. The CLEAN harness, used in all recent scripts:
- **Outcome:** ATR-scaled bracket, **2:1 runner** (TP=2·ATR14, SL=1·ATR14), entry at close, N=10/15d,
  same-bar tie = stop-first, timeout = mark-to-market in R. (Fixed ±1% brackets are rigged by the
  intrabar both-touch artifact — don't use.)
- **Universe hygiene:** vol floor `ATR/close ≥ 0.5%` (kills cash/bond-ETF grinders like BIL/JPST
  that produced a fake +1.4R/t=82 "ceiling").
- **De-overlap:** episode-start only (collapse consecutive signal runs); **symbol-clustered** paired
  stats (each symbol = one vote) — raw per-bar t-stats are massively inflated by overlap.
- **THE GATE (PSAR taught us this):** an edge counts only if it holds the **same sign in BOTH time
  halves** (2016-20 vs 2021-26). Plus a **cost check** (5/10/20 bps round-trip → R via ATR%).
Reusable templates in `research/indicator_screen/`: `adx_param_sweep_clean.py` (param sweep),
`psar_confirmation.py` (conditional/interaction), `psar_adx_gate.py` (gating), `psar_trailing_test.py`
(exit rules), `signal_independence*.py` (correlation/factor structure).

## What's settled (all in auto-memory — MEMORY.md loads the index)
- **Indicator-based daily-equity SELECTION is closed** ([[project_why_believed_synthesis]],
  [[project_indicator_edge_screen]]): trend/breakout family robustly anti-predicts (daily returns
  mean-revert). 4 root mechanisms.
- **~41 indicators = ~5 independent factors** ([[project_signal_independence]]): one giant
  20-signal price-position/momentum cluster (the no-edge one) + ADX, volatility, volume, gap, candles.
  Diversification ceiling √5≈2.2×, NOT a linear sum of lifts. Confidence store must be FACTOR-based.
- **Pruning needs EDGE not correlation** ([[project_pruning_edge_not_correlation]]): a signal can be
  value-redundant yet edge-orthogonal. Decide removal by incremental edge, not the correlation matrix.
- **ADX: fully worked, weak.** Real config = bull/period-21/ADX>25/di-off ≈ +0.08R but FAILS the
  time-split (different config wins each era = regime-luck). No deployable standalone edge.
- **PSAR: fully closed.** Tested standalone/redundancy/confirmation/ADX-gate/trailing-exit — all
  negative, mechanistically understood (built for sustained-futures-trend position-stops, mismatched
  to mean-reverting daily-equity 10-day swings). Stays weight 0.0; don't delete code.
- **Exit/geometry is the real lever:** the 2:1 ATR runner roughly DOUBLES expectancy over 1:1 on
  RANDOM entries; nonbull + longer hold is the hot regime. Edge lives in structure, not entry selection.

## NEXT ACTION — RSI (the load-bearing one)
RSI is the **representative of the 20-signal price-position cluster** → validating RSI ≈ validating
the whole dominant factor. And there's an **open yellow flag**: under the clean method, `rsi<30`
(nonbull) came out **NEGATIVE (−0.029R, t−1.3)** — vs the earlier `rsi_oversold` "+0.08R, t=9 winner"
([[project_rsi_oversold_bracket_edge]]) which was measured per-bar with NO vol-floor/de-overlap/clustering.
**So our one "verified" edge is suspect and must be re-validated clean.**

Do for RSI:
1. **Re-validate `rsi_oversold(<30)` on the clean harness** (vol floor + episode-start + symbol-cluster
   + TIME-SPLIT sign-stability + costs), all regimes. Does the edge survive, or was it the same
   inflation that faked the ADX ceiling? This is the linchpin — everything downstream assumes it's real.
2. **Sweep RSI parameters** like we did ADX: period (7/14/21/28), oversold threshold (20/25/30/35),
   overbought, hold, regime. Find its true ceiling on the clean harness. (Use `adx_param_sweep_clean.py`
   as the template.)
3. If a config survives the time-split + costs → it's the **first real entry in the factor store**
   (the mean-reversion/oversold factor). If it flips like PSAR → huge to know before building anything.

## Guardrails / state
- **Process safety:** the daily `-u`→`-p`→`--evaluate` cron chain runs (it fired mid-session today).
  ALWAYS `pgrep -af "main.py"` + try a read-only DuckDB connect before launching heavy scripts; the
  watcher-wait pattern (`while kill -0 <PID>; do sleep 30; done`, run_in_background) works well.
- **Nothing committed this session.** All new files are untracked research scripts in
  `research/indicator_screen/` + this handoff. Per git policy, don't commit without Brand's OK.
- **Score-backfill cron still PAUSED** (`.score_backfill_pause` present). Live scorer UNTOUCHED.
- 4-vCPU/8GB box — keep backtests serialized, never concurrent with `-p`/`-u`.
