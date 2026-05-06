# BH FTMO — Candlestick Reversal Strategy v1 (Marginal: 1 thin cell)

**Status:** Tested under v2 methodology across all three entry modes. **1 production cell** under mid entry only (USD_JPY bullish engulfing long, test mean_R +0.172). Gate-skating margins. Limit and stop entries are both NULL.

**Date locked:** 2026-05-04

---

## Headline finding

Four reversal patterns tested (hammer, shooting star, bullish engulfing, bearish engulfing) under relaxed / strict threshold variants — 320 cells per entry mode. The result is **the inverse of MACD**: candlesticks survive under MID entry only, where MACD survived under LIMIT only.

The single survivor (USD_JPY bullish engulfing relaxed long) clears the v2 gate by ~1 standard error of zero on the test half (test CI [+0.0004, +0.344]) — technically passing but in the same gate-skating zone as the pivot survivors. It does survive the spread test (which the pivot survivors didn't), so there's *some* edge here, but it's thin and single-pair.

## Why limit/stop entries fail (interpretation)

Candlestick patterns are **bar-geometry-dependent** in a way the other tested indicators aren't:

- A hammer's *defining feature* is the long lower shadow. The bar's low is, by construction, far below the close. Limit-at-bar-low entry asks for a pullback below the lowest point of an already-extended low — that's asking the rejection candle to fail.
- A bullish engulfing bar's *defining feature* is that its body engulfs the prior bar. The close is at or above the prior bar's open. Limit-at-bar-low again asks for a pullback into territory the engulfing has just rejected — same structural problem.
- Stop-buy at bar high asks for continuation past the bar's high. For a single-bar reversal pattern, the bar's high is often near the *peak* of the move being reversed — a stop above that asks the reversal to immediately resume in the direction it just flipped from. Often it just doesn't fire.

So mid-close is the only entry mode that takes the candle's own message at face value. The +0.172 R/trade test edge under mid is consistent with that interpretation.

## Why the edge is thin (interpretation)

Three candidate reasons:

1. **Pattern detection is rule-of-thumb.** The detectors use fixed body/shadow ratios. There's nothing dynamic about market context — a hammer at the top of a parabolic uptrend looks identical to a hammer at a major support level, and they have very different forward distributions. The other working indicators (RSI, Stoch, CCI, etc.) all have *internal state* that captures regime context.
2. **Pattern frequency is high.** Hammer fires ~780 times per pair on relaxed thresholds; over 40 pairs that's ~31,000 sample candidates. Most of those fires don't carry edge. Strict thresholds (~240 fires/pair) cut noise but also cut signal — strict variants didn't surface a single survivor.
3. **H4 forex isn't the natural timeframe.** Candlesticks were originally daily-bar / equity literature. On 4-hour forex bars, the pattern frequency is much higher (more fires per unit calendar time) and the per-pattern significance is lower.

## Result Summary

| Entry mode | Walk-forward cells | Walk-forward survivors | Spread-robust | Production cells |
|------------|--------------------|------------------------|---------------|------------------|
| `--entry mid`   | 320 | 1 | 1 | **1** (USD_JPY bull_engulf) |
| `--entry limit` | 320 | 0 | 0 | **0** (NULL) |
| `--entry stop`  | 320 | 0 | 0 | **0** (NULL) |

### Production Cell

| Pair    | Pattern              | Strict | Direction | Train n | Train mean_R | Train CI | Test n | Test mean_R | Test CI |
|---------|----------------------|--------|-----------|---------|--------------|----------|--------|-------------|---------|
| USD_JPY | bullish_engulfing    | False  | long      | 291     | +0.123       | [+0.014, +0.233] | 125    | +0.172      | [+0.0004, +0.344] |

Test CI lower bound at +0.0004 is essentially zero — passes the v2 gate but only just. Train half is more comfortably above zero. Treat this as marginal evidence, not a strong edge.

### Portfolio Performance (single-cell, USD_JPY long)

| Metric          | Train (n=291) | Test (n=125)  | Full (n=416) |
|-----------------|---------------|---------------|--------------|
| WR              | 56.3%         | 58.2%         | 56.9%        |
| Mean R / trade  | +0.123        | +0.172        | +0.138       |
| Cumulative R    | +35.9         | +21.5         | +57.4        |
| Max drawdown    | -11.1R        | -9.0R         | -11.1R       |
| Max consec losses | 10          | 5             | 10           |
| Max simultaneous | 6            | 4             | 6            |

### Trigger Spec

**Bullish Engulfing (relaxed):** prior bar bearish (`prev_close < prev_open`), current bar bullish (`close > open`), current open ≤ prior close, current close ≥ prior open, both bars body fraction ≥ 0.30 of their range. Detector: `bh_ftmo.indicators.candlestick.is_bullish_engulfing(min_body_frac=0.3)` (default).

**Entry:** market order at the engulfing bar's close (mid). NOT limit, NOT stop — both fail under v2.

**Exit:** TP at `entry × 1.01`, stop at `entry × 0.99`, timeout at `close_bid` after 84 H4 bars.

## Cumulative Indicator Status (BH FTMO Phase 2 v2 sweep)

| Indicator   | Shape           | v2 production cells | Notes |
|-------------|-----------------|---------------------|-------|
| BB          | mean-reversion  | 5 | working |
| Stochastic  | mean-reversion  | 4 | working |
| SMA-band    | mean-reversion  | 3 | working |
| EMA-band    | mean-reversion  | 4 | working |
| RSI         | mean-reversion  | 3 | working |
| CCI         | mean-reversion  | 5 | working |
| MACD (limit) | inflection-event | 5 | working — limit only |
| **Candlestick (mid)** | **bar-pattern reversal** | **1** | **thin: USD_JPY bull_engulf** |
| Pivots      | level-touch     | 0 (null) | smoothing absence |
| Donchian    | breakout         | 0 (null) | trend shape |
| SuperTrend  | trend-flip       | 0 (null) | trend shape |

Refines the working-shape spectrum:

- **Smoothed mean-reversion** (oscillators, distance-from-MA): productive across multiple pairs.
- **Inflection-event** (MACD signal cross under limit entry): productive, ~5 pairs, smallest DD of the set.
- **Bar-pattern reversal** (candlesticks under mid entry): marginal — one thin pair, gate-skating margins.
- **Level-touch mean-reversion** (pivots): NULL — no internal smoothing.
- **Trend-following** (Donchian, SuperTrend): NULL across all entry modes.

The one-pair candlestick result lives at the boundary between "marginal positive" and "noise." It's worth noting in the FTMO portfolio review but probably not a load-bearing piece of the deployed system.

## Reproducibility

- `research/_v2_rerun/run_candlestick_v2.py` — full pipeline, supports `--entry={mid,limit,stop}`
- `research/_v2_rerun/candlestick/walkforward.csv`, `walkforward_limit.csv`, `walkforward_stop.csv`
- `research/_v2_rerun/candlestick/walkforward_spread.csv` — single survivor row
- `research/_v2_rerun/candlestick/portfolio_trades.csv` — 416-trade ledger

(No limit/stop portfolio CSVs — both NULL.)

Param grid: 4 patterns × 2 strictness × 40 pairs = 320 cells per entry mode.
