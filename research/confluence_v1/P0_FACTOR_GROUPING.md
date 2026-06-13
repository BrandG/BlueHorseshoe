# P0 Factor Grouping

## Objective
Determine which deployed v2 evaluator families are orthogonal on H4 forex before any P1 confluence sweep.

## Method
Used 33 deployed cells across 17 deployed pairs. For each evaluator, selected one deployed parameter set by modal frequency; ties use existing ranked-cell order as the deterministic tiebreaker. Fire masks are side-agnostic (`long OR short`) and evaluated on closed H4 bars only, matching the trigger-bar convention in `evaluate_cell`.

## Parameter Choices
- stoch: `{"d_period": 3, "k_period": 9, "recovery": 1, "threshold": 20}` (tied modal deployed param set (1/4 cells); ranked-cell order broke tie; 4 deployed param set(s))
- bb: `{"depth": 0.0, "n_std": 2.0, "period": 50}` (modal deployed param set (2/5 cells); 4 deployed param set(s))
- macd: `{"fast": 6, "signal": 9, "slow": 13, "trigger": "signal_cross"}` (modal deployed param set (2/5 cells); 4 deployed param set(s))
- sma: `{"atr_period": 14, "k": 2.5, "period": 200}` (modal deployed param set (2/3 cells); 2 deployed param set(s))
- ema: `{"atr_period": 14, "k": 2.0, "period": 20}` (tied modal deployed param set (1/4 cells); ranked-cell order broke tie; 4 deployed param set(s))
- rsi: `{"period": 14, "recovery": 1, "threshold": 35}` (tied modal deployed param set (1/3 cells); ranked-cell order broke tie; 3 deployed param set(s))
- cci: `{"period": 14, "recovery": 1, "threshold": 100}` (tied modal deployed param set (1/5 cells); ranked-cell order broke tie; 5 deployed param set(s))
- atr: `{"atr_period": 14, "k": 0.5, "range_lookback": 14, "trigger": "range_expansion"}` (modal deployed param set (2/3 cells); 2 deployed param set(s))
- ichimoku: `{"displacement": 26, "kijun": 26, "senkou_b": 52, "tenkan": 9, "trigger": "tk_cross"}` (only deployed param set; 1 deployed param set(s))
- candle: `{"pattern": "bull_engulf", "strict": false}` (single briefing.CELLS param set; evaluator is in _EVALUATORS but not selected by deploy_predicate; 1 deployed param set(s))

## Data Coverage
- AUD_CAD: 16,248 closed H4 bars
- AUD_JPY: 16,248 closed H4 bars
- CAD_CHF: 16,248 closed H4 bars
- CAD_JPY: 16,248 closed H4 bars
- CHF_JPY: 16,250 closed H4 bars
- EUR_CAD: 16,251 closed H4 bars
- EUR_CHF: 16,251 closed H4 bars
- EUR_GBP: 16,251 closed H4 bars
- EUR_NOK: 16,252 closed H4 bars
- EUR_USD: 16,249 closed H4 bars
- GBP_CAD: 16,251 closed H4 bars
- NZD_CHF: 16,258 closed H4 bars
- NZD_JPY: 16,259 closed H4 bars
- NZD_USD: 16,258 closed H4 bars
- USD_CAD: 16,260 closed H4 bars
- USD_JPY: 16,259 closed H4 bars
- USD_SGD: 16,256 closed H4 bars

## Cluster Map
Threshold: `abs(correlation) >= 0.50`. Full matrix: `factor_grouping.csv`.
- C1 (standalone): atr
- C2 (standalone): bb
- C3 (standalone): candle
- C4 (standalone): cci
- C5 (standalone): ema
- C6 (standalone): ichimoku
- C7 (standalone): macd
- C8 (standalone): rsi
- C9 (standalone): sma
- C10 (standalone): stoch

## Verdict
45 orthogonal cross-cluster evaluator pairs found; P1 is worth running only for those cross-cluster pairs.
Evaluated all 45 evaluator pairs. 0 are redundant-by-design at the current threshold.

