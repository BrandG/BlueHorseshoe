# Ichimoku Cloud Experiment Summary

## Overview
Ichimoku Kinko Hyo (Equilibrium Chart at a Glance) is a comprehensive multi-component trend indicator that defines support/resistance, identifies trend direction, measures momentum, and provides trading signals in a single system. It consists of five lines and a "cloud" (Kumo) that together provide a complete picture of market equilibrium. This experiment tested Ichimoku at three weight configurations to determine optimal influence on baseline strategy scores.

## Experiment Configurations

### Test 1: Ichimoku Reduced (0.5x)
**Configuration:** `ICHIMOKU_MULTIPLIER = 0.5`

**Results:**
- **Win Rate:** 52.94%
- **Average P&L:** +0.02%
- **Sharpe Ratio:** 0.032
- **Max Drawdown:** 64.96%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At reduced weight, Ichimoku barely breaks even with near-zero Sharpe ratio (0.032). The 0.5x dampening suppresses the multi-component signals too much, resulting in essentially random performance with massive 64.96% drawdown.

### Test 2: Ichimoku Baseline (1.0x)
**Configuration:** `ICHIMOKU_MULTIPLIER = 1.0`

**Results:**
- **Win Rate:** 57.95%
- **Average P&L:** +0.55%
- **Sharpe Ratio:** 0.969
- **Max Drawdown:** 38.37%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At baseline weight, Ichimoku shows moderate improvement with 0.969 Sharpe. Performance is still below top-tier indicators but demonstrates the indicator's potential. The near 58% win rate suggests useful signal detection capability that needs amplification.

### Test 3: Ichimoku Boosted (1.5x) - OPTIMAL ✓
**Configuration:** `ICHIMOKU_MULTIPLIER = 1.5`

