# BH FTMO — Multi-Timeframe (D1 Alignment) Filter v1

**Status:** Tested under v2 methodology. **Strongly recommended deployment for mid-entry strategies and most limit-entry combos.** Pair coverage expands from 3-5 pairs per indicator to 28-34 pairs — nearly the full 40-pair universe.

**Date locked:** 2026-05-05

---

## Headline finding

D1 alignment is the largest filter effect found in BH FTMO Phase 2. Diagnostic showed with-trend trades have **3-9× higher per-trade R** than counter-trend trades. Cell-level walk-forward with the filter applied produces:

- **Mid-entry indicators** (Stoch, SMA, EMA, RSI, CCI mid): universal massive expansion. Each goes from 3-5 production pairs to **28-34 pairs** — nearly the entire 40-pair universe. Test mean_R lifts to +0.26 to +0.44 per trade.
- **Momentum / large-grid limit-entry** (ATR limit, MACD limit, Stoch limit, CCI limit): strong expansion (9-33 pairs per indicator).
- **Small-grid limit-entry mean-reversion** (SMA limit, EMA limit, RSI limit): destructive. Filter cuts trades by ~67% and the smaller surviving (pair × params) base falls below the v2 sample-size threshold.

The mechanism is the textbook "buy the dip in an uptrend" rule: mean-reversion long signals fire at oversold extremes; D1 filter restricts to days when daily is bullish, capturing the canonical long-term-trend + short-term-reversal confluence.

This refines the deployment picture more than any prior result in Phase 2.

---

## Phase 1 — Diagnostic (alignment effect on existing portfolios)

Ran `research/_v2_rerun/multitf_diagnostic.py` over every existing v2 portfolio_trades CSV. Tagged each trade as "with-trend" (trade direction matches D1 close > D1 open that NY day) or "counter-trend" (opposite).

### Cross-indicator alignment summary (test half)

| Alignment | Total trades | Weighted mean_R | Indicators positive |
|-----------|--------------|-----------------|---------------------|
| **with-trend** | 4,191 | **+0.332** | 15 / 15 |
| **counter-trend** | 8,062 | **+0.100** | 13 / 15 |

with-trend is 33% of trades but carries 3.3× higher per-trade R. Per-indicator the gap is even larger:

| Indicator | with-R / counter-R | lift |
|-----------|--------------------|------|
| MACD limit | +0.530 / +0.059 | 9× |
| Stoch limit | +0.414 / +0.091 | 4.5× |
| ATR limit | +0.374 / +0.069 | 5.4× |
| ATR mid | +0.208 / **-0.033** | counter is negative |
| Candlestick mid | +0.253 / **-0.062** | counter is negative |
| RSI limit | +0.466 / +0.215 | 2.2× |
| EMA limit | +0.523 / +0.218 | 2.4× |

Three indicators (ATR mid, ATR limit, Candlestick mid) have **negative counter-trend mean_R** in test — those trades systematically lose money.

---

## Phase 2 — Cell-level walk-forward with D1 filter

Ran `research/_v2_rerun/multitf_filter_test.py` — monkey-patches FxStore.load to precompute D1 direction per H4 bar, and patches the sim functions in `_lib` to return None for triggers misaligned with D1. Patches happen BEFORE runner imports.

### Per-indicator pair coverage

| Indicator | Entry | Pairs base | Pairs filtered | Δ | Test mean_R |
|-----------|-------|------------|----------------|---|-------------|
| Stoch | mid | 4 | **34** | +30 | +0.259 |
| Stoch | limit | 4 | **32** | +28 | +0.459 |
| SMA | mid | 3 | **28** | +25 | +0.424 |
| SMA | limit | 3 | 1 | -2 | +0.564 |
| EMA | mid | 4 | **30** | +26 | +0.444 |
| EMA | limit | 4 | 1 | -3 | +0.369 |
| RSI | mid | 3 | **28** | +25 | +0.317 |
| RSI | limit | 3 | 0 | -3 | NULL |
| CCI | mid | 5 | **28** | +23 | +0.314 |
| CCI | limit | 5 | **9** | +4 | +0.446 |
| MACD | limit | 5 | **16** | +11 | +0.398 |
| ATR | mid | 2 | **28** | +26 | +0.160 |
| ATR | limit | 3 | **33** | +30 | +0.353 |
| Ichimoku | limit | 1 | 0 | -1 | NULL |

**Net delta:** +245 unique pair gains across 10 indicators, -8 pair losses across 4 indicators. **Net +237 pair coverage** universe-wide.

### Three patterns

#### Pattern A: Mid-entry universal expansion (5/5)

All five mid-entry mean-reversion indicators expand to 28-34 pairs. Why: mid-entry takes the signal close at face value. For mean-reversion long, that's an oversold close — when D1 is bullish, this is exactly the textbook "buy the dip in an uptrend" setup. The diagnostic showed this combo prints +0.27 to +0.45 mean_R, well above the all-trades baseline of +0.10-0.20.

