# BH FTMO — MACD Filter v1 (Phase 0+1 Complete)

**Status:** Validated cohort-delta filter for mean-reversion strategies. Walk-forward stable on both BB v1 and Stoch v1 hosts. **Optional, applied at FTMO sizing time — not a hard production rule.** Deploy/skip decision is deferred until concurrent-risk sizing is the binding constraint.

**Date locked:** 2026-05-01

## Role

MACD does **not** function as a standalone trigger for mean-reversion at fixed 1%/1% RR (Phase 0 trigger sweep, 2,400 cells, mean WR 50.18% — symmetric noise around 50%). It functions as a **state-based filter** on existing reversion strategies (BB v1, Stoch v1) where its information improves trade quality.

This is the role described in `feedback_signal_role_by_solo_edge.md`: weak solo edge + positive cohort delta = filter, not strategy.

The host strategies (BB v1, Stoch v1) are valid standalone. The filter is a tool to apply *if and when* concurrent risk becomes the binding sizing constraint at FTMO deployment.

## Filter Spec (Optional, Sizing-Time)

**Headline filter:** `macd_below_zero_for_5_bars` at MACD(12, 26, 9), with direction mirror for shorts.

| Filter form (long-direction) | MACD params | Mirror for shorts | Where applied |
|---|---|---|---|
| `macd[i-4..i]` all < 0 | fast=12, slow=26, signal=9 | `macd[i-4..i]` all > 0 | BB v1 long trades, Stoch v1 long trades |
|  |  |  | (mirror for BB v1 short / Stoch v1 short trades) |

**Applied at the entry bar of the host strategy's trigger.** Only trades where the filter passes are kept. The filter does not change entry, exit, or RR logic of the host — only the trade-selection set.

### Strategic interpretation

For mean-reversion strategies, "MACD has been below zero for 5 H4 bars" = "the established trend has been DOWN" = "the move I'm trying to fade with my long entry has been a real, sustained move, not noise." This is a high-quality reversion setup. The mirror applies for shorts: "MACD has been above zero for 5 bars before my short entry" = established uptrend ready to fade.

## The Tradeoff: Filter On vs Off

The filter cuts trade count by ~50% in exchange for a +0.05 R per-trade lift and ~+3pp WR. Whether that's a good trade depends on the binding constraint:

| Optimizing for | Filter on or off? | Why |
|---|---|---|
| Total return at fixed sizing | **OFF** | Filter loses 30–40% of cumulative R because volume drops more than per-trade quality lifts |
| Per-trade efficiency / Sharpe | **ON** | +0.05 R on +0.21 R baseline is ~25% per-trade improvement |
| Spread cost in deployment | **ON** | Half the trades = ~half the spread paid |
| FTMO sizing (concurrent risk binding) | **ON, probably** | See sizing math below |

### Why FTMO sizing leans toward filter-on

Under FTMO rules, daily DD (~4%) caps how much risk you can put on simultaneously. With more max simultaneous positions, you have to size each trade smaller to stay inside the daily-DD budget. The filter cuts max simultaneous positions by 30-40%, which raises per-trade sizing room proportionally.

Worst-case concurrent-risk model:

| Host | Max simultaneous (unfiltered) | Max simultaneous (filtered) | Sizing headroom |
|---|---|---|---|
| BB v1 | 18 | 11 | 1.6× |
| Stoch v1 | 40 | 26 | 1.5× |

Multiplying through:

```
Stoch v1 test half:
  Unfiltered: 2125 trades × +0.135 R × 1.0× sizing ≈ +287 R-equivalent
  Filtered:   1022 trades × +0.197 R × 1.5× sizing ≈ +302 R-equivalent
```

