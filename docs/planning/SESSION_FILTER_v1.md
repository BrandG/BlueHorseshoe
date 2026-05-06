# BH FTMO — Session Filter v1 (drop-overlap test)

**Status:** Tested under v2 methodology. **Per-indicator filter (apply only where it expands coverage) is the recommended pattern.** Universal "drop overlap" filter is a wash — expands net pair coverage by 6 but kills 7 specific production cells.

**Date locked:** 2026-05-05

---

## Headline finding

The conventional "trade only during the London/NY overlap" advice is **inverted** in this universe:

- Diagnostic showed Asia is the strongest session (weighted test mean_R +0.186 across all 19 indicator/entry combos in `portfolio_trades` CSVs), Overlap the weakest (+0.118).
- Cell-level walk-forward with overlap dropped: per-trade test mean_R lifts from baseline +0.10–0.20 to **+0.15–0.44** across nearly every indicator. Filtering OVERLAP trades systematically improves per-trade quality.
- BUT: pair coverage shifts. Some pairs LOSE production cells when their overlap trades are dropped (their edge was concentrated in overlap); other pairs GAIN cells.

**Net delta on unique production pairs (universal filter):** +13 gains − 7 losses = **+6 pairs**.

The filter is not a free win. It reshuffles which pairs are productive — quality up, breadth down for some indicators, up for others.

---

## Phase 1 — Diagnostic (per-session expectancy across 19 portfolios)

Ran `research/_v2_rerun/session_diagnostic.py` over every existing portfolio_trades CSV. Cross-indicator session summary (test halves only):

| Session | Total trades | Weighted mean_R | Indicators positive |
|---------|--------------|-----------------|---------------------|
| **Asia** | 8,863 | **+0.186** | 19 / 19 |
| London | 3,144 | +0.166 | 18 / 19 |
| **Overlap** | 3,432 | **+0.118** | 19 / 19 |
| NY | 2,488 | +0.183 | 17 / 19 |

Asia is highest-volume AND highest mean_R. Overlap is consistently weakest. NY is high-quality / low-volume. London is middling. The "overlap is weakest" pattern holds across smoothed mean-reversion (BB/Stoch/SMA/EMA/RSI/CCI), volatility-scaled momentum (ATR), and inflection-event (MACD signal_cross, Ichimoku tk_cross) shapes.

### Per-indicator session strengths (notable)

| Indicator | Strongest session | Notes |
|-----------|-------------------|-------|
| MACD limit | Overlap (+0.378) | the *one* indicator where overlap is best — counter-trend momentum benefits from volatility |
| EMA limit | NY (+0.474) | highest single-session/indicator combo seen |
| ATR mid | NY (+0.286) | overlap variants are flat (mean_R 0.00–0.07) |
| Most mean-reversion | Asia | consistent across BB/Stoch/SMA/RSI/CCI |
| Ichimoku tk_cross | Asia (+0.316) | 34/51 test trades in Asia |

---

## Phase 2 — Cell-level walk-forward with overlap dropped

Ran `research/_v2_rerun/session_filter_test.py` — monkey-patches `_lib.expectancy_split` to drop OVERLAP trades, then re-runs walk-forward + spread test for every working v2 indicator.

### Results

| Indicator | Entry | Pairs (base→filt) | Δ pairs | Test mean_R (filtered) |
|-----------|-------|--------------------|---------|-------------------------|
| stoch | mid | 4 → 4 | — | +0.173 |
| **stoch** | **limit** | 4 → 9 | **+5** | +0.242 |
| sma | mid | 3 → 1 | -2 | +0.266 |
| **sma** | **limit** | 3 → 5 | **+2** | +0.318 |
| **ema** | **mid** | 4 → 5 | **+1** | +0.283 |
| **ema** | **limit** | 4 → 6 | **+2** | +0.338 |
| rsi | mid | 3 → 3 | — | +0.233 |
| **rsi** | **limit** | 3 → 4 | **+1** | +0.325 |
| cci | mid | 5 → 3 | -2 | +0.184 |
| **cci** | **limit** | 5 → 7 | **+2** | +0.294 |
| macd | limit | 5 → 4 | -1 | **+0.438** |
| atr | mid | 2 → 1 | -1 | +0.147 |
| atr | limit | 3 → 3 | — | +0.180 |
| ichimoku | limit | 1 → 0 | -1 | NULL |

**Bold** = combos where the filter expanded unique-pair coverage (filter recommended).

Per-trade test mean_R is uniformly ELEVATED under the filter — every surviving cell has higher per-trade quality than its unfiltered baseline. This is the consistent quality lift; the variance is in pair count.

### Pair losses worth noting