**Results:**
- **Win Rate:** 57.30%
- **Average P&L:** +0.88%
- **Sharpe Ratio:** 1.535 (#10 OVERALL!)
- **Max Drawdown:** 22.50% (BEST)
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At boosted weight, Ichimoku delivers solid performance with 1.535 Sharpe, ranking #10 overall. The +0.88% average gain and excellent 22.50% drawdown (best of all configs) demonstrate strong risk-adjusted returns. The 1.5x weight properly amplifies the multi-component signals to compete with simpler indicators.

## Comparative Analysis

| Metric | 0.5x | 1.0x | 1.5x (Winner) |
|--------|------|------|---------------|
| Win Rate | 52.94% | 57.95% | 57.30% |
| Avg P&L | +0.02% | +0.55% | **+0.88%** |
| Sharpe Ratio | 0.032 | 0.969 | **1.535** |
| Max Drawdown | 64.96% | 38.37% | **22.50%** |

**Key Insight:** Clear upward performance trend from 0.5x → 1.0x → 1.5x. Sharpe ratio improves 48x from 0.5x to 1.5x, while drawdown is cut by 65%. The 1.5x weight provides optimal signal strength and risk control.

## Pattern Recognition: Multi-Component Indicators Need Amplification

Ichimoku joins the "elevation required" category at 1.5x optimal weight:

**Elevation Required (1.5x optimal):**
- **BB (1.5x):** 1.647 Sharpe - Volatility bands, normalized percentile
- **Williams %R (1.5x):** 1.647 Sharpe - Bounded momentum oscillator
- **MFI (1.5x):** 1.612 Sharpe - Volume-weighted momentum
- **Ichimoku (1.5x):** 1.535 Sharpe - Multi-component trend system
- **CMF (1.5x):** 1.200 Sharpe - Money flow accumulation

**Why Multi-Component Indicators Need Amplification:**

Unlike single-value indicators (RSI, Stochastic, ROC), multi-component systems like Ichimoku aggregate multiple signals:
1. **Tenkan-sen (Conversion Line):** 9-period midpoint
2. **Kijun-sen (Base Line):** 26-period midpoint
3. **Senkou Span A:** Average of Tenkan/Kijun, projected forward
4. **Senkou Span B:** 52-period midpoint, projected forward
5. **Chikou Span:** Close price, plotted backward
6. **Kumo (Cloud):** Area between Senkou Spans

Each component contributes small incremental values. When averaged or combined, the composite signal has lower magnitude than single-calculation indicators. The 1.5x amplification brings Ichimoku's signal strength to parity with simpler indicators.

## Phase 1 Rankings (After 15 Indicators)

1. **RSI (1.0x):** 2.467 Sharpe 🥇
2. **OBV (1.0x):** 2.379 Sharpe 🥈
3. **Stochastic (1.0x):** 2.047 Sharpe 🥉
4. **CCI (0.5x):** 2.024 Sharpe
5. **ROC (1.0x):** 1.911 Sharpe
6. **BB (1.5x):** 1.647 Sharpe (tied)
6. **Williams %R (1.5x):** 1.647 Sharpe (tied)
8. **MFI (1.5x):** 1.612 Sharpe
9. **ATR_BAND (0.5x):** 1.549 Sharpe
10. **Ichimoku (1.5x):** 1.535 Sharpe (NEW - #10!)
11. **CMF (1.5x):** 1.200 Sharpe
12. **MACD (0.5x):** 1.146 Sharpe
13. **ADX (2.0x):** 0.738 Sharpe

**Failed:**
14. **ATR_SPIKE (0.0x):** -0.271 Sharpe (disabled)

Ichimoku ranks #10 overall with solid 1.535 Sharpe, slotting between ATR_BAND (#9) and CMF (#11).

## Trend Category Progress

**Trend Indicators (3 of 7 tested):**

| Indicator | Optimal Weight | Sharpe | Rank | Status |
|-----------|---------------|--------|------|--------|
| Stochastic | 1.0x | 2.047 | #3 | ✅ Bronze |
| Ichimoku | 1.5x | 1.535 | #10 | ✅ Solid (NEW) |
| ADX | 2.0x | 0.738 | #13 | ✅ Weak |
| PSAR | TBD | TBD | TBD | 🔄 Next |
| Heiken Ashi | TBD | TBD | TBD | ⏳ Pending |
| Donchian | TBD | TBD | TBD | ⏳ Pending |
| SuperTrend | TBD | TBD | TBD | ⏳ Pending |

**Trend category insights (3 tested):**
- Wide performance variance: 0.738 to 2.047 Sharpe (2.8x difference)
- Stochastic dominates (#3 overall - elite)
- Ichimoku solid mid-tier (#10 overall)
- ADX struggles standalone (#13 overall)
- Average of 3 tested: 1.440 Sharpe (moderate category strength)

## Recommendation

**Set `ICHIMOKU_MULTIPLIER = 1.5` in production weights.json**

**Rationale:**
1. **Solid performance:** 1.535 Sharpe ranks #10 overall
2. **Best risk control:** 22.50% max drawdown (lowest of all configurations)
3. **Strong profitability:** +0.88% average gain per trade
4. **Clear optimal:** 48x Sharpe improvement from 0.5x, 58% improvement from 1.0x
5. **Multi-component amplification:** 1.5x properly elevates aggregate signal strength

The 1.5x weight allows Ichimoku's comprehensive cloud/line system to compete with simpler single-value indicators while maintaining excellent risk control.

## Technical Context

**Ichimoku Components:**

```
Tenkan-sen (Conversion Line) = (9-period high + 9-period low) / 2
Kijun-sen (Base Line) = (26-period high + 26-period low) / 2
Senkou Span A (Leading Span A) = (Tenkan-sen + Kijun-sen) / 2, projected 26 periods ahead
Senkou Span B (Leading Span B) = (52-period high + 52-period low) / 2, projected 26 periods ahead
Chikou Span (Lagging Span) = Close price, plotted 26 periods back
Kumo (Cloud) = Area between Senkou Span A and Senkou Span B
```

**Traditional Signals:**
- **Price above cloud:** Bullish trend
- **Price below cloud:** Bearish trend
- **Price in cloud:** Consolidation/neutral
- **Cloud color (A>B = green, B>A = red):** Trend strength
- **Tenkan/Kijun cross:** Entry/exit signals (TK cross)
- **Price vs Kijun-sen:** Support/resistance levels
- **Chikou Span vs price:** Confirmation filter

**Baseline Strategy Application:**
Ichimoku contributes to trend scoring in the baseline (trend-following) strategy by:
1. Rewarding price above cloud (bullish structure)
2. Confirming trends via cloud color (A>B = bullish)
3. Identifying support via Kijun-sen
4. Detecting momentum via Tenkan/Kijun positioning
5. Filtering signals via Chikou Span confirmation

The 1.5x multiplier ensures Ichimoku's multi-layered signals carry appropriate weight alongside other trend indicators (Stochastic, ADX) and momentum indicators (RSI, ROC, CCI, MACD, BB, Williams %R).

## Strategic Insights

**Ichimoku's Unique Value:**

Ichimoku is the only indicator in Phase 1 testing that provides:
- **Future projection:** Senkou Spans plotted 26 periods ahead
- **Historical confirmation:** Chikou Span plotted 26 periods back
- **Multi-timeframe analysis:** Fast (9), medium (26), slow (52) components
- **Complete system:** Support, resistance, trend, momentum in one indicator

This comprehensive approach makes Ichimoku particularly valuable for:
- **Swing trading:** Cloud provides clear entry/exit zones
- **Trend following:** Cloud structure identifies established trends
- **Risk management:** Cloud thickness = volatility/uncertainty measure

**Ichimoku vs Other Trend Indicators:**

| Indicator | Type | Optimal Weight | Sharpe | Rank |
|-----------|------|---------------|--------|------|
| Stochastic | Momentum oscillator | 1.0x | 2.047 | #3 |
| Ichimoku | Multi-component cloud | 1.5x | 1.535 | #10 |
| ADX | Trend strength | 2.0x | 0.738 | #13 |

**Key Differences:**
- **Stochastic:** Measures position in range (0-100), single value
- **Ichimoku:** Measures equilibrium across multiple timeframes, 5+ values
- **ADX:** Measures trend strength only (no direction), single value

Ichimoku's complexity is both strength (comprehensive view) and weakness (needs amplification to match simpler indicators).

**Complementary with Stochastic:**
Using both in Phase 2 ensemble provides:
- **Stochastic:** Short-term momentum and overbought/oversold
- **Ichimoku:** Medium-term trend structure and support/resistance
- Together they cover both momentum extremes and trend context

## Why 1.5x Works for Ichimoku

**Multi-Component Aggregation Effect:**

When indicators aggregate multiple calculations, the result tends to be "averaged down":

**Single-Value Indicators (no averaging):**
- RSI: One calculation → Natural magnitude → 1.0x optimal
- Stochastic: One calculation → Natural magnitude → 1.0x optimal
- ROC: One calculation → Natural magnitude → 1.0x optimal

**Multi-Component Indicators (implicit averaging):**
- Ichimoku: 5+ components → Reduced magnitude → 1.5x needed
- MACD: Two EMAs + histogram → Reduced magnitude → 0.5x (different reason - large values)

Ichimoku's 5 lines each contribute to the scoring, and their average is lower than single-component indicators. The 1.5x boost brings it to parity.

**Historical Calibration:**
Ichimoku was developed in 1960s Japan for daily charts with specific period lengths (9, 26, 52). These periods may not have been optimized for modern markets or for combining with other indicators. The 1.5x adjustment helps Ichimoku compete in a multi-indicator ensemble.

## Comparison: Complex vs Simple Trend Indicators

**Performance by Complexity:**

| Indicator | Components | Complexity | Optimal Weight | Sharpe |
|-----------|------------|------------|---------------|--------|
| Stochastic | 2 (%K, %D) | Moderate | 1.0x | 2.047 |
| Ichimoku | 5+ (cloud) | Very High | 1.5x | 1.535 |
| ADX | 3 (+DI, -DI, ADX) | Moderate | 2.0x | 0.738 |

**Observation:** Complexity doesn't guarantee better performance. Stochastic (moderate complexity) outperforms both Ichimoku (very high) and ADX (moderate). However, all three positive performers contribute value from different angles.

## Next Steps

**Trend Category Progress: 3/7 Complete**

**Remaining Trend Indicators:**
- PSAR (Parabolic SAR - trailing stop)
- Heiken Ashi (modified candlesticks)
- Donchian (channel breakouts)
- SuperTrend (ATR-based trend following)

**Other Remaining Categories:**
- **Candlestick (4 patterns):** RISE_FALL_3_METHODS, THREE_WHITE_SOLDIERS, MARUBOZU, BELT_HOLD
- **Mean Reversion indicators:** RSI, BB, MA_DIST, CANDLESTICK (separate strategy)

**Suggested Next Steps:**
- Continue trend category testing with PSAR
- Complete all 40+ indicators in Phase 1
- Proceed to Phase 2 ensemble optimization

## Files Generated
- `ichimoku_reduced.log` (0.5x test output)
- `ichimoku_baseline.log` (1.0x test output)
- `ichimoku_boosted.log` (1.5x test output)
- `src/experiments/results/ichimoku_reduced.json`
- `src/experiments/results/ichimoku_baseline.json`
- `src/experiments/results/ichimoku_boosted.json`

---

**Experiment Date:** 2026-01-26
**Branch:** Tweak_indicators
**Commit:** [To be added]
**Achievement:** Ichimoku ranks #10 overall with solid 1.535 Sharpe! Comprehensive trend system needs 1.5x amplification.
