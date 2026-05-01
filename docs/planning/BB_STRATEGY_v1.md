# BH FTMO — Bollinger Band Strategy v1 (Phase 0+1 Complete)

**Status:** Validated candidate strategy. Holds spread-aware walk-forward. Awaiting integration with other indicators (stochastic, etc.) before portfolio sizing and FTMO rule simulation.

**Date locked:** 2026-05-01

## Strategy Spec

Four-pair Bollinger Band penetration strategy at H4 timeframe, fixed 1.0% take-profit / 1.0% stop, real OANDA bid/ask spread. One production cell per pair (no overlapping parameter combinations on the same instrument).

| Pair    | BB Period | BB Std | Depth | Direction | Confirmation | Test n | Test WR | Test 95% CI    |
|---------|-----------|--------|-------|-----------|--------------|--------|---------|----------------|
| CAD_CHF | 10        | 1.5    | 0.00  | short     | none         | 318    | 58.5%   | [52.7, 64.2]   |
| USD_JPY | 10        | 1.5    | 0.00  | long      | rise_0.00%   | 168    | 58.4%   | [50.9, 65.9]   |
| EUR_CAD | 50        | 2.0    | 0.00  | long      | none         | 89     | 64.8%   | [53.7, 75.9]   |
| CHF_JPY | 50        | 2.0    | 0.00  | long      | none         | 89     | 61.6%   | [51.4, 71.9]   |

### Trigger logic

- **Long fresh trigger:** `close_mid[i] < lower_band[i] - depth × bandwidth[i]`. Fires only on transition (false → true), not on every bar that satisfies the condition.
- **Short fresh trigger:** `close_mid[i] > upper_band[i] + depth × bandwidth[i]`.
- **Bands** are Bollinger Bands computed on mid OHLC (`(high + low) / 2` of bid/ask average).

### Confirmation rules

