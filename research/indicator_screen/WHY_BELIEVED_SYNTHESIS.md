# Why-believed / can-it-be-rescued — synthesis (2026-06-03)

Workflow: `research/indicator_screen/why_believed_workflow.js` (26 agents, ~1.15M tokens).
One agent per textbook signal, anchored on the measured `edge_table.csv`.
Per-indicator JSON: see workflow output (run wf_e21fa915-226).

## Verdict
Indicator-based daily-equity **selection** is a closed file. No textbook indicator picks
daily-equity longs on the 5-10d swing horizon. Converges with the prior decisive findings
(scorer anti-selects, entry-signal alpha absent, none of ~25 signals beat "just being long").

## Four root mechanisms (explain every row)
1. **Horizon mismatch** — continuation/breakout signals fire on bars that just moved up;
   daily 1-20d forward returns mean-revert. Continuation logic is at war with the horizon.
2. **Baseline already high** — edge measured vs random long; long-biased 2016-2026 drift is
   strong (bull h20 +1.33%, nonbull +2.23%). Continuation signals pick the most-extended
   name in an already-rising crowd → can only approach, never beat, baseline. above_sma200 /
   cmf_pos fire on ~the whole universe (zero selectivity).
3. **Beta/vol confound** — big nominal edges (Williams, stoch, OBV, RVOL) have t<1.2 despite
   huge n; they select high-ATR names, fat tails drag the mean, median bar does nothing.
4. **Regime is the missing variable** — oversold is bimodal: bull = falling-knife detector,
   nonbull = real capitulation that reverts only at h20 (dead zone at 5-10d house window).

## Scorecard (25)
- keep-as-filter (5): rsi_exit_oversold, stoch_oversold(<20), bb_lower_touch, hammer, gap_up(>2%)
- demote-to-zero (11): rsi_oversold, williams_oversold, cci_oversold, cci_break, bb_upper_break,
  macd_bull_cross, donchian20_break, rvol_high, above_sma200, sma50_reclaim, sma20_pullback_uptrend
- drop (9): rsi_bull(>50), roc_pos, adx_uptrend, aroonosc_up, obv_rising, cmf_pos, mfi_oversold,
  engulfing_bull, golden_cross
- Whole trend/breakout family is significantly ANTI-predictive (|t| 20-75 at n 100k-960k).

## Short list worth a real rescue experiment (all the SAME experiment:
## regime-gate to nonbull, hold ~20d, confirm dislocation/depth not beta)
1. rsi_oversold(<30) — h20/nonbull +2.11pp, t=10.1, n=26,567 (strongest cell in study)
2. gap_up(>2%) — h20/nonbull +2.54pp, t=11.98, n=31,601 (capitulation reversal)
3. rsi_exit_oversold(x30up) — h20/nonbull +2.11pp, t=6.23 (needs vol-quintile control)
4. bb_lower_touch — h20/nonbull +0.87pp, t=4.86, n=28,057
5. stoch_oversold(<20) — only nonbull h20 clean (+0.24, t=2.72)
6. hammer — lone clean SHORT-horizon cell: h3/nonbull +0.25pp, t=3.17

## Where the edge actually lives (not entry selection)
- Regime gating as RISK CONTROL — above_sma200/golden_cross only as a portfolio kill-switch
  ("suppress new longs while SPY<200d"), not stock-pickers.
- Exits / trade management (WS3) — the realized-vs-signal gap says structure, not entry.
- One narrow contrarian sleeve — nonbull, deep-dislocation, ~20d hold. Small, regime-conditional,
  orthogonal to the long-biased main book; only thing with a t-stat that survives costs.

## Decisive close
Stop trying to make trend/momentum indicators select daily-equity longs. Spend remaining
effort on exits (WS3) and on validating the nonbull/h20 deep-dislocation sleeve — start with
rsi_oversold and gap_up.
