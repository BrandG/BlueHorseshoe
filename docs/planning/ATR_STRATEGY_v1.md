# BH FTMO — ATR-Conditional Momentum Strategy v1

**Status:** Validated under v2 methodology across all three entry modes. **First momentum/breakout-shaped indicator to produce production cells.** Best variant: `--entry limit` with 3 production cells (EUR_NOK long, NZD_CHF short, USD_JPY long), test mean_R +0.188, max_DD -19.4R.

**Date locked:** 2026-05-04

---

## Headline finding

ATR-conditional momentum is **the first non-mean-reversion shape to survive v2**. Donchian and SuperTrend (the two pure-trend candidates) went NULL. MACD survives but only as an inflection-event signal under limit entry. ATR survives across **all three entry modes** with productive cells, with limit being the strongest.

The mechanism: **volatility scaling**. A pure breakout (Donchian: "close above 20-bar high") triggers easily in low-volatility regimes and late in high-volatility regimes — sample bias against trend persistence. An ATR-scaled trigger ("today's close moved more than k × recent ATR" or "today's range is k× recent average AND closed in trigger direction") asks for *regime-relative* significance. In low-vol periods you need a smaller absolute move; in high-vol periods a proportionally larger one. This filters volatility noise and keeps only regime-significant moves.

This refines the working-shape spectrum:

| Shape | Examples | v2 cells | Mechanism |
|-------|----------|----------|-----------|
| Smoothed mean-reversion | BB, RSI, Stoch, CCI, SMA, EMA | many | oscillator state / distance-from-MA |
| Inflection event | MACD signal_cross (limit) | 5 | momentum direction change |
| Volatility-scaled momentum | **ATR range_expansion (limit)** | **3** | volatility-adaptive thresholds |
| Bar-pattern reversal | bullish_engulfing (mid) | 1 (thin) | bar geometry |
| Level-touch mean-reversion | pivots | 0 | no smoothing |
| Static-channel breakout | Donchian, SuperTrend | 0 | no volatility scaling |

---

## v2 Production Cells — limit entry (3 pairs, the strongest variant)

| Pair    | ATR period | k | Trigger          | Direction | Test n | Test WR | Test mean_R | Test cum_R |
|---------|------------|---|------------------|-----------|--------|---------|-------------|------------|
| EUR_NOK | 14 | 1.0 | range_expansion  | long  | 144 | 62.5% | +0.247 | +35.5 |
| NZD_CHF | 14 | 0.5 | range_expansion  | short | 360 | 61.2% | +0.210 | +75.7 |
| USD_JPY | 14 | 0.5 | range_expansion  | long  | 320 | 57.0% | +0.138 | +44.1 |

### Portfolio Performance — limit entry

| Metric | Train (n=1,922) | Test (n=824) | Full (n=2,746) |
|---|---|---|---|
| WR | 55.7% | **59.8%** | 56.9% |
| Mean R / trade | +0.109 | **+0.188** | +0.133 |
| Cumulative R | +209.3 | +155.3 | +364.6 |
| Max DD | -36.0R | -19.4R | -36.0R |
| Max consec losses | 12 | 12 | 12 |
| Max simultaneous | 18 | 15 | 18 |

Test out-performs train (+0.188 vs +0.109 mean_R; 59.8% vs 55.7% WR) — desirable shape.

## Mid-entry production (2 pairs, secondary)

| Pair    | ATR period | k | Trigger          | Direction | Test n | Test WR | Test mean_R |
|---------|------------|---|------------------|-----------|--------|---------|-------------|
| USD_CHF | 14 | 1.0 | close_breakout   | short | 263  | 57.2% | +0.139 |
| USD_JPY | 14 | 0.5 | range_expansion  | long  | 1,206 | 55.7% | +0.115 |

Mid-entry test: WR 56.0%, mean_R +0.119, cum_R +175.5, **max_DD -49.7R**, max_simul **31**.