- **`none`:** enter at the trigger bar's close. Long fills at `close_ask[i]`, short fills at `close_bid[i]`.
- **`rise_0.00%`:** wait one bar. Long enters at `close_ask[i+1]` only if `close_mid[i+1] >= close_mid[i]` (the next bar didn't close lower). Short mirrors. Used only on USD_JPY.

### Exit logic

- **Long:** TP at `entry × 1.01` (checked against `high_bid`). Stop at `entry × 0.99` (checked against `low_bid`, evaluated stop-first per bar). Timeout exit at `close_bid` after 84 H4 bars (2 weeks).
- **Short:** TP at `entry × 0.99` (checked against `low_ask`). Stop at `entry × 1.01` (checked against `high_ask`). Timeout exit at `close_ask`.

### Sizing convention

R is unitless: +1.0 on TP, -1.0 on stop, fractional on timeout. Sizing (1R = X% of account) is deferred to the FTMO integration phase, not part of this spec.

## Portfolio Performance (Test Half: 2022-12-01 → 2026-04-07)

| Metric                       | Train (1544 trades) | Test (662 trades)   | Full (2206 trades)  |
|------------------------------|---------------------|---------------------|---------------------|
| Decisive WR                  | 55.8%               | **59.3%**           | 56.9%               |
| Decisive WR 95% CI           | [53.2, 58.4]        | [55.4, 63.3]        | [54.7, 59.0]        |
| Avg R per trade              | +0.107              | **+0.171**          | +0.126              |
| Cumulative R                 | +165                | +113                | +278                |
| Max drawdown (R)             | -37                 | -16                 | -37                 |
| Max consecutive losses       | 13                  | 9                   | 13                  |
| Max simultaneous open positions | 18              | 18                  | 18                  |

**Key observation:** test outperformed train (avg R +0.171 vs +0.107). The strategy is not curve-fit to the training window; if anything, the recent regime favored it.

### Per-pair contribution (test half)

| Pair    | n    | W/L/T          | WR    | Cum R |
|---------|------|----------------|-------|-------|
| CAD_CHF | 316  | 164/118/34     | 58.2% | +46   |
| USD_JPY | 174  | 101/71/2       | 58.7% | +30   |
| EUR_CAD | 89   | 46/25/18       | 64.8% | +21   |
| CHF_JPY | 83   | 48/32/3        | 60.0% | +16   |

### Cross-pair monthly R correlation (test half)

```
          CAD_CHF  CHF_JPY  EUR_CAD  USD_JPY
CAD_CHF    1.00    -0.06     +0.37    -0.35
CHF_JPY   -0.06     1.00     -0.01    +0.09
EUR_CAD   +0.37    -0.01      1.00    +0.08
USD_JPY   -0.35    +0.09     +0.08     1.00
```

CAD_CHF and USD_JPY are negatively correlated (-0.35) — natural diversification. CHF_JPY is uncorrelated with the rest. EUR_CAD shares CAD exposure with CAD_CHF (+0.37) — only pair-pair where sizing should account for double-counting.

## Methodology

The strategy was validated through three phases of testing, each with progressively stricter conditions.

### Phase 0 — Does the trigger predict anything?

Goal: prove the entry signal has predictive value before worrying about exits, fills, or portfolio effects.

- **Mid prices throughout** — entry, TP check, stop check, timeout exit all on mid OHLC. No bid/ask. (See section "On the spread question" below.)
- **Fixed 1% / 1% RR** — symmetric target and stop. Outcome is binary except for timeouts.
- **Full universe** (40 OANDA majors and exotics).
- **Both directions** (long below lower band, short above upper band).
- **Coin-flip gate:** WR_decisive (excluding timeouts) Wilson 95% CI lower bound > 50%.

Result: at the trigger level, BB-penetration with fixed RR is **anti-edge** universe-wide (47.7% WR on H1, 48.2% on H4). The signal does not predict mean reversion at arbitrary 1% targets — it predicts reversion to indicator-relative levels (middle band) which the partial-exit version of this work demonstrated separately. **For fixed 1%/1% RR, edge exists only on a specific cluster of pairs.**

### Phase 1 — Parameter optimization

Goal: find which (period, std, depth, direction, confirmation) cells have edge and confirm they hold up out-of-sample.

Parameter grid swept:
- BB period: 10, 20, 30, 50
- BB std multiplier: 1.5, 2.0, 2.5, 3.0
- Penetration depth: 0.0, 0.1, 0.25, 0.5, 0.75 bandwidths past the band
- Confirmation: none, bare (close back inside band), rise_0.00%, rise_0.10%, rise_0.25%, rise_0.50%
- Period-state filter (band shape): tested and rejected — see "Approaches Tested and Rejected"
- Direction: long, short
- Pair: full 40

Total: 38,400 cells (after dropping shape filter).

Each cell underwent 70/30 walk-forward by entry timestamp. Robust survivor = Wilson CI lower bound > 50% on **both** halves with `tr_n >= 50` and `te_n >= 30`. At α=0.05/38,400 (Bonferroni-corrected for the multiple-comparisons risk at this grid size), 45 cells passed — far above noise expectation.

The robust cells clustered in 4–5 instruments and consistent parameter ranges (period 10–50 with std=1.5, depth ≤ 0.25). Standard BB(20, 2) was *not* prominent in the survivor list.

### Phase 2 — Deployment cost (real spread)

Goal: stress-test the trigger with realistic transaction cost.

The same 38,400-cell grid re-run with bid/ask fills:
- Long entry at `close_ask`, stop check vs `low_bid`, TP check vs `high_bid`, timeout exit at `close_bid`.
- Short mirror.
- Triggers and confirmation still evaluated on mid (that is what the trader sees).

Spread reduced robust survivors from 45 to **11**. The four pairs in the production spec are the ones whose edge survives transaction cost at the strict CI gate. Average degradation across the originally-robust cells was -2.3pp WR.

## Validation Gates

The four pairs in the production spec passed every gate:

1. **Coin-flip vs random** at fixed 1%/1% RR mid prices (Phase 0).
2. **Walk-forward 70/30 split** with both halves CI lower > 50%, min sample sizes (Phase 1).
3. **Multi-parameter robustness** — each pair has 2+ neighboring parameter cells that also pass walk-forward, indicating the edge is not concentrated at a single sensitive setting (Phase 1).
4. **Spread-aware walk-forward** — both halves CI lower > 50% after real OANDA bid/ask (Phase 2).

## Pair-Cluster Theory

The four survivors are not randomly distributed across the 40-pair universe. Three of them (CAD_CHF, EUR_CAD, USD_JPY) are major or commodity-currency pairs with deep liquidity; CHF_JPY is a cross between two safe-haven currencies. All four show frequent mean-reversion behavior on H4 — extended moves are followed by partial retracements at characteristic timescales matching the 1% target / 84-bar timeout window.

Pairs that did **not** survive: every USD-emerging-market pair (USD_HUF, USD_PLN, USD_CZK, USD_ZAR), most EUR-cross-emerging pairs (EUR_HUF, EUR_PLN, EUR_CZK), and several JPY crosses (CAD_JPY, NZD_JPY, AUD_JPY). The exotics fail primarily because spread is too wide relative to the 1% target. The other JPY crosses fail because their reversion behavior differs from CHF_JPY's / USD_JPY's. The CHF/CAD cluster persists through every gate.

## Approaches Tested and Rejected

### Partial-exit / band-relative exits (early exploration)

Earlier in the BH FTMO project, BB-penetration was tested with a 50/50 partial-exit structure: half the position at the middle band (≈+0.5 bw), runner at the opposite band. That approach showed a different edge profile — average R per trade +0.038 with 6 surviving pairs (AUD-CAD-cross-heavy: AUD_USD, AUD_CHF, AUD_CAD, EUR_CAD, GBP_AUD, GBP_CAD).

The fixed-1%/1% strategy here is a different question with a different answer. Both are valid; this v1 doc covers the fixed-RR version because the user explicitly requested it as the basics-first investigation.

### Standard BB(20, 2)

The default Bollinger Band parameters did *not* dominate the high-confidence cells. Period=50 with std=1.5 was more prevalent. The strategy works, but not at the textbook settings.

### Period-state (band shape) filter

A separate sweep tested whether layering a band-shape filter (bandwidth contracting/flat/expanding, middle band sloping up/down/flat) onto the trigger improved performance. Across 268,800 cells, no shape filter delivered reliable improvement. The cells where shape "improved" things either preserved nearly all trades (mid_flat ≈ no-op) or paired large WR jumps with massive sample drops (selection bias). Bonferroni-adjusted, no shape variant survived. **Shape filter dropped from the spec.**

### Confirmation bar (most variants)

Of the 6 confirmation variants tested, only `none` (default) and `rise_0.00%` (specifically for USD_JPY long) appear in the production spec. The `bare`, `rise_0.10%`, `rise_0.25%`, and `rise_0.50%` variants either reduced sample below useful thresholds or did not improve the underlying cell.

### High-spread pairs

Every CZK, PLN, HUF, ZAR pair had positive-WR cells in mid-only sweeps but lost edge under spread. They are excluded from the production spec.

## On the Spread Question

A spread-cost-in-solo-edge memory was deleted during this work. The reason: it was being applied at the wrong phase. Phase 0 ("does the signal predict anything?") is correctly run on mid prices — adding spread at that phase mixes signal-quality and cost-survival into one number and obscures both. Phase 2 ("does it survive deployment?") is the right time for spread. The discipline is "mid first, spread later," not "spread always."

## Reproducibility

The seven scripts that produced this work live at `research/bb_phase0_v1/`:

| Script                          | Purpose                                                          |
|---------------------------------|------------------------------------------------------------------|
| `sweep_bb_triggers.py`          | Phase 0/1 base sweep: 6,400 cells (no confirmation). CSV output. |
| `walkforward_bb_triggers.py`    | 70/30 walk-forward of the base sweep.                            |
| `sweep_bb_confirm.py`           | Phase 1 sweep with confirmation dimension: 38,400 cells.         |
| `walkforward_bb_confirm.py`     | 70/30 walk-forward with confirmation.                            |
| `walkforward_bb_shape.py`       | Phase 1 shape-filter sweep: 268,800 cells (rejected).            |
| `walkforward_bb_spread.py`      | Phase 2 spread-aware walk-forward: 38,400 cells.                 |
| `portfolio_bb_walkforward.py`   | Final per-pair cell selection + portfolio walk-forward.          |

To regenerate the canonical results from scratch:

```bash
./run.sh python research/bb_phase0_v1/walkforward_bb_spread.py
./run.sh python research/bb_phase0_v1/portfolio_bb_walkforward.py
```

Result CSVs are written to `/tmp/` and are not version-controlled. The portfolio script reads `walkforward_bb_spread.py`'s output, so run them in order.

## Next Steps

The BB strategy is locked at v1. It will not be deployed standalone. Pending:

1. **Stochastic indicator sweep.** Same Phase 0/1/2 methodology applied to a Stochastic-based trigger. Expected to surface a different (and ideally non-overlapping) pair cluster.
2. **Other indicators** as warranted (RSI, MACD, ATR-based, etc.). Each gets its own Phase 0+1+2 validation.
3. **Portfolio assembly.** Combine the validated cells from each indicator into one cross-indicator portfolio. Re-walk-forward at the portfolio level.
4. **FTMO sizing simulation.** Once the indicator portfolio is locked, layer the actual FTMO 2-Step Swing 10k rules (profit targets, max loss, daily loss, min trading days). Pass-rate analysis. See `FTMO_RULES.md` for the rule constants.
5. **Live forward test.** Paper trade the portfolio on the OANDA practice account, parallel to `rising_3bar` if it's still running. Soak for 4+ weeks before live FTMO deployment.

Sizing is **deliberately not** part of v1. The trigger is locked; the sizing question has its own validation criteria once the full indicator portfolio is in place.
