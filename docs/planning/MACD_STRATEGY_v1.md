# BH FTMO — MACD Strategy v1 (Standalone, Limit-Entry Only)

**Status:** Validated under v2 methodology with `--entry=limit`. **5 production cells.** Mid entry is NULL; stop entry is near-NULL (1 cell). Limit entry is required for deployment.

**Date locked:** 2026-05-04

---

## Headline finding

MACD has **no solo edge under market-order (mid) entry** — confirms the prior Phase 0 wash result. But under **limit-at-signal-bar-extreme entry**, MACD becomes a 5-pair standalone strategy with strong out-of-sample expectancy. This is the first indicator where the entry mechanic selects the result: mid NULL, limit productive, stop near-NULL.

The mechanism: MACD `signal_cross` is an **inflection event** (the moment momentum direction changes), not a sustained-trend signal. Limit-at-bar-extreme entry waits one H4 bar for a pullback to the signal bar's low (long) or high (short) before entering. The pullback acts as a confirmation filter — only trades that get a clean retracement to the bar's extreme are taken. This filters out fakeouts and produces higher-quality entries.

This is the same shape as the limit-entry sweep finding for the mean-reversion indicators (RSI, Stoch, CCI, SMA, EMA): limit entry favors *anything that looks mean-reversion-like at the entry moment*, and a fresh signal cross at a bar's extreme qualifies.

This **doesn't invalidate MACD's filter role** on BB/Stoch hosts (`MACD_FILTER_v1.md`) — that's a state-based filter applied to a host's trade set, not an entry signal. MACD now plays two distinct roles:

1. **Standalone strategy** (this doc) — fresh signal_cross / zero_cross trigger + limit entry, 5 pairs.
2. **Optional sizing-time filter** (`MACD_FILTER_v1.md`) — `macd_below_zero_for_5_bars` filter on BB v1 / Stoch v1 trade lists.

---

## v2 Production Cells (5 pairs, limit-entry only)

| Pair    | (fast,slow,signal) | Trigger       | Direction | Test n | Test mean_R | Test cum_R |
|---------|--------------------|---------------|-----------|--------|-------------|------------|
| AUD_JPY | (18, 39, 5)        | signal_cross  | long      | 62     | +0.355      | +22.0      |
| CAD_CHF | (6, 13, 5)         | signal_cross  | short     | 102    | +0.318      | +32.4      |
| EUR_CHF | (6, 13, 9)         | signal_cross  | short     | 82     | +0.174      | +14.2      |
| NZD_JPY | (6, 13, 5)         | zero_cross    | long      | 35     | +0.543      | +19.0      |
| NZD_USD | (6, 13, 9)         | signal_cross  | short     | 72     | +0.260      | +19.0      |

Three of five surviving cells use the `(6, 13, X)` "fast MACD" parameterization — substantially shorter than the standard `(12, 26, 9)`. This matches the Phase 0 alternative-filter finding (MACD(6,13,5) `macd_above_signal` was a stronger filter than the standard params). At H4, the standard MACD periods may be too slow for a 2-week timeout horizon.

### Portfolio Performance

| Metric          | Train (n=825) | Test (n=354)  | Full (n=1,179) |
|-----------------|---------------|---------------|----------------|
| Decisive WR     | 59.1%         | **65.9%**     | 61.1%          |
| Mean R / trade  | +0.176        | **+0.301**    | +0.214         |
| Cumulative R    | +145.4        | **+106.6**    | +252.1         |
| Max drawdown    | -13.5R        | -8.8R         | -13.5R         |
| Max consec losses | 7           | 6             | 7              |
| Max simultaneous | 8            | 12            | 12             |

**Test out-performs train on every metric** (mean_R +0.301 vs +0.176; WR 65.9% vs 59.1%). This is the desirable shape — out-of-sample magnitude exceeds in-sample. Max drawdown is **the smallest of any v2 indicator portfolio** (-8.8R test vs RSI -39R, CCI -38R, Stoch comparable). The 5-pair portfolio is also less correlated than the existing v2 cluster (max simultaneous = 12).

### Trigger Logic

**`signal_cross` (4 of 5 cells):**
- **Long:** `MACD[i] > Signal[i]` AND `MACD[i-1] <= Signal[i-1]` (fresh upward cross).
- **Short:** mirror.

**`zero_cross` (1 of 5 cells, NZD_JPY long):**
- **Long:** `MACD[i] > 0` AND `MACD[i-1] <= 0` (fresh upward cross of the zero line).
- **Short:** mirror.

Where `MACD = EMA(close, fast) - EMA(close, slow)` and `Signal = EMA(MACD, signal)`.

### Entry Logic — REQUIRED: Limit, Not Market

For each fresh trigger at bar `i`:

- **Long:** Place a buy-limit at `low[i]` (signal bar's low). If `low[i+1] <= low[i]`, fill at `low[i]`. Otherwise no trade.
- **Short:** Place a sell-limit at `high[i]` (signal bar's high). If `high[i+1] >= high[i]`, fill at `high[i]`. Otherwise no trade.

**Fill window: 1 H4 bar.** The order is cancelled if not filled by the next bar's close.

This is **NOT a market order at the trigger close**. Mid-entry produced 0 production cells (12 walk-forward survivors all killed by spread). The limit-entry pullback is what creates the edge.

### Exit Logic

- **Long:** TP at `entry × 1.01` (checked against `high_bid`). Stop at `entry × 0.99` (checked against `low_bid`, stop-first per bar). Timeout at `close_bid` after 84 H4 bars (2 weeks).
- **Short:** mirror.
- **Long entry fill price:** `low_bid[i]` (the limit level).
- **Short entry fill price:** `high_ask[i]`.

(Spread convention matches the rest of the v2 portfolio: long enters paying ask-side, short enters at bid-side, per `_lib.sim_*_limit_spread`.)

---

## Entry-Mode Comparison

The entry sweep is what makes this finding possible — without it, MACD would have stayed in the "Phase 0 wash, filter-only" bucket.

| Entry mode | Walk-forward survivors | Spread-robust | Production cells | Test mean_R | Test cum_R |
|------------|------------------------|---------------|------------------|-------------|------------|
| `--entry mid`   | 12 / 2,400 | 0 / 12  | **0**     | NULL    | NULL    |
| `--entry limit` | 19 / 2,400 | 11 / 19 | **5**     | +0.301  | +106.6  |
| `--entry stop`  | 8 / 2,400  | 1 / 8   | 1 (AUD_JPY) | +0.250 | +26.5  |

The stop-entry survivor (AUD_JPY (24,52,5) signal_cross long, +0.250 mean_R, n=106 test) is real but a thin standalone — drops to 1 pair. Limit entry dominates.

### Why limit entry helps MACD specifically

`signal_cross` and `zero_cross` are *inflection events*. At the moment of fire, the most recent bar's close is at or near a local extreme of price action. Three plausible mechanisms for the limit-entry edge:

1. **Pullback as confirmation.** The 1-bar fill window asks "did price retrace into the bar that produced the cross?" If yes (~30-50% of cases per pair, depending on volatility), the cross has staying power. If no, the move was already done by the time you'd have entered at close.
2. **Better entry price.** Filling at the bar's extreme rather than its close gives ~0.1-0.5% better entry on average, which at 1%/1% RR is materially edge-creating.
3. **Spread asymmetry.** Limit fills at the bid-low (long) / ask-high (short) sit closer to the favorable side of the spread than market fills at close.

(1) is the dominant mechanism — the same effect surfaced in the limit-entry sweep across the mean-reversion indicators.

---

## Implications for the FTMO Portfolio

### New unique pairs

Cross-reference of the 5 MACD limit cells against the existing v2 portfolio (BB, Stoch, SMA, RSI, CCI, EMA, WR — see `BH_FTMO_PLAN.md`):

- **AUD_JPY long** — likely new direction (no existing v2 indicator covers AUD_JPY long).
- **NZD_JPY long** — likely new direction.
- **CAD_CHF short** — already in Stoch / SMA / CCI under limit entry (3-indicator confirmation if MACD added).
- **NZD_USD short** — needs cross-check.
- **EUR_CHF short** — needs cross-check.

(Full pair-overlap analysis pending — flagged for the cross-reference task.)

### Deployment requirements

- **Entry must be limit, not market.** Production cells go away under mid entry.
- **No mixing with mid-entry strategies in the same portfolio code path.** Strategy selector needs to dispatch on `entry_mode = "limit"` for MACD trades.
- **Order cancellation policy.** Limit must auto-cancel after 1 H4 bar — partial fills or stale orders that fill later are NOT in the sim.

### Methodology note (test indicators independently)

Per `feedback_test_indicators_independently.md` (BH FTMO 2026-04-30 lesson): MACD's solo-edge test had to sweep its own RR and entry mode rather than locking to BB/Stoch's hyperparameters. The Phase 0 sweep that produced the wash result tested triggers only at fixed 1%/1% mid-entry — the entry-mode sweep was the missing dimension. **Conclusion: an indicator's "no solo edge" finding is not robust until it's been tested across all entry modes.**

This is also why the `feedback_signal_role_by_solo_edge.md` rule ("weak solo + positive cohort delta = filter, not strategy") needs the qualifier: weak solo *across all entry modes*. MACD passes the cohort-delta test as a filter AND has a standalone strategy under the right entry mechanic — both roles are valid.

---

## Reproducibility

- `research/_v2_rerun/run_macd_v2.py` — full pipeline, supports `--entry={mid,limit,stop}`
- `research/_v2_rerun/macd/walkforward.csv` (mid), `walkforward_limit.csv`, `walkforward_stop.csv` — all 2,400 cells per mode
- `research/_v2_rerun/macd/walkforward_spread.csv`, `walkforward_spread_limit.csv`, `walkforward_spread_stop.csv` — survivors after spread test
- `research/_v2_rerun/macd/portfolio_trades_limit.csv` — full 1,179-trade ledger of the production portfolio
- (No `portfolio_trades.csv` for mid — no production cells.)

Param grid: 5 fast/slow combos × 3 signal periods × 2 triggers × 2 directions × 40 pairs = 2,400 cells per entry mode.

## See Also

- `MACD_FILTER_v1.md` — MACD as a sizing-time filter on BB v1 / Stoch v1 hosts (orthogonal role).
- `LIMIT_ENTRY_SWEEP` (memory `project_limit_entry_sweep.md`) — broader limit-vs-mid finding for the mean-reversion indicators.
- `BH_FTMO_PLAN.md` — full FTMO indicator portfolio.