The much higher max_simul (31 vs limit's 15) and worse max_DD (-49.7R vs -19.4R) reflect that mid-entry takes every trigger fire while limit-entry's pullback filter cuts low-quality fires. Limit also recovers correlation diversity — USD_JPY isn't paired with itself across entry modes.

## Stop-entry production (1 pair, weakest)

| Pair    | ATR period | k | Trigger          | Direction | Test n | Test WR | Test mean_R |
|---------|------------|---|------------------|-----------|--------|---------|-------------|
| GBP_JPY | 14 | 1.0 | range_expansion  | long  | 460  | 58.5% | +0.157 |

Test: WR 58.5%, mean_R +0.157, cum_R +72.4, max_DD -24.9R.

Single-cell, single-pair — useful as cross-validation that the ATR signal works across entry modes, but limit is dominant for portfolio construction.

---

## Trigger Logic

### range_expansion (4 of 6 total production cells)

For period `14`:
- **Long:** `range[i] > k × mean(range, 14)[i-1]` AND `close[i] > open[i]` (bullish bar). Fires fresh (true at i, false at i-1).
- **Short:** `range[i] > k × mean(range, 14)[i-1]` AND `close[i] < open[i]` (bearish bar). Mirror.

Where `range[i] = high[i] - low[i]` and `mean(range, 14)` is a 14-bar simple moving average of the range.

**Interpretation:** "today's range is k× recent average range AND we closed in the trigger direction." Volatility expansion + momentum confirmation.

### close_breakout (2 production cells, mid only)

For period `14`:
- **Long:** `close[i] > close[i-1] + k × ATR(14)[i-1]`. Fresh.
- **Short:** `close[i] < close[i-1] - k × ATR(14)[i-1]`. Fresh.

**Interpretation:** "today's close moved more than k volatility units beyond yesterday's." Volatility-scaled momentum without the directional close requirement.

range_expansion is structurally tighter (requires bullish/bearish close confirmation) and is what wins in the production set.

## Param Findings

- **ATR period 14 wins** in every survivor across all three modes. Period 20 didn't surface a single production cell.
- **k = 0.5 dominates** for range_expansion. k = 1.0 wins for close_breakout. Lower thresholds for range_expansion catch more signal density (range_expansion already has the directional close as a filter); higher thresholds for close_breakout (which lacks the bar-direction filter) avoid noise.
- **range_expansion dominates close_breakout** — 4 of 6 production cells. The bullish/bearish close requirement is the difference.

## Cross-mode Robustness

USD_JPY range_expansion long appears as a production cell under both mid (k=0.5, n=1,198 test, mean_R +0.113) and limit (k=0.5, n=320 test, mean_R +0.143) — the limit-entry version filters about 73% of the mid trades while raising per-trade quality. Same setup, different entry mechanic, both productive. This is the first cross-mode robust cell in the v2 sweep.

## Implications for FTMO Portfolio

### New unique pairs (from limit-entry production)

Cross-reference of the 3 ATR limit cells against the existing v2 portfolio:

- **EUR_NOK long** — likely NEW (no existing v2 indicator covers EUR_NOK).
- **NZD_CHF short** — overlaps with RSI / Stoch / CCI in some sweeps; pending full check.
- **USD_JPY long** — overlaps with BB / RSI / CCI / MACD-as-strategy. Cross-pair confluence.

(Full pair-overlap analysis pending — same flagged TODO as MACD strategy.)

### Deployment notes

- **Entry can be mid OR limit** — both productive, different trade-offs. Limit is cleaner per-trade quality and smaller DD; mid catches more trades.
- **Limit-entry production set is the recommended deployment** — best risk-adjusted shape, smallest max_DD of the three modes.
- **range_expansion uses 14-bar SMA of range, not ATR**. The trigger involves a different volatility proxy than the close_breakout cells (which use Wilder ATR). Worth keeping consistent in any reusable trigger code.

## Reproducibility

- `research/_v2_rerun/run_atr_v2.py` — full pipeline, supports `--entry={mid,limit,stop}`
- `research/_v2_rerun/atr/walkforward.csv`, `walkforward_limit.csv`, `walkforward_stop.csv` — all 960 cells per mode
- `research/_v2_rerun/atr/walkforward_spread.csv` — survivors after spread test
- `research/_v2_rerun/atr/portfolio_trades.csv` (mid), `portfolio_trades_limit.csv`, `portfolio_trades_stop.csv` — full ledgers

Param grid: 2 ATR periods × 3 k values × 2 triggers × 2 directions × 40 pairs = 960 cells per entry mode.