Under worst-case-concurrent assumptions, the filter roughly breaks even on absolute return while dropping max DD and improving per-trade quality. Under realistic concurrent-correlation assumptions (positions aren't perfectly correlated), the filter probably wins outright.

### One mark against the filter

Filter-on increases max consecutive losses on both hosts in train (BB 13→24, Stoch 21→24). Trade selection thins the ledger and clusters surviving trades in time, so loss streaks lengthen even as WR improves. Sizing should account for this — equity curves with the filter applied may be choppier despite the higher per-trade R.

## Decision Logic

**Production deploy answer is deferred until FTMO sizing simulation.** When the multi-indicator portfolio is laid against actual FTMO 2-Step Swing 10k rules:

1. Run pass-rate simulation with filter OFF.
2. Run same simulation with filter ON.
3. Compare: pass rate, profit-target-hit rate, daily-DD-breach rate, max DD curves.
4. Whichever variant gives the better risk-adjusted pass rate gets deployed.

The filter is a tool ready to be deployed; whether it should be deployed is a question this spec deliberately doesn't answer.

## Cohort-Delta Evidence

In-sample (single pass, full history):

| Host | Filter pass n | dAvgR | dWR |
|---|---|---|---|
| BB v1 (2,206 trades) | 780 | +0.116 R | +5.2pp |
| Stoch v1 (7,082 trades) | 2,613 | +0.080 R | +4.0pp |

Walk-forward 70/30 by entry timestamp:

| Host | Train pass n | Train dR | Test pass n | Test dR | Stable? |
|---|---|---|---|---|---|
| BB v1 | 521 | +0.060 | 259 | **+0.093** | ✅ |
| Stoch v1 | 1,763 | +0.070 | 850 | **+0.116** | ✅ |

**Test half outperforms train on both hosts** — the desirable walk-forward shape (out-of-sample magnitude ≥ in-sample, suggesting the filter isn't curve-fit).

## Robustness Across MACD Parameter Choices

The filter holds across all three MACD parameter combos tested:

| MACD params | BB tr dR | BB te dR | Stoch tr dR | Stoch te dR |
|-------------|----------|----------|-------------|-------------|
| (12, 26, 9) classic | +0.060 | +0.093 | +0.070 | +0.116 |
| (24, 52, 9) slow    | +0.095 | +0.006 | +0.039 | +0.060 |
| (6, 13, 5)  fast    | +0.011 | +0.133 | +0.075 | +0.087 |

(12, 26, 9) is selected for the spec because magnitudes are most consistent across hosts and walk-forward halves.

## Other Walk-Forward Stable Filters (Documented for Future Use)

Beyond the headline filter, two other filter forms are walk-forward stable on both hosts:

| Filter | Best params | BB tr/te dR | Stoch tr/te dR | Notes |
|---|---|---|---|---|
| `macd_above_signal` | (6, 13, 5) | +0.102 / +0.107 | +0.073 / +0.040 | Short-term momentum agreement |
| `hist_rising_3` | (12, 26, 9) | +0.041 / +0.021 | +0.071 / +0.066 | Momentum is accelerating in trade direction |
| `macd_below_zero` (no for_5) | (12, 26, 9) | +0.058 / +0.042 | +0.045 / +0.068 | Looser version of headline filter |

`macd_below_zero_for_5` was selected over these because its magnitude is largest and most consistent across hosts/params, and its strategic interpretation ("established opposite trend") is cleaner than the others.

## Anti-Edge Filters (Walk-Forward Stable HARMS — Do Not Use)

These filters consistently *hurt* both hosts across train and test:

| Filter | Best params | BB tr/te dR | Stoch tr/te dR | Verdict |
|---|---|---|---|---|
| `macd_above_zero_for_5` | (12, 26, 9) | -0.069 / -0.065 | -0.039 / -0.082 | **DO NOT USE** |
| `macd_above_zero` | (12, 26, 9) | -0.045 / -0.042 | -0.036 / -0.068 | **DO NOT USE** |
| `hist_falling_3` | (24, 52, 9) | +0.015 / -0.055 | -0.048 / -0.069 | Mixed but mostly negative |

The "trade WITH established trend" intuition is the wrong instinct for mean-reversion strategies. Established trend in your direction means you're catching extension, not reversion.

## Filter Forms Tested but UNSTABLE (Mixed Walk-Forward)

| Filter | Notes |
|---|---|
| MACD(12,26,9) `macd_above_signal` (classic textbook) | Flips sign between train and test on both hosts. The default-MACD signal-cross filter is **not** reliable. |
| `hist_rising_2` | Stable on Stoch, flips on BB. Less robust than `hist_rising_3`. |
| `macd_below_signal` | Mostly flips. Not reliable. |

The instability of the textbook MACD(12,26,9) signal-cross filter is itself a useful finding — it's the first thing most traders would reach for, and it doesn't hold up to walk-forward.

## Methodology

The same Phase 0/1 methodology used for BB v1 and Stoch v1 triggers, adapted for state-based filters:

### Phase 0 — Cohort-delta in-sample

For each (host, MACD params, filter form):
1. Generate the host's trade ledger from its production cells.
2. For each trade, evaluate the filter state at the entry bar.
3. Split trades into PASS (filter aligned with direction) and FAIL.
4. Compare avg R and decisive WR across cohorts. Compute delta.

### Phase 1 — Walk-forward cohort delta

Same as Phase 0, but split each host's ledger 70/30 chronologically by entry timestamp first. Compute cohort delta on each half independently. Filter is "walk-forward stable" if the sign of dAvgR is preserved across halves.

### What's intentionally not here

- **Phase 2 spread-aware re-test:** the filter operates by removing trades from the host's ledger, so the spread cost behavior is inherited from the host's Phase 2 work. There's no new spread question for the filter itself.
- **Standalone trigger sweeps for MACD:** Phase 0 trigger sweep (2,400 cells, mean WR 50.18%) showed no solo edge. Re-testing at different RR shapes was deliberately deferred — the filter role is more valuable.

## Reproducibility

Three scripts at `research/macd_phase0_v1/`:

| Script | Purpose |
|---|---|
| `sweep_macd_triggers.py` | Phase 0 standalone-trigger sweep (the wash result that established MACD's role isn't standalone). |
| `macd_filter_cohort_test.py` | In-sample cohort-delta test on BB v1 and Stoch v1 hosts. |
| `macd_filter_walkforward.py` | Walk-forward 70/30 cohort delta — the validation behind this spec. |

To regenerate:

```bash
./run.sh python research/macd_phase0_v1/sweep_macd_triggers.py
./run.sh python research/macd_phase0_v1/macd_filter_cohort_test.py
./run.sh python research/macd_phase0_v1/macd_filter_walkforward.py
```

## Next Steps

1. **Cross-indicator portfolio assembly** — combine BB v1 cells + Stoch v1 cells (and any future indicator's cells) into one chronological book. Walk-forward at portfolio level. Run with filter OFF as the baseline.
2. **FTMO sizing simulation with filter A/B** — once the multi-indicator portfolio is locked, layer the FTMO 2-Step Swing 10k rules and run pass-rate simulation twice: once with filter off, once with filter on. The variant with better risk-adjusted pass rate gets deployed. This is the binding test for whether the filter's tradeoff (50% trade count for +3pp WR + 35% concurrent-position reduction) is worth it.
3. **Optionally**: scan finer-grained variants of "established opposite trend" — e.g. `for_3`, `for_7`, `for_10`, threshold-conditioned (`MACD < -X for N bars`). Currently `for_5` is the only window tested; the strategic story doesn't pin a specific number. Useful only if the FTMO sizing simulation in step 2 shows the filter is on a knife edge.
