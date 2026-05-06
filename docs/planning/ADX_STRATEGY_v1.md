# BH FTMO — ADX Strategy v1 (NULL — standalone AND as filter)

**Status:** Tested under v2 methodology in BOTH roles: standalone trigger and filter on Donchian/SuperTrend. **Zero production cells in either role.** ADX joins Donchian and SuperTrend in the trend-shape NULL pile.

**Date locked:** 2026-05-04

---

## Headline finding

ADX is the third trend-strength/direction indicator to fail completely:

- **Standalone (this doc, part 1):** ADX threshold-cross + DI-direction triggers — 2/960 walk-forward survivors mid (both killed by spread), 0 in limit/stop.
- **Filter on Donchian/SuperTrend (part 2):** Adding ADX>T (T ∈ {20, 25, 30}) gate to the existing Donchian/SuperTrend triggers — across **18 combinations** (2 hosts × 3 thresholds × 3 entry modes), the filter NEVER improves the survivor count over unfiltered. It strictly reduces it.

This falsifies the natural hypothesis that "ADX>25 only fire when trending" rescues the static-channel breakouts. The trend filter cuts trigger volume substantially (28–79% cut depending on threshold) but the surviving triggers don't carry enough additional edge to compensate for sample-size loss.

## Part 1 — ADX as Standalone Trigger

### Trigger families

**adx_cross:** Fresh ADX rising through threshold T, with DI dominance picking direction.
- Long: `ADX[i] > T AND ADX[i-1] <= T AND plus_di[i] > minus_di[i]`
- Short: same threshold cross AND `minus_di[i] > plus_di[i]`

**di_cross_with_adx:** Fresh DI cross with ADX above threshold (must be trending).
- Long: `plus_di crosses above minus_di AND ADX[i] > T`
- Short: mirror.

### Param grid

| Param | Values |
|-------|--------|
| period | 14, 20 |
| threshold | 20, 25, 30 |
| trigger | adx_cross, di_cross_with_adx |
| direction | long, short |
| pair | 40 |

960 cells per entry mode.

### Result

| Entry | Walk-forward survivors | Spread-robust | Production cells |
|-------|------------------------|---------------|------------------|
| `--entry mid`   | 2/960 | 0 | **0** (NULL) |
| `--entry limit` | 0/960 | 0 | **0** (NULL) |
| `--entry stop`  | 0/960 | 0 | **0** (NULL) |

The 2 mid survivors had marginal train CI bounds and were killed by the ~0.03 R/trade spread cost — the same shape as Donchian and SuperTrend.

## Part 2 — ADX as Filter on Donchian / SuperTrend

### Setup

For each Donchian / SuperTrend trigger event from the prior v2 sweeps, keep the trigger only if `ADX(14)[i] > T`. Re-run v2 walk-forward with the filter applied. Test thresholds T ∈ {20, 25, 30} across all three entry modes for both hosts.

### Result table

| Host | Entry | Unfiltered WF | ADX>20 WF | ADX>25 WF | ADX>30 WF |
|------|-------|---------------|-----------|-----------|-----------|
| Donchian   | mid   | **3**/960  | 1/960  | 1/960  | 0/960  |
| Donchian   | limit | 0/960     | 0/960  | 0/960  | 0/960  |
| Donchian   | stop  | 0/960     | 0/960  | 0/960  | 0/960  |
| SuperTrend | mid   | **3**/1,280 | 0/1,280 | 0/1,280 | 0/1,280 |
| SuperTrend | limit | 0/1,280   | 0/1,280 | 0/1,280 | 0/1,280 |
| SuperTrend | stop  | 0/1,280   | 0/1,280 | 0/1,280 | 0/1,280 |

Filter trigger-retention rates:

| Threshold | Donchian retain | SuperTrend retain |
|-----------|------------------|-------------------|
| ADX>20 | 72.0% | 57.9% |
| ADX>25 | 51.1% | 35.3% |
| ADX>30 | 33.9% | 20.6% |

### Interpretation

The hypothesis "trend-followers fail because they fire in non-trending regimes; an ADX gate fixes that" is falsifiable as: with the filter, surviving cell count should INCREASE relative to unfiltered. It doesn't. **In every combination, filtered ≤ unfiltered.** The filter is hurting, not helping.

Why? Three candidate reasons:

1. **The filter doesn't separate winning trades from losing trades.** ADX>25 captures roughly half the trigger sample (51% retention). If the filter were edge-creating, the retained half would have a higher win rate than the discarded half. Since survivor counts go DOWN, the retained set isn't materially more profitable than the original.

2. **Sample-size loss hits the v2 gate.** The gate requires `tr_n >= 50` AND `te_n >= 30`. Cutting trigger volume by 50-80% pushes many cells under those thresholds, killing them via sample-size loss alone — even if per-trade quality were unchanged.

3. **ADX is a lagging confirmation, not a regime predictor.** ADX rises *after* a trend has already been moving; by the time it's >25, the move is mature and the residual move is shrinking. So gating on "ADX>25 NOW" is closer to gating on "trend was strong recently" than "trend is about to be strong" — which is what the breakout would need.

(3) is the most plausible. The other indicators that *do* survive use indicators that lead price (oscillators in extreme zones, volatility expansion at the bar of the move) rather than confirm-after-the-fact.

## Cumulative trend-shape findings

| Indicator   | Standalone | As filter | Notes |
|-------------|------------|-----------|-------|
| Donchian    | NULL | (filter target) | static channel |
| SuperTrend  | NULL | (filter target) | flip event with ATR band |
| **ADX**     | **NULL** | **NULL** | trend-strength meter |

Three trend-shaped indicators tested, three NULL. Volatility-scaled momentum (ATR range_expansion) is the *only* non-mean-reversion shape that has surfaced production cells.

## Reproducibility

**Standalone:**
- `research/_v2_rerun/run_adx_v2.py` — full pipeline, supports `--entry={mid,limit,stop}`
- `research/_v2_rerun/adx/walkforward.csv`, `walkforward_limit.csv`, `walkforward_stop.csv`

**Filter test:**
- `research/_v2_rerun/run_adx_filter_test.py` — applies ADX>T gate to Donchian + SuperTrend triggers
- Args: `--entry={mid,limit,stop}` `--host={donchian,supertrend,both}` `--threshold {20|25|30}` (default = sweep all three)
- `research/_v2_rerun/adx_filter/{donchian,supertrend}_T{T}_walkforward{_entry}.csv`

(No portfolio CSVs — no production cells in either role.)
