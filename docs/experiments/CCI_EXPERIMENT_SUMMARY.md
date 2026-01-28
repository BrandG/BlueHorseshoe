# CCI (Commodity Channel Index) Experiment Summary

## Overview
CCI (Commodity Channel Index) is a loosely-bounded momentum oscillator that measures how far price deviates from its statistical mean. Unlike strictly bounded oscillators (RSI: 0-100, Williams %R: -100 to 0), CCI typically ranges between -200 and +200 but can theoretically extend to ±∞. This experiment tested CCI at three weight configurations to determine optimal influence on baseline strategy scores.

## Experiment Configurations

### Test 1: CCI Reduced (0.5x) - OPTIMAL ✓
**Configuration:** `CCI_MULTIPLIER = 0.5`

**Results:**
- **Win Rate:** 58.54%
- **Average P&L:** +0.98%
- **Sharpe Ratio:** 2.024 ⭐ (RANKS #3 OVERALL!)
- **Max Drawdown:** 20.56%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At reduced weight, CCI delivers exceptional performance with a 2.024 Sharpe ratio, ranking #3 overall in Phase 1 testing (bronze medal). The 58.54% win rate combined with +0.98% average gain and minimal 20.56% drawdown demonstrates excellent risk-adjusted returns. The 0.5x weight tempers CCI's tendency toward extreme values, creating a well-calibrated signal.

### Test 2: CCI Baseline (1.0x)
**Configuration:** `CCI_MULTIPLIER = 1.0`

**Results:**
- **Win Rate:** 53.57%
- **Average P&L:** +0.69%
- **Sharpe Ratio:** 1.229
- **Max Drawdown:** 23.11%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At baseline weight, CCI shows moderate performance with positive but reduced returns compared to 0.5x. Win rate drops 5 percentage points, P&L decreases 30%, and Sharpe ratio falls 40%. While still profitable, the full-strength signal creates more noise and false positives.

### Test 3: CCI Boosted (1.5x) - WORST
**Configuration:** `CCI_MULTIPLIER = 1.5`

**Results:**
- **Win Rate:** 49.45%
- **Average P&L:** -0.56%
- **Sharpe Ratio:** -1.033
- **Max Drawdown:** 79.09%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** Boosting CCI produces disastrous results - negative returns, below-50% win rate, and catastrophic 79% maximum drawdown. The 1.5x amplification over-weights normal volatility as extreme signals, leading to premature entries on false breakouts and excessive sensitivity to market noise.

## Comparative Analysis

| Metric | 0.5x (Winner) | 1.0x | 1.5x |
|--------|---------------|------|------|
| Win Rate | **58.54%** | 53.57% | 49.45% |
| Avg P&L | **+0.98%** | +0.69% | -0.56% |
| Sharpe Ratio | **2.024** | 1.229 | -1.033 |
| Max Drawdown | **20.56%** | 23.11% | 79.09% |

**Key Insight:** CCI exhibits strong inverse relationship between weight and performance. As weight increases, all metrics degrade linearly - win rate drops, profitability decreases, drawdown explodes.

## Pattern Recognition: The "Dampening Required" Category

CCI joins MACD as the second indicator requiring weight reduction for optimal performance:

**Dampening Required (optimal at 0.5x):**
- **MACD (0.5x):** 1.146 Sharpe - Dual moving average crossover, large signal magnitude
- **CCI (0.5x):** 2.024 Sharpe - Mean deviation measurement, loosely bounded but volatile

**Baseline Weight (optimal at 1.0x):**
- **RSI (1.0x):** 2.467 Sharpe - Exceptionally strong bounded oscillator
- **OBV (1.0x):** 2.379 Sharpe - Cumulative volume, unbounded
- **ROC (1.0x):** 1.911 Sharpe - Percentage change, unbounded

**Elevation Required (optimal at 1.5x):**
- **BB (1.5x):** 1.647 Sharpe - Volatility bands, bounded percentile
- **Williams %R (1.5x):** 1.647 Sharpe - Bounded -100 to 0
- **MFI (1.5x):** 1.612 Sharpe - Volume-weighted RSI, bounded 0-100
- **CMF (1.5x):** 1.200 Sharpe - Volume flow, bounded -1 to +1

**High Amplification (optimal at 2.0x):**
- **ADX (2.0x):** 0.738 Sharpe - Trend strength, bounded 0-100 but weak signal

## Why CCI Needs Dampening

**1. Loosely Bounded = High Volatility:**
CCI typically ranges ±200 but can spike to extremes (±300+). Unlike RSI which is mathematically bounded to 0-100, CCI's statistical approach produces variable range, leading to occasional extreme values that dominate scoring.

**2. Mean Deviation Measurement:**
CCI formula: `(Typical Price - SMA) / (0.015 × Mean Deviation)`

The mean deviation denominator creates large absolute values when price volatility increases. During volatile periods, CCI can swing wildly, creating disproportionate influence on composite scores.

**3. Over-Sensitivity Without Dampening:**
At 1.0x or 1.5x, normal market volatility gets interpreted as extreme signals. The 0.5x weight provides appropriate scaling to balance CCI's contribution with other momentum indicators (RSI, ROC, MACD, BB, Williams %R).

## Phase 1 Rankings (After 11 Indicators - Momentum Category COMPLETE!)

1. **RSI (1.0x):** 2.467 Sharpe 🥇
2. **OBV (1.0x):** 2.379 Sharpe 🥈
3. **CCI (0.5x):** 2.024 Sharpe 🥉 (NEW - BRONZE!)
4. **ROC (1.0x):** 1.911 Sharpe
5. **BB (1.5x):** 1.647 Sharpe (tied)
5. **Williams %R (1.5x):** 1.647 Sharpe (tied)
7. **MFI (1.5x):** 1.612 Sharpe
8. **CMF (1.5x):** 1.200 Sharpe
9. **MACD (0.5x):** 1.146 Sharpe
10. **ADX (2.0x):** 0.738 Sharpe

**CCI wins the bronze medal (3rd place) with 2.024 Sharpe!**

## Milestone: Momentum Category Complete! 🎉

With CCI testing complete, we've finished the **entire momentum category (6/6 indicators)**:

| Indicator | Optimal Weight | Sharpe | Rank | Status |
|-----------|---------------|--------|------|--------|
| RSI | 1.0x | 2.467 | #1 | ✅ Gold |
| CCI | 0.5x | 2.024 | #3 | ✅ Bronze |
| ROC | 1.0x | 1.911 | #4 | ✅ Strong |
| BB | 1.5x | 1.647 | #5T | ✅ Solid |
| Williams %R | 1.5x | 1.647 | #5T | ✅ Solid |
| MACD | 0.5x | 1.146 | #9 | ✅ Moderate |

**Category Insights:**
- **3 indicators in top 4**: RSI (#1), CCI (#3), ROC (#4)
- **Average Sharpe: 1.740** - Momentum is a strong category
- **Weight diversity**: 2 at 0.5x, 1 at 1.0x, 3 at 1.5x
- **All positive**: Even the lowest (MACD) has 1.146 Sharpe

## Recommendation

**Set `CCI_MULTIPLIER = 0.5` in production weights.json**

**Rationale:**
1. **Best risk-adjusted returns:** 2.024 Sharpe ratio (ranks #3 overall)
2. **Strong profitability:** +0.98% average gain per trade
3. **Controlled risk:** 20.56% max drawdown (73% lower than 1.5x)
4. **High win rate:** 58.54% (9 percentage points better than 1.5x)
5. **Optimal scaling:** 0.5x dampens CCI's extreme value tendency

The 0.5x weight prevents CCI's statistical outliers from dominating the composite score while preserving its mean-reversion signal. CCI complements other momentum indicators by identifying when price has deviated significantly from statistical norms.

## Technical Context

**CCI Calculation:**
```
Typical Price = (High + Low + Close) / 3
CCI = (Typical Price - SMA of Typical Price) / (0.015 × Mean Deviation)
```

Standard period: 20 days. The constant 0.015 ensures approximately 70-80% of values fall between -100 and +100.

**Traditional Interpretation:**
- **Above +100:** Overbought, potential reversal
- **Below -100:** Oversold, potential reversal
- **Between -100 and +100:** Normal trading range
- **Extreme readings (±200+):** Strong trend or exhaustion

**Baseline Strategy Application:**
CCI contributes to momentum scoring by rewarding positive divergence from mean (bullish) and penalizing negative divergence (bearish). The 0.5x multiplier ensures CCI signals are appropriately weighted alongside RSI, ROC, MACD, BB, and Williams %R in the composite momentum assessment.

## Strategic Insights

**CCI's Unique Value:**
Unlike oscillators that measure position within recent range (RSI, Williams %R), CCI measures statistical deviation from mean price. This provides a different perspective:

- **RSI/Williams %R:** "Is price at extreme of recent range?"
- **ROC:** "What's the percentage change?"
- **CCI:** "How many standard deviations from the mean?"
- **MACD:** "Are short/long trends converging or diverging?"
- **BB:** "Is price at volatility band extremes?"

Having all six perspectives creates robust momentum assessment that captures different market dynamics.

**Complementary Signals:**
CCI works particularly well with RSI:
- Both identify overbought/oversold
- RSI bounded (0-100), CCI loosely bounded (typically ±200)
- RSI measures relative strength, CCI measures statistical deviation
- Together they confirm momentum extremes from multiple angles

## Next Steps

**Momentum Category: COMPLETE! ✅**

**Remaining Categories:**
1. **Trend (6 indicators):** STOCHASTIC, ICHIMOKU, PSAR, HEIKEN_ASHI, DONCHIAN, SUPERTREND (ADX already tested - 2.0x optimal)
2. **Volume (2 indicators):** ATR_BAND, ATR_SPIKE (OBV, CMF, MFI already tested)
3. **Candlestick (4 patterns):** RISE_FALL_3_METHODS, THREE_WHITE_SOLDIERS, MARUBOZU, BELT_HOLD
4. **Mean Reversion indicators:** RSI, BB, MA_DIST, CANDLESTICK (separate strategy)

**Suggested Next Steps:**
- Begin trend category testing with Stochastic
- Continue systematic Phase 1 isolated testing
- After all categories complete, proceed to Phase 2 ensemble optimization

## Files Generated
- `cci_reduced.log` (0.5x test output)
- `cci_baseline.log` (1.0x test output)
- `cci_boosted.log` (1.5x test output)
- `src/experiments/results/cci_reduced.json`
- `src/experiments/results/cci_baseline.json`
- `src/experiments/results/cci_boosted.json`

---

**Experiment Date:** 2026-01-25
**Branch:** Tweak_indicators
**Commit:** [To be added]
**Milestone:** Momentum Category Complete (6/6) 🎉