## Cross-Cluster Shortlist For P1
- stoch + bb
- stoch + macd
- stoch + sma
- stoch + ema
- stoch + rsi
- stoch + cci
- stoch + atr
- stoch + ichimoku
- stoch + candle
- bb + macd
- bb + sma
- bb + ema
- bb + rsi
- bb + cci
- bb + atr
- bb + ichimoku
- bb + candle
- macd + sma
- macd + ema
- macd + rsi
- macd + cci
- macd + atr
- macd + ichimoku
- macd + candle
- sma + ema
- sma + rsi
- sma + cci
- sma + atr
- sma + ichimoku
- sma + candle
- ema + rsi
- ema + cci
- ema + atr
- ema + ichimoku
- ema + candle
- rsi + cci
- rsi + atr
- rsi + ichimoku
- rsi + candle
- cci + atr
- cci + ichimoku
- cci + candle
- atr + ichimoku
- atr + candle
- ichimoku + candle

## Redundant By Design
- None

## Sanity Check
Stoch nearest neighbor: `rsi` (corr=0.300). Dislocation-family check: passed.

## Per-Pair Range Note
Wrote `factor_grouping_pair_ranges.csv` with pooled correlation plus per-pair min/max for every evaluator pair so the pooled average does not hide heterogeneity.

## Top Absolute Correlations
- bb + ema: pooled=0.379, per-pair range=[0.331, 0.437]
- stoch + rsi: pooled=0.300, per-pair range=[0.268, 0.328]
- rsi + cci: pooled=0.249, per-pair range=[0.230, 0.272]
- rsi + atr: pooled=0.233, per-pair range=[0.189, 0.264]
- stoch + cci: pooled=0.227, per-pair range=[0.206, 0.246]
- atr + candle: pooled=0.162, per-pair range=[0.148, 0.171]
- stoch + atr: pooled=0.145, per-pair range=[0.130, 0.165]
- cci + atr: pooled=0.117, per-pair range=[0.087, 0.142]
- bb + sma: pooled=0.079, per-pair range=[0.055, 0.108]
- stoch + macd: pooled=-0.075, per-pair range=[-0.091, -0.059]
- sma + ema: pooled=0.072, per-pair range=[0.048, 0.099]
- ema + rsi: pooled=-0.063, per-pair range=[-0.071, -0.056]

---

## Addendum — Strict-AND co-fire feasibility (corrected verdict, 2026-06-13)

The cluster map above is a fire-mask **correlation** pass. That answers "do triggers coincide?",
not the two questions that actually gate P1: (1) are there enough simultaneous **same-direction**
fires to test a strict-AND `BOTH` cell, and (2) do two correlated triggers carry independent
information. Fire-mask correlation conflates "independent edge" with "trigger bars rarely line
up" — two triggers from the same factor, offset 1–3 bars, show near-zero mask correlation. So the
"45 orthogonal pairs" reading **overstates** the opportunity and should not be taken as the P0
verdict.

`co_fire.py` measures the gating quantity directly: direction-aware fresh fire masks per
evaluator, then per `(forex_pair, direction, A, B)` the count of bars where both fire (≈ the
`BOTH` cell's trade count). n_floor = 40.

**Solo fresh-fire rates** (fraction of ~276k bar-observations per direction):
`atr 24.7% | stoch 10.4% | cci 7.1% | macd 6.0% | rsi 4.3% | candle 2.7% (long only) | ichimoku 2.4% | ema 2.0% | bb 2.0% | sma 1.6%`

**Findings:**
- **24 / 45 evaluator pairs are untestable under strict-AND** anywhere (too few same-direction
  co-fires in any pair/direction). Sparsity, not redundancy, is the binding constraint. Full dead
  list + counts in `co_fire_counts.csv`.
- **21 / 45 are testable, but compromised:**
  - **atr is a near pass-through** (fires 24.7% of bars); `X ∧ atr` clears the floor trivially
    (`stoch∧atr` co-fires 17,625×) but is `X` lightly thinned, not a confluence — expect
    `atr∧X ≈ X`.
  - the dislocation cluster (stoch/rsi/cci mutual) is testable but same-factor.
  - **bb+ema co-fires ~20× above independence** (both are "stretched-below" distance signals;
    also the matrix's top correlation, 0.379) — redundant, not confluence.
- The intersection **{testable} ∩ {independent info} ∩ {not-passthrough}** is small: roughly
  `macd × {stoch, rsi, cci}`, and even those are thin (best single-pair cells ~120–140 co-fires).

**Verdict:** strict-AND confluence on H4 forex is mostly infeasible or redundant. P1 is narrowed
to the macd-crossed cross-factor pairs, run with atr- and dislocation-pairs as redundancy
controls. See `docs/planning/CONFLUENCE_SWEEP_v1.md` §13 "P0 findings → revised P1 plan".

**Artifacts:** `co_fire.py`, `co_fire.out`, `co_fire_counts.csv`.