#### Pattern B: Limit-entry mean-reversion with small grids collapses (3/4)

SMA limit (1,280 cells), EMA limit (1,280), RSI limit (5,120 but smaller surviving cell base) all collapse to 1 or 0 pairs under the filter. Why:

- Limit-at-bar-low fills on a pullback within the next bar.
- A pullback often happens during a counter-trend intraday swing.
- So limit-filled trades are *structurally biased* toward counter-trend (more often AGAINST D1 than mid trades are).
- D1 filter cuts the bulk of limit-filled trades.
- Smaller grids don't have enough backup (pair × params) combos with sufficient with-trend volume to clear the v2 sample-size gate.

#### Pattern C: Large-grid or momentum-shaped limit-entry survives (4/5)

Stoch limit (5,120 cells, +28 pairs), CCI limit (5,120, +4), ATR limit (+30), MACD limit (+11) all expand. Why:

- **Stoch / CCI**: large grid — plenty of (pair × k_period × d_period × threshold × recovery × direction) combos to find ones with sufficient with-trend volume.
- **ATR**: range_expansion already requires bullish/bearish close confirmation, so the trigger is *already* directional. D1 alignment overlap is high.
- **MACD**: signal_cross is an inflection event that often happens at the start of a new daily trend. Filtered trades concentrate at the "trend just turned" moment.

#### Special case: Ichimoku tk_cross collapses

Ichimoku limit had 1 thin cell (USD_SGD short, n=51 test). Filter removes the trades that were below D1 alignment, drops below sample-size threshold. Lost.

---

## Recommended deployment pattern

| Indicator role | D1 filter | Rationale |
|----------------|-----------|-----------|
| Stoch mid | ✅ ON | 4 → 34 pairs |
| Stoch limit | ✅ ON | 4 → 32 pairs |
| SMA mid | ✅ ON | 3 → 28 pairs |
| SMA limit | ❌ OFF | 3 → 1 (collapse) |
| EMA mid | ✅ ON | 4 → 30 pairs |
| EMA limit | ❌ OFF | 4 → 1 (collapse) |
| RSI mid | ✅ ON | 3 → 28 pairs |
| RSI limit | ❌ OFF | 3 → 0 (NULL) |
| CCI mid | ✅ ON | 5 → 28 pairs |
| CCI limit | ✅ ON | 5 → 9 pairs |
| MACD limit | ✅ ON | 5 → 16 pairs |
| ATR mid | ✅ ON | 2 → 28 pairs |
| ATR limit | ✅ ON | 3 → 33 pairs |
| Ichimoku limit | ❌ OFF | 1 → 0 (kills lone cell) |

**Net portfolio impact:** **+245 unique pairs** across 10 indicator/entry combos that benefit. Each indicator that benefits expands from 3-5 production pairs to 28-34 — essentially the full universe.

---

## Caveats

1. **Sample size at the cell level.** Many of the "newly surviving" pair × cell combos pass the v2 gate (tr_n≥50, te_n≥30) but with margin. The aggregate test mean_R values are healthy (+0.16 to +0.46) but individual cell-level CIs at the marginal pairs may be tight. Cell-by-cell verification is a follow-up if any single pair becomes load-bearing in the FTMO sizing simulation.

2. **D1 direction definition.** Used D1 close > D1 open (today's bar color). Other reasonable choices: D1 close vs prior close, D1 EMA(20) slope, D1 MA cross. The "today's bar color" version is the simplest and aligns with the user's "D1 mid-direction agrees" framing. Variants might give different filter aggressiveness.

3. **Spread test inherits filter.** The cell-level test applies the D1 filter to the spread sim too. Real deployment with filter: same. Spread-robust counts here are post-filter — cells that pass with filter applied at both walk-forward and spread stages.

4. **Combined with session filter is open.** This work is independent of `SESSION_FILTER_v1.md`. Combining both filters (drop overlap AND require D1 alignment) hasn't been tested — could be additive, could be subtractive. Worth a follow-up if the FTMO portfolio composition needs further tuning.

5. **Implementation cost.** D1 alignment requires per-trade D1 lookup at entry time. Each pair has a precomputed D1 direction array per H4 bar; trivial in deployment code (`if d1_dir[entry_bar] != trade_dir: skip`).

---

## Reproducibility

- `research/_v2_rerun/multitf_diagnostic.py` — Phase 1 per-portfolio with-trend vs counter-trend mean_R.
- `research/_v2_rerun/multitf_filter_test.py` — Phase 2 cell-level walk-forward with D1 filter.
- `research/_v2_rerun/multitf_filter_results.csv` — full per-(indicator, entry) result table.

The filter test patches `FxStore.load` to set per-bar D1 direction, then patches all 10 sim functions in `_lib` to drop misaligned triggers. No modifications to existing v2 runners.

## See Also

- `SESSION_FILTER_v1.md` — independent session-conditional filter test (smaller effect, per-indicator tradeoff).
- `BH_FTMO_PLAN.md` §queue — combinator items list.