The 7 lost production cells (under universal filter):
- **MACD limit (-1)**: one of the 5 pairs (likely overlap-concentrated — MACD overlap had test mean_R +0.378, the highest single MACD session). Dropping overlap removes a load-bearing chunk.
- **CCI mid (-2)**, **SMA mid (-2)**: the mid-entry mean-reversion variants tend to fire more often during overlap (high-volume reversal opportunities). Dropping overlap drops their volume below the v2 sample-size threshold.
- **ATR mid (-1)**: USD_CHF close_breakout short loses cells.
- **Ichimoku limit (-1)**: the lone production cell (USD_SGD tk_cross short) had 30/51 test trades in non-overlap sessions but 17/51 in overlap; dropping overlap brings it under sample-size threshold.

---

## Recommended deployment pattern: per-indicator filter

| Indicator role | Filter? | Rationale |
|----------------|---------|-----------|
| Stoch limit | ✅ ON | 4→9 pairs, +0.07 mean_R lift |
| SMA limit | ✅ ON | 3→5 pairs, +0.13 mean_R lift |
| EMA mid | ✅ ON | 4→5 pairs, +0.13 mean_R lift |
| EMA limit | ✅ ON | 4→6 pairs, +0.14 mean_R lift |
| RSI limit | ✅ ON | 3→4 pairs, +0.04 mean_R lift |
| CCI limit | ✅ ON | 5→7 pairs, +0.05 mean_R lift |
| Stoch mid | ❌ OFF | pair count unchanged; modest mean_R lift not worth complexity |
| RSI mid | ❌ OFF | pair count unchanged |
| ATR limit | ❌ OFF | pair count unchanged |
| SMA mid | ❌ OFF | filter loses 2 pairs |
| CCI mid | ❌ OFF | filter loses 2 pairs |
| ATR mid | ❌ OFF | filter loses 1 pair |
| MACD limit | ❌ OFF | filter loses 1 pair (despite huge per-trade R lift) |
| Ichimoku limit | ❌ OFF | filter kills the lone production cell |

**Net portfolio impact:** +13 unique pairs across 6 indicators (no losses).

The MACD case is interesting: filter drops 1 pair but lifts test mean_R from +0.301 to +0.438 (a +0.14 lift). For an FTMO sizing model that prioritizes per-trade quality over coverage breadth, MACD-with-filter could be the right call. Defer this decision to the FTMO sizing simulation.

## Why "drop overlap" works as a per-trade quality lift

Three plausible reasons:

1. **Overlap is dominated by directional institutional flow.** London/NY overlap is the highest-volume forex window — institutions execute, news lands, momentum runs. Mean-reversion signals fire often (price extremes are common in high-volume regimes) but the bounces don't materialize because the flow is one-directional. Result: many trades, low per-trade quality.

2. **Spread cost is highest during overlap volatility.** OANDA bid-ask widens during high-vol windows (algorithmic spread management). The 1%/1% RR at mean-reversion extremes has a tight spread budget; even a small spread widening eats meaningful edge.

3. **Asia's lower volume is range-bound.** Tokyo + Sydney desks don't drive directional moves the way London/NY do. Price wanders within prior-day extremes, mean-reversion setups print bounces. The "quiet session is the productive session" finding is the inverse of conventional retail wisdom.

## Why "drop overlap" hurts some pairs

The pairs that LOSE coverage under the filter had edge concentrated in the overlap session — likely currency pairs whose flow dynamics are most active during London/NY hours (e.g. EUR/USD, GBP/USD majors, USD majors in general). For mid-entry mean-reversion strategies, overlap is when reversal extremes most often fire AND complete cleanly. Filtering out overlap drops these productive trades along with the noise.

## Reproducibility

- `research/_v2_rerun/session_diagnostic.py` — Phase 1 per-session expectancy diagnostic.
- `research/_v2_rerun/session_filter_test.py` — Phase 2 cell-level walk-forward with overlap filter.
- `research/_v2_rerun/session_filter_results.csv` — full per-(indicator, entry) result table.

The filter test uses monkey-patching of `_lib.expectancy_split` — no modifications to existing v2 runners. The patched expectancy_split filters out OVERLAP trades from the (timestamp, R) tuple list before computing 70/30 train/test split.

## Implications for next phases

- **The per-indicator filter pattern is now an active deployment dimension.** Future indicators should be tested under both filtered and unfiltered modes, and the better variant deployed.
- **Pair-coverage rebalancing**: 6 pairs gained, 7 pairs lost. Net +6 unique pairs across the universe means a richer portfolio if combined per-indicator. Many gained pairs are overlap-quiet currency crosses (likely Asia-active pairs).
- **The MACD overlap insight is unique** — it's the only indicator where overlap is the best session. Worth keeping in mind: not every signal benefits from the filter.
- **Per-indicator filter complexity is real but bounded** — it's a single boolean per (indicator, entry) combo, deployable in code as `if cell.filter_overlap: drop_session(t, "overlap")`.

## See Also

- `research/_v2_rerun/session_diagnostic.py` — diagnostic script
- `research/_v2_rerun/session_filter_test.py` — filter test
- `BH_FTMO_PLAN.md` §queue — combinator items list
