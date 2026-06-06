# Session Handoff

**Date:** June 6, 2026
**Status:** **Newey-West re-audit of the whole indicator book — complete.** De-overlap was a biased
estimator burying the slow-dislocation factor; NW resurrected it. The trend family is NOT dead — it's the
year-stable SHORT leg of the same mean-reversion factor. One factor, mapped on both sides. No code shipped
to the live system; all work is research scripts + this handoff + memory.

## What this session did (the arc, in order)
Started from the loose thread "re-audit PSAR/ADX under Newey-West" (they were declared dead under the
**biased de-overlap** method — see memory `project_deoverlap_signflip_newey_west`). It expanded into a full
re-audit of the indicator book. Every run = 2000 symbols, liquid >$25M, bracket TP2:SL1, NW Bartlett L=hold−1,
both regimes, smoke-tested at 120–150 syms first. **Process safety honored throughout** (`pgrep -af main.py`
before each run; never concurrent with `-p`/`-u`).

1. **PSAR/ADX re-audit** (`psar_adx_nw.py`): PSAR dead, rigorously (NW *more* negative, t−5.2 — nothing
   buried). ADX-as-long dead. **But** `ADX(21)>25` nonbull was a real de-overlap false-negative
   (deov −0.023 t−1.3 → NW +0.022 t+2.8), depth-monotonic in state-age.
2. **Incremental-edge test** (`adx_incremental_edge.py`): the ADX ember is REDUNDANT — its +R lives entirely
   in dislocation bars (∩below_cloud|rsi<30 = +0.127R; clean bars = −0.147R). Not a new factor.
3. **Depth-control** (`adx_depth_control.py`): ADX-persistence is NOT an amplifier — within fixed oversold
   depth it's a *destroyer* (rsi24-27 all: +0.072 noADX → −0.029 withADX). No sizing lever.
4. **Broad NW sweep** (`nw_broad_sweep.py`, ~30 signals): the big structural result. De-overlap
   systematically buried the **slow-dislocation family** — below_sma200/50 + far-below variants are all
   false-negatives, strongly positive under NW in BOTH regimes. **Timescale is the discriminant:**
   slow/persistent dislocation = regime-robust alpha; fast/sharp (stoch, cci, BB-break, gap-down, rsi<20) =
   bull-beta that knifes in nonbull. Trend family negative-for-LONG across the board.
5. **Slow-MA deploy test** (`slow_ma_deploy.py`, next-open+gap-stops+cost): the slow-MA family monetizes
   (nonbull +0.06R lift after cost, cost-robust to 20bps) and is cloud-grade year-stable (+11/−0 incl COVID),
   BUT is largely the same factor as the cloud (off-cloud edge weak). `below_sma200` = a simpler trigger for
   the same sleeve.
6. **Trend-as-short test** (`trend_short_test.py`): **Brand's call, vindicated.** The trend family is a
   year-stable RELATIVE short-selector — `adx_uptrend` (which I'd called "decisively dead") is the BEST:
   nonbull gross NW lift +0.102R t7.0, +11/−0 yr. above_sma200 +0.073 t6.6, rsi_strong +0.061 t7.2, all
   +11/−0. CAVEATS: not shortable outright (absolute net negative — drift dominates), edge is RELATIVE and
   NONBULL-only; only PERSISTENT-state trend signals translate (donchian-high breakout EVENT fails as short).

## The synthesis (one factor, symmetric)
Mean-reversion is the only edge, with two legs and one discriminant:
- **Persistent DISLOCATION reverts up** (long: below_cloud, below_sma200, rsi<30, mfi/ultosc).
- **Persistent EXTENSION reverts down** (short: above_sma200, golden_cross, rsi>50, adx_uptrend).
- **TIMESCALE gates both:** persistent *states* revert; sharp *events* (breakout, BB-break, gap) don't,
  either direction. This explains why additive `weights.json` anti-selects (it bundles knife + reversion
  + both directions into one "oversold/momentum" bucket and sizes them equally).

## ⚠️ Standing correction (DO NOT repeat my error) — `feedback_trend_family_not_dead`
Brand REJECTS framing the trend family as "dead/killed/closed." I asserted it repeatedly this session and
it was wrong each time. Our bracket tests are LONG-ONLY, 10d, mean-reverting-horizon — a negative long
result is a SHORT-selector candidate, not an obituary. Respect the practitioner base rate (these indicators
have survived far more than our narrow tests). Always state the horizon/direction limitation; report
measurements, not verdicts; let Brand steer.

## THE NEXT DOOR — market-neutral long-short prototype
The first thing all arc that points at a *deployable product* rather than a refinement. Long the dislocation
sleeve (below_cloud/below_sma200), short the trend-extension sleeve (above_sma200/adx_uptrend), dollar-neutral,
nonbull-gated. The up-drift that sinks an outright short cancels in the pair, leaving the two alphas
(~+0.06R long-lift + ~+0.08–0.12R short-lift, nonbull). **This needs a real paired-portfolio backtest** — NOT
two single-leg numbers added: overlap between legs, sizing, turnover, actual borrow on the names selected.
Bigger build than these screens — a strategy prototype. Parked for Brand's go.

## Research artifacts (this session, committed under `research/indicator_screen/`)
`psar_adx_nw`, `adx_incremental_edge`, `adx_depth_control`, `nw_broad_sweep`, `slow_ma_deploy`,
`trend_short_test` (each `.py` + `.out`). All reuse the `clean_harness.py` machinery (bracket/noov/NW). The
honest harness + findings are fully captured in memory `project_deoverlap_signflip_newey_west` (the owning
thread) and `feedback_trend_family_not_dead`.

---

## Carry-forward state (from the June 4 DeepOS session — still live, unchanged)
- **DeepOS is live on paper** (`deep_oversold` / "DeepOS", account DUE616654): RSI<30 ≥3 consecutive bars +
  $-vol ≥$25M, entry = prior close ×1.01 DAY limit, 2:1 ATR bracket, hold 10. Backtest +0.142R/t6.2.
  3 reserved paper slots (`PaperTrader._select_with_reservation`).
- **Forward-R fidelity fix is on `master`** (`ca88cfe`): per-strategy `get_hold_days`/`entry_style` so DeepOS
  evaluates at hold=10 / marketable-next-open. **Still maturing** — DeepOS journal rows land ~10 trading days
  after the first DeepOS-era frozen batch (~mid/late June). NA-3 (per-strategy `track_record.py` breakout) is
  the only remaining code piece, parked behind html_reporter WIP.
- **Equity cron runs** `run_daily_pipeline.sh` Tue–Sat 01:00 UTC (`-u→-p→journal→--evaluate→report→email`).
- **Score-backfill PAUSED** — sentinel `.score_backfill_pause` present; do NOT remove. Live scorer UNTOUCHED.
- **Factor-store direction** (the teardown's end goal): replace additive `weights.json` with a FACTOR-based,
  TIMESCALE-SEPARATED confidence store; zero fast-oscillator longs in nonbull. `factor_groups.py` has the
  group scaffold. This session gave it the empirical edge map to populate it.
- **Workflow:** Brand is solo, **no PRs** — branch+commit+push, direct merge to `master`. 4-vCPU/8GB box,
  serialize backtests, never concurrent with `-p`/`-u`.

---
*Prior DeepOS handoff detail (slot reservation internals, NA-1/NA-2 Codex artifacts) recoverable from git
history at commit `737c144` / `ca88cfe` if needed.*
