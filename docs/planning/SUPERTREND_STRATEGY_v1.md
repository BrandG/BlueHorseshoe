# BH FTMO — SuperTrend Strategy v1 (NULL RESULT)

**Status:** NULL — zero production cells survive. Tested 2026-05-04 under v2 methodology.

**Outcome:** Second trend-following indicator to fail entirely (Donchian was first).

---

## Result summary

- **Cells tested:** 1,280 (40 pairs × 4 ATR periods × 4 multipliers × 2 directions)
- **Mid walk-forward survivors:** 3
- **Spread-robust survivors:** 0
- **Production cells:** 0

## Trigger logic tested

- SuperTrend(period, multiplier) on mid OHLC.
- Long fresh: direction[i] == +1 AND direction[i-1] == -1 (flip up).
- Short fresh: direction[i] == -1 AND direction[i-1] == +1 (flip down).
- Same exits as v2 family: fixed 1.0% TP, 1.0% stop, 84-bar (2-week) timeout.

## Param grid

- Period: [7, 10, 14, 21]
- Multiplier: [1.5, 2.0, 2.5, 3.0]

## Mid walk-forward survivors (3)

| Pair    | Period | Multiplier | Direction | Train n | Train CI low | Test n | Test CI low |
|---------|--------|------------|-----------|---------|--------------|--------|-------------|
| USD_CHF | 7      | 2.0        | short     | 251     | +0.005       | 108    | +0.079      |
| USD_CHF | 21     | 1.5        | short     | 348     | +0.002       | 150    | +0.008      |
| CHF_JPY | 10     | 1.5        | long      | 346     | +0.022       | 149    | +0.025      |

All 3 had train CI lower bound just barely above zero — fragile mid-only edges.

## Why all 3 died at spread

After applying real bid/ask spread, train-half CI lower bound flipped negative for every survivor:

| Pair    | Period | Mult | Dir | Mid train CI low | Spread train CI low |
|---------|--------|------|-----|------------------|---------------------|
| USD_CHF | 7      | 2.0  | S   | +0.005           | **-0.022**          |
| USD_CHF | 21     | 1.5  | S   | +0.002           | **-0.023**          |
| CHF_JPY | 10     | 1.5  | L   | +0.022           | **-0.032**          |

Test halves still had positive CI lower bounds, but the v2 gate requires **both** halves positive. Train-half CI failure rules them out.

## Conclusion

SuperTrend's flip-event signal cannot extend far enough to consistently hit a 1% TP after paying spread, on H4 forex. Same lesson as Donchian: **trend-following indicators don't survive in this universe at fixed 1%/1% RR**.

Two trend signals tested, two null results. Mean-reversion remains the only working shape:

| Indicator    | Shape           | v2 production cells |
|--------------|-----------------|---------------------|
| BB           | mean-reversion  | 5                   |
| Stochastic   | mean-reversion  | 4                   |
| SMA-band     | mean-reversion  | 3                   |
| EMA-band     | mean-reversion  | 4                   |
| RSI          | mean-reversion  | 3                   |
| CCI          | mean-reversion  | 5                   |
| **Donchian** | **breakout**    | **0** (null)        |
| **SuperTrend** | **trend-flip** | **0** (null)        |

## Stop-buy entry mode (2026-05-04)

After Donchian also went NULL under `--entry limit`, a stop-buy entry mode was added to rule out "wrong entry mechanic for breakouts." Stop-buy places the order *above* the signal bar's high (mirror for shorts), filling only on continuation past the signal extreme — the entry shape that's structurally idiomatic for trend-following.

| Entry mode | Walk-forward survivors |
|------------|------------------------|
| `--entry mid`   | 3 / 1,280 (all killed by spread) |
| `--entry limit` | 0 / 1,280 |
| `--entry stop`  | 0 / 1,280 |

NULL on stop too. Combined with Donchian's same outcome, the failure is the trend-following shape × 1%/1% RR × H4 forex combination — not the entry mechanic.

## Reproducibility

- `research/_v2_rerun/run_supertrend_v2.py` — full pipeline, supports `--entry={mid,limit,stop}`
- `research/_v2_rerun/supertrend/walkforward.csv` — all 1,280 cells (mid)
- `research/_v2_rerun/supertrend/walkforward_spread.csv` — 3 mid survivors after spread test
- `research/_v2_rerun/supertrend/walkforward_limit.csv`, `walkforward_stop.csv` — both NULL
