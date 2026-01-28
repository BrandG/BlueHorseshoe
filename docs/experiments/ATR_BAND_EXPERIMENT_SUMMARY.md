# ATR_BAND Experiment Summary

## Overview
ATR_BAND uses Average True Range (ATR) to create dynamic volatility-based price bands around a moving average. Unlike Bollinger Bands which use standard deviation, ATR bands measure actual price movement including gaps, providing a different perspective on volatility. This experiment tested ATR_BAND at three weight configurations to determine optimal influence on baseline strategy scores.

## Experiment Configurations

### Test 1: ATR_BAND Reduced (0.5x) - OPTIMAL ✓
**Configuration:** `ATR_BAND_MULTIPLIER = 0.5`

**Results:**
- **Win Rate:** 64.37% ⭐ (HIGHEST WIN RATE IN PHASE 1!)
- **Average P&L:** +0.82%
- **Sharpe Ratio:** 1.549
- **Max Drawdown:** 23.76%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At reduced weight, ATR_BAND delivers exceptional win rate (64.37% - the highest we've seen in Phase 1 testing!) with solid profitability. The 1.549 Sharpe ratio ranks #8 overall. The 0.5x weight prevents volatility signals from dominating composite scores while preserving the indicator's trend/breakout detection capabilities.

### Test 2: ATR_BAND Baseline (1.0x)
**Configuration:** `ATR_BAND_MULTIPLIER = 1.0`

**Results:**
- **Win Rate:** 52.87%
- **Average P&L:** +0.54%
- **Sharpe Ratio:** 0.999
- **Max Drawdown:** 41.86%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At baseline weight, ATR_BAND shows moderate performance with win rate dropping 11.5 percentage points from 0.5x. The nearly doubled drawdown (41.86% vs 23.76%) indicates that full-strength volatility signals create excessive risk. Still profitable but significantly degraded from 0.5x.

### Test 3: ATR_BAND Boosted (1.5x)
**Configuration:** `ATR_BAND_MULTIPLIER = 1.5`

**Results:**
- **Win Rate:** 48.89%
- **Average P&L:** +0.23%
- **Sharpe Ratio:** 0.390
- **Max Drawdown:** 32.90%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** Boosting ATR_BAND produces severely degraded results - below-50% win rate, weak 0.390 Sharpe, and minimal profitability. The 1.5x amplification over-weights price volatility, leading to false signals and poor trade selection.

## Comparative Analysis

| Metric | 0.5x (Winner) | 1.0x | 1.5x |
|--------|---------------|------|------|
| Win Rate | **64.37%** | 52.87% | 48.89% |
| Avg P&L | **+0.82%** | +0.54% | +0.23% |
| Sharpe Ratio | **1.549** | 0.999 | 0.390 |
| Max Drawdown | **23.76%** | 41.86% | 32.90% |

**Key Insight:** Strong inverse relationship between weight and performance. As weight increases from 0.5x → 1.0x → 1.5x, win rate drops from 64% → 53% → 49%, and Sharpe ratio falls from 1.549 → 0.999 → 0.390.

## Pattern Recognition: The "Dampening Required" Category Grows

ATR_BAND joins MACD and CCI as the third indicator requiring weight reduction for optimal performance:

**Dampening Required (0.5x):**
- **MACD (0.5x):** 1.146 Sharpe - Dual MA crossover, large signal magnitude
- **CCI (0.5x):** 2.024 Sharpe - Mean deviation, loosely bounded, volatile extremes
- **ATR_BAND (0.5x):** 1.549 Sharpe - Volatility bands, large absolute values during volatility

**Baseline Weight (1.0x):**
- **RSI (1.0x):** 2.467 Sharpe - Exceptionally strong bounded oscillator
- **OBV (1.0x):** 2.379 Sharpe - Cumulative volume, unbounded
- **ROC (1.0x):** 1.911 Sharpe - Percentage change, unbounded

**Elevation Required (1.5x):**
- **BB (1.5x):** 1.647 Sharpe - Standard deviation bands, normalized
- **Williams %R (1.5x):** 1.647 Sharpe - Bounded -100 to 0
- **MFI (1.5x):** 1.612 Sharpe - Volume-weighted RSI, bounded 0-100
- **CMF (1.5x):** 1.200 Sharpe - Volume flow, bounded -1 to +1

**High Amplification (2.0x):**
- **ADX (2.0x):** 0.738 Sharpe - Trend strength, bounded 0-100 but weak signal

## Why ATR_BAND Needs Dampening

**1. Large Absolute Values During Volatility:**
ATR measures the true range of price movement (max of: High-Low, |High-PrevClose|, |Low-PrevClose|). During volatile periods, ATR produces large absolute values. When these are used to define band widths and score band touches/breaks, the signals can have disproportionate magnitude compared to other indicators.

**2. Volatility ≠ Directional Momentum:**
ATR_BAND measures price volatility and band position, not necessarily directional momentum. High volatility can occur in both trending and choppy markets. Without dampening, the indicator can over-weight price swings that don't represent genuine trend strength.

**3. Band Breakouts Can Be Noisy:**
Price touching or exceeding ATR bands can signal genuine breakouts OR false moves in choppy markets. At full strength (1.0x) or amplified (1.5x), these signals overwhelm other momentum/trend indicators. The 0.5x weight provides appropriate balance.

**4. Comparison to Bollinger Bands:**
Interesting contrast: BB (standard deviation bands) needs 1.5x amplification, while ATR_BAND (volatility bands) needs 0.5x dampening. This suggests:
- BB's statistical normalization produces smaller relative values → needs amplification
- ATR's absolute range measurement produces larger values → needs dampening

## Phase 1 Rankings (After 12 Indicators)

1. **RSI (1.0x):** 2.467 Sharpe 🥇
2. **OBV (1.0x):** 2.379 Sharpe 🥈
3. **CCI (0.5x):** 2.024 Sharpe 🥉
4. **ROC (1.0x):** 1.911 Sharpe
5. **BB (1.5x):** 1.647 Sharpe (tied)
5. **Williams %R (1.5x):** 1.647 Sharpe (tied)
7. **MFI (1.5x):** 1.612 Sharpe
8. **ATR_BAND (0.5x):** 1.549 Sharpe (NEW - #8!)
9. **CMF (1.5x):** 1.200 Sharpe
10. **MACD (0.5x):** 1.146 Sharpe
11. **ADX (2.0x):** 0.738 Sharpe

ATR_BAND ranks #8 overall with solid 1.549 Sharpe. Notably, it achieved the **highest win rate (64.37%)** of any indicator tested in Phase 1!

## Volume Category Progress

**Volume Indicators (4 of 5 tested):**
| Indicator | Weight | Sharpe | Rank | Win Rate | Status |
|-----------|--------|--------|------|----------|--------|
| OBV | 1.0x | 2.379 | #2 | ~60% | ✅ Silver |
| MFI | 1.5x | 1.612 | #7 | 58.97% | ✅ Solid |
| ATR_BAND | 0.5x | 1.549 | #8 | **64.37%** | ✅ NEW |
| CMF | 1.5x | 1.200 | #9 | 60.47% | ✅ Solid |
| ATR_SPIKE | TBD | TBD | TBD | TBD | 🔄 Next |

**Volume category average (4 tested): 1.685 Sharpe** - Strong category performance!

**Remaining:** ATR_SPIKE (1 indicator left to complete volume category)

## Recommendation

**Set `ATR_BAND_MULTIPLIER = 0.5` in production weights.json**

**Rationale:**
1. **Highest win rate in Phase 1:** 64.37% (11.5 points higher than 1.0x)
2. **Strong Sharpe ratio:** 1.549 (ranks #8 overall)
3. **Controlled risk:** 23.76% max drawdown (43% lower than 1.0x)
4. **Solid profitability:** +0.82% average gain per trade
5. **Optimal volatility signal scaling:** 0.5x prevents ATR's large absolute values from dominating composite scores

The 0.5x weight allows ATR_BAND to contribute volatility/breakout signals without over-weighting price swings relative to momentum (RSI, ROC, CCI, MACD) and volume (OBV, CMF, MFI) indicators.

## Technical Context

**ATR Calculation:**
```
True Range = max(High - Low, |High - Previous Close|, |Low - Previous Close|)
ATR = Moving Average of True Range (typically 14 periods)
```

**ATR_BAND Calculation:**
```
Middle Band = Moving Average of Price (typically SMA or EMA)
Upper Band = Middle Band + (ATR × Multiplier)
Lower Band = Middle Band - (ATR × Multiplier)
```

**Signals:**
- Price above upper band: Strong uptrend or overbought
- Price below lower band: Strong downtrend or oversold
- Price within bands: Normal trading range
- Band expansion: Increasing volatility
- Band contraction: Decreasing volatility

**Baseline Strategy Application:**
ATR_BAND contributes to the baseline (trend-following) strategy by:
1. Rewarding price near/above upper band (bullish momentum)
2. Penalizing price near/below lower band (bearish momentum)
3. Identifying volatility breakouts (band expansion during trends)

The 0.5x multiplier ensures these volatility signals complement rather than dominate the momentum indicators (RSI, ROC, CCI, MACD, BB, Williams %R) and other volume indicators (OBV, CMF, MFI).

## Strategic Insights

**ATR_BAND vs Bollinger Bands:**
Both create dynamic price bands, but with different approaches:

- **Bollinger Bands (BB):** Uses standard deviation (statistical volatility)
  - Normalized to price distribution
  - Needs 1.5x amplification
  - 1.647 Sharpe at 1.5x

- **ATR Bands:** Uses actual true range (absolute volatility)
  - Captures gaps and discontinuities
  - Needs 0.5x dampening
  - 1.549 Sharpe at 0.5x

Using both provides complementary volatility perspectives: statistical (BB) and absolute (ATR_BAND).

**Highest Win Rate Achievement:**
ATR_BAND's 64.37% win rate is the highest in Phase 1, even higher than:
- RSI: ~62% (estimated)
- OBV: ~60% (estimated)
- CCI: 58.54%

This suggests ATR_BAND excels at filtering low-quality setups. The volatility perspective helps avoid choppy, directionless markets where momentum indicators might give false signals.

**Volume Category Strength:**
With 4 of 5 volume indicators tested, the category shows strong average performance (1.685 Sharpe). Volume indicators provide crucial confirmation of price moves:
- OBV: Cumulative volume direction
- MFI: Volume-weighted price momentum
- CMF: Money flow over period
- ATR_BAND: Volatility-adjusted price position

## Next Steps

**Volume Category Progress: 4/5 Complete**

**Remaining Volume Indicator:**
- ATR_SPIKE (1 indicator)

After ATR_SPIKE, the volume category will be complete!

**Other Remaining Categories:**
1. **Trend (6 indicators):** STOCHASTIC, ICHIMOKU, PSAR, HEIKEN_ASHI, DONCHIAN, SUPERTREND (ADX already tested)
2. **Candlestick (4 patterns):** RISE_FALL_3_METHODS, THREE_WHITE_SOLDIERS, MARUBOZU, BELT_HOLD
3. **Mean Reversion indicators:** RSI, BB, MA_DIST, CANDLESTICK (separate strategy)

## Files Generated
- `atr_band_reduced.log` (0.5x test output)
- `atr_band_baseline.log` (1.0x test output)
- `atr_band_boosted.log` (1.5x test output)
- `src/experiments/results/atr_band_reduced.json`
- `src/experiments/results/atr_band_baseline.json`
- `src/experiments/results/atr_band_boosted.json`

---

**Experiment Date:** 2026-01-25
**Branch:** Tweak_indicators
**Commit:** [To be added]
**Achievement:** Highest win rate in Phase 1 testing (64.37%)! 🎯
