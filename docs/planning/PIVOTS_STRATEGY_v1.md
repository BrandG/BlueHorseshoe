# BH FTMO — Pivots Strategy v1 (NULL RESULT)

**Status:** Tested under v2 methodology across all three entry modes (`mid`, `limit`, `stop`). **Zero production cells survive in any mode.** Classic NY-daily pivot levels do not produce a standalone trigger edge in this H4 forex universe at 1%/1% RR.

**Date locked:** 2026-05-04

---

## Headline finding

Pivots are mean-reversion-shaped on paper (fade S/R levels), so the prior was that they'd behave like RSI / Stoch / CCI / SMA / EMA — productive under limit entry. They didn't. Across all three entry modes, only one cell per mode (mid: CAD_CHF r1 short; limit: EUR_CAD s1 long) cleared the walk-forward expectancy gate, and those cells had **train CI lower bounds of 0.009 and 0.0001** — gate-skating margins. Both were killed by the spread test.

**Spread cost is not the only issue — there's barely any edge before spread.** The walk-forward survival rate (1/480 cells in mid and limit, 0/480 in stop) is the lowest of any indicator tested: an order of magnitude below the working mean-reversion indicators. The signal is mostly noise.

## Why pivots fail (interpretation)

Three plausible reasons:

1. **NY-day session mismatch.** Pivots are computed from prior NY-trading-day OHLC and recomputed at NY rollover (≈22:00 UTC). H4 forex bars cross all three trading sessions (Asia / London / NY). A "fresh touch of S1" during the Asian session is reacting to a level that was last refreshed by NY traders 8 hours earlier and won't be refreshed again for another 16 hours. Half the day, the level is stale information.

2. **Six static levels are too coarse.** Real pivot traders use confluence — pivot at the same price as a moving average, a trendline, or a Fibonacci level. On their own, S1/S2/S3/R1/R2/R3 are six round-ish horizontal lines that price routinely punches through without bouncing. The 1%/1% RR doesn't have room to wait for a deeper level to provide more meaningful support.

3. **The "fresh touch" definition is too noisy.** `low[i] <= S1[i] AND low[i-1] > S1[i-1]` fires on any wick that punches through, including continuation breaks (where price keeps falling). The optional close-rejection filter (`reject=True`: `close[i] > S1[i]`) helps slightly — half of the surviving cells used it — but doesn't lift the signal above noise.

The other working mean-reversion indicators (RSI, Stoch, CCI) all have *internal smoothing* (multi-bar averages, oscillator state), which filters out wick noise. Pivots are pure horizontal levels with no smoothing.

## Result summary

| Entry mode | Walk-forward cells | Walk-forward survivors | Spread-robust | Production cells |
|------------|--------------------|------------------------|---------------|------------------|
| `--entry mid`   | 480 | 1 | 0 | **0** (NULL) |
| `--entry limit` | 480 | 1 | 0 | **0** (NULL) |
| `--entry stop`  | 480 | 0 | 0 | **0** (NULL) |

### Survivors that died at spread

| Mode  | Pair    | Level | Reject | Direction | Train CI low | Test CI low |
|-------|---------|-------|--------|-----------|--------------|-------------|
| mid   | CAD_CHF | r1    | False  | short     | +0.009       | +0.032      |
| limit | EUR_CAD | s1    | True   | long      | +0.0002      | +0.002      |

Train CI lower bounds at +0.009 and +0.0002 — the v2 gate threshold is `tr_ci_low_r > 0`, so these are passing by 1-2 standard errors of zero. Spread cost (~-0.03 R/trade) flipped both signs.

## Cumulative trend-vs-mean-reversion finding (updated)

| Indicator   | Shape           | v2 production cells |
|-------------|-----------------|---------------------|
| BB          | mean-reversion  | 5 |
| Stochastic  | mean-reversion  | 4 |
| SMA-band    | mean-reversion  | 3 |
| EMA-band    | mean-reversion  | 4 |
| RSI         | mean-reversion  | 3 |
| CCI         | mean-reversion  | 5 |
| MACD (limit only) | inflection-event | 5 |
| Donchian    | breakout         | **0** (null) |
| SuperTrend  | trend-flip       | **0** (null) |
| **Pivots**  | **mean-reversion (level-touch)** | **0** (null) |

Important refinement: not all "mean-reversion-shaped" indicators are productive. The working set has internal smoothing (oscillator state, moving-average distances). Pure level-touch mean-reversion (pivots) doesn't carry edge in this universe.

## Trigger Spec

For each pivot level (S1, S2, S3 for long; R1, R2, R3 for short):

- **Long fresh trigger:** `low[i] <= S_level[i]` AND `low[i-1] > S_level[i-1]`. Optional close-rejection: AND `close[i] > S_level[i]`.
- **Short fresh trigger:** `high[i] >= R_level[i]` AND `high[i-1] < R_level[i-1]`. Optional close-rejection: AND `close[i] < R_level[i]`.

Pivots from `bh_ftmo.indicators.pivots()` (classic formula: `PP = (H+L+C)/3`, `R1 = 2*PP - L`, etc.) computed from prior NY forex day's mid OHLC and reindexed per bar.

Param grid: 6 levels × 2 reject options × 40 pairs = **480 cells per entry mode**.

## Reproducibility

- `research/_v2_rerun/run_pivots_v2.py` — full pipeline, supports `--entry={mid,limit,stop}`
- `research/_v2_rerun/pivots/walkforward.csv`, `walkforward_limit.csv`, `walkforward_stop.csv`
- `research/_v2_rerun/pivots/walkforward_spread.csv`, `walkforward_spread_limit.csv` — both empty after filter

(No `portfolio_trades.csv` — no production cells.)
