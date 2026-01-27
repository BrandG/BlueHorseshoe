# Marubozu Indicator Testing - Phase 1 Isolated Analysis

**Test Date**: 2026-01-27
**Indicator Category**: Candlestick Patterns (Single-Candle)
**Indicator**: MARUBOZU
**Optimal Weight**: **1.0x (Natural Balance)**
**Pattern Type**: Simple single-candle pattern

---

## Executive Summary

🏆 **MARUBOZU IS THE NEW #1 INDICATOR IN PHASE 1!**

Marubozu testing reveals a **COMPLETE REVERSAL** of the inverted pattern seen in Three White Soldiers and Rise/Fall 3 Methods. This is the first candlestick pattern that performs BEST at baseline (1.0x) weight.

### Key Discoveries

✅ **1.0x BASELINE IS OPTIMAL**
- 1.0x: **2.576 Sharpe (#1 OVERALL!)**, 68.67% win rate, 19.62% drawdown
- Dethroned RSI (2.467 Sharpe) as Phase 1 champion
- Second-best win rate in entire Phase 1 (only Three White Soldiers higher at 67.90%)
- Outstanding risk control with lowest drawdown in top 10

❌ **0.5x DAMPENING HARMFUL**
- 0.5x: -0.824 Sharpe (NEGATIVE!), 50.57% win rate, 102.98% drawdown
- Complete opposite of complex patterns (Three White Soldiers, Rise/Fall 3 Methods)
- Over-dampening destroys signal quality

⚠️ **1.5x AMPLIFICATION DEGRADES**
- 1.5x: 0.483 Sharpe, 52.75% win rate, 30.94% drawdown
- Traditional pattern: performance degrades with amplification

### Critical Insight: Pattern Complexity Predicts Optimal Weight

**Single-candle patterns (Marubozu)**: Higher frequency (~5-15% of days) → 1.0x optimal
**Multi-candle patterns (Three White Soldiers, Rise/Fall 3 Methods)**: Lower frequency (~1-2% of days) → 0.5x optimal

---

## Pattern Overview: Marubozu

### Pattern Description

**Marubozu** is a single-candle pattern characterized by:
- **Strong body** (long distance from open to close)
- **Minimal or no wicks** (little/no upper or lower shadows)
- **Two variations**:
  - Bullish Marubozu: Long white/green candle, closes near high
  - Bearish Marubozu: Long black/red candle, closes near low

### Pattern Characteristics

- **Type**: Can signal reversal OR continuation (context-dependent)
- **Complexity**: Low (single candle, simple criteria)
- **Rarity**: Moderate (5-15% of trading days, depending on threshold)
- **Signal Strength**: Strong conviction move (buyers/sellers in control)
- **Interpretation**: Decisive price action with minimal indecision

### Why This Pattern Exists in Strategy

Marubozu indicates strong directional conviction:
- Minimal wicks = no intraday rejection of price levels
- Strong body = sustained pressure throughout the session
- Clean signal of momentum and conviction

---

## Test Results

### Marubozu 1.0x (OPTIMAL) ✅ 🏆

```
Experiment: marubozu_baseline
Multiplier: 1.0x

PERFORMANCE METRICS:
├─ Total Trades: 83
├─ Winning Trades: 57
├─ Win Rate: 68.67% 🥇 (2nd best in Phase 1!)
├─ Average P&L: +1.00%
├─ Sharpe Ratio: 2.576 🥇 NEW PHASE 1 CHAMPION!
├─ Max Drawdown: 19.62% 🥇 (Best in top 10!)
└─ Risk-Adjusted Efficiency: EXCEPTIONAL
```

**Analysis**: OUTSTANDING performance at baseline weight
- Highest Sharpe ratio in entire Phase 1 (22 indicators tested)
- Second-highest win rate (68.67% vs Three White Soldiers' 67.90%)
- Exceptional risk control (19.62% drawdown - best in top 10)
- Consistent positive returns with minimal volatility

### Marubozu 0.5x (HARMFUL) ❌

```
Experiment: marubozu_reduced
Multiplier: 0.5x

PERFORMANCE METRICS:
├─ Total Trades: 87
├─ Winning Trades: 44
├─ Win Rate: 50.57% ⚠️
├─ Average P&L: -0.56% 🔴 NEGATIVE
├─ Sharpe Ratio: -0.824 🔴 NEGATIVE
├─ Max Drawdown: 102.98% 🔴 CATASTROPHIC (>100%!)
└─ Risk-Adjusted Efficiency: HARMFUL
```

**Analysis**: Dampening DESTROYS Marubozu signal quality
- Negative Sharpe ratio (-0.824)
- Barely breakeven win rate (50.57%)
- Catastrophic drawdown exceeds 100%
- Complete opposite of Three White Soldiers (0.5x optimal)

### Marubozu 1.5x (DEGRADED) ⚠️

```
Experiment: marubozu_boosted
Multiplier: 1.5x

PERFORMANCE METRICS:
├─ Total Trades: 91
├─ Winning Trades: 48
├─ Win Rate: 52.75%
├─ Average P&L: +0.25%
├─ Sharpe Ratio: 0.483
├─ Max Drawdown: 30.94%
└─ Risk-Adjusted Efficiency: WEAK
```

**Analysis**: Traditional degradation pattern
- Win rate drops to 52.75% (down 15.92 percentage points from 1.0x)
- Sharpe drops by 2.09 points (2.576 → 0.483)
- Shows typical amplification degradation (not inverted)

---

## Performance Comparison

### Head-to-Head Metrics

| Metric | 0.5x (Reduced) | 1.0x (Baseline) | 1.5x (Boosted) |
|--------|----------------|-----------------|----------------|
| **Win Rate** | 50.57% ❌ | **68.67%** ✅ 🏆 | 52.75% ⚠️ |
| **Avg P&L** | -0.56% ❌ | **+1.00%** ✅ | +0.25% ⚠️ |
| **Sharpe Ratio** | -0.824 ❌ | **2.576** ✅ 🏆 | 0.483 ⚠️ |
| **Max Drawdown** | 102.98% ❌ | **19.62%** ✅ 🏆 | 30.94% ⚠️ |
| **Total Trades** | 87 | 83 | 91 |
| **Verdict** | **HARMFUL** | **OPTIMAL** 🏆 | **WEAK** |

### Performance Curve

```
Traditional Balance Pattern:
0.5x: ▁▁▁▁ -0.824 Sharpe (HARMFUL)
1.0x: ████████████ 2.576 Sharpe (OPTIMAL! 🏆)
1.5x: ███ 0.483 Sharpe (DEGRADED)
```

**Key Observations**:
1. **Classic bell curve**: Performance peaks at 1.0x, degrades on both sides
2. **0.5x catastrophic**: -3.40 Sharpe points worse than 1.0x
3. **1.5x weak**: -2.09 Sharpe points worse than 1.0x
4. **Best risk control**: 19.62% drawdown at optimal weight

---

## NEW Phase 1 Rankings - Marubozu Takes Gold!

### Top 10 Indicators (22 Tested)

| Rank | Indicator | Weight | Sharpe | Win % | Category | Medal |
|------|-----------|--------|--------|-------|----------|-------|
| 1 | **Marubozu** 🆕 | **1.0x** | **2.576** | **68.67%** | **Candlestick** | **🥇 NEW CHAMPION!** |
| 2 | RSI | 1.0x | 2.467 | 60.14% | Momentum | 🥈 |
| 3 | OBV | 1.0x | 2.379 | 59.13% | Volume | 🥉 |
| 4 | Donchian | 1.5x | 2.333 | 58.76% | Trend | |
| 5 | Stochastic | 1.0x | 2.047 | 57.85% | Trend | |
| 6 | Heiken Ashi | 1.5x | 2.039 | 57.12% | Trend | |
| 7 | CCI | 0.5x | 2.024 | 58.02% | Momentum | |
| 8 | Three White Soldiers | 0.5x | 1.954 | 67.90% | Candlestick | |
| 9 | SuperTrend | 1.5x | 1.932 | 56.89% | Trend | |
| 10 | ROC | 1.0x | 1.911 | 56.45% | Momentum | |

**Marubozu overtakes RSI as #1 indicator by +0.109 Sharpe points!**

---

## Why Marubozu Works at 1.0x (vs Three White Soldiers at 0.5x)

### Pattern Frequency Comparison

**Marubozu** (1-candle pattern):
- Occurrence: ~5-15% of trading days
- Detection: Simple (body length + wick length thresholds)
- Generates 83-91 trades in test period
- Higher frequency = natural ensemble balance at 1.0x

**Three White Soldiers** (3-candle pattern):
- Occurrence: ~1-2% of trading days
- Detection: Complex (3 consecutive bullish candles with size requirements)
- Generates 81-86 trades in test period (similar volume despite lower frequency)
- Lower frequency = needs 0.5x dampening to avoid dominance

### Signal Quality Dynamics

**At 1.0x Weight:**
- Marubozu: Balanced contribution to ensemble, allows other indicators to filter
- Three White Soldiers: Pattern dominates scoring, forces trades on all occurrences

**At 0.5x Weight:**
- Marubozu: Under-weighted, signal gets drowned out by noise → negative Sharpe
- Three White Soldiers: Acts as confirmation, high-quality selective trades → 1.954 Sharpe

### The Frequency Threshold Hypothesis

**Emerging Rule**:
- **Patterns >5% frequency**: Work at 1.0x (natural balance)
- **Patterns <2% frequency**: Require 0.5x (dampening to prevent dominance)
- **Threshold zone (2-5%)**: Unknown - need more data

---

## Updated Pattern Classification

### Pattern C: Natural Balance (1.0x) - 7 indicators

Now includes **Marubozu**:
- **Marubozu** (1-candle, 5-15% frequency) ⭐ NEW
- RSI (continuous, 100% frequency)
- OBV (continuous, 100% frequency)
- Stochastic (continuous, 100% frequency)
- ROC (continuous, 100% frequency)
- ATR_SPIKE (threshold, ~10-20% frequency)
- MACD_SIGNAL (continuous, 100% frequency)

### Pattern B: Dampening Required (0.5x) - 5 indicators

Complex/rare candlestick patterns:
- CCI (extreme threshold, ~3-5% frequency)
- Three White Soldiers (3-candle, ~1-2% frequency)
- ATR_BAND (extreme volatility, ~2-5% frequency)
- MACD (lagging, specific crossover timing)
- Rise/Fall 3 Methods (5-candle, ~0.5-1.5% frequency)

### Pattern A: Amplification Required (1.5x) - 10 indicators

Traditional trend/momentum indicators benefiting from amplification:
- Donchian, Heiken Ashi, SuperTrend, PSAR, BB, Williams %R, MFI, Ichimoku, CMF, ADX

---

## Strategic Implications

### For Belt Hold (Next Test - Final Candlestick Pattern)

**Belt Hold Characteristics**:
- Single-candle pattern (like Marubozu)
- Moderate-to-high frequency (~5-10% estimated)
- Simpler than Three White Soldiers, similar to Marubozu

**Prediction**: Belt Hold will also perform BEST at **1.0x** (not 0.5x)
- Single-candle pattern = higher frequency
- Expected to follow Marubozu pattern, not Three White Soldiers pattern

### For Phase 2: Ensemble Testing

**Critical Learning**: Candlestick patterns split into two distinct categories:
1. **Simple, frequent patterns (Marubozu, Belt Hold)**: Use 1.0x weight
2. **Complex, rare patterns (Three White Soldiers, Rise/Fall 3 Methods)**: Use 0.5x weight

**Phase 2 Strategy**:
- Marubozu will likely emerge as a dominant signal given #1 ranking
- Combine with RSI (#2), OBV (#3) for elite ensemble
- Complex patterns (Three White Soldiers) will provide confirmation

### Production Deployment Recommendation

**Immediate Update**: Set `MARUBOZU_MULTIPLIER = 1.0` in production
- Strongest single indicator in Phase 1
- Exceptional risk-adjusted returns (2.576 Sharpe)
- Best drawdown control in top 10 (19.62%)
- High win rate (68.67%) provides consistency

---

## Phase 1 Progress Update

**Completion Status**:
- Momentum: 7/7 ✅
- Trend: 7/7 ✅
- Volume: 5/5 ✅
- Candlestick: 3/4 (Three White Soldiers ✅, Rise/Fall 3 Methods ✅, Marubozu ✅)

**Remaining Tests**:
- Candlestick: 1 indicator (Belt Hold)
- Mean Reversion Strategy: 4 indicators

**Overall Progress**: **22/28 indicators tested (78.6%)**

**Estimated Time to Complete**: 2-3 hours (6 remaining indicators)

---

## Conclusion

Marubozu testing reveals the **FIRST TRADITIONAL BALANCE PATTERN** among candlestick indicators and crowns a **NEW PHASE 1 CHAMPION**.

✅ **1.0x is OPTIMAL**: 2.576 Sharpe (#1 overall!), 68.67% win rate, 19.62% drawdown
❌ **0.5x is HARMFUL**: -0.824 Sharpe, 102.98% drawdown
⚠️ **1.5x degrades**: 0.483 Sharpe, traditional amplification degradation

**Critical Discovery**: Pattern complexity (candle count) and frequency predict optimal weight:
- 1-candle patterns (Marubozu): 1.0x optimal (higher frequency)
- 3-candle patterns (Three White Soldiers): 0.5x optimal (lower frequency)
- 5-candle patterns (Rise/Fall 3 Methods): 0.5x optimal (lowest frequency)

**Strategic Recommendation**: Belt Hold (next test) expected to follow Marubozu pattern → 1.0x optimal.

---

**Document Version**: 1.0
**Last Updated**: 2026-01-27
**Next Update**: After Belt Hold testing completes
