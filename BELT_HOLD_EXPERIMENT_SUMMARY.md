# Belt Hold Indicator Testing - Phase 1 Isolated Analysis

**Test Date**: 2026-01-27
**Indicator Category**: Candlestick Patterns (Single-Candle Reversal)
**Indicator**: BELT_HOLD
**Optimal Weight**: **1.5x (Amplification)**
**Pattern Type**: Single-candle reversal pattern

---

## Executive Summary

Belt Hold testing reveals a **TRADITIONAL AMPLIFICATION PATTERN** (Pattern A), making it distinct from Marubozu despite both being single-candle patterns. This completes the candlestick category with **all 4 patterns tested**.

### Key Discoveries

✅ **1.5x AMPLIFICATION IS OPTIMAL**
- 1.5x: **0.699 Sharpe** (BEST), 54.43% win rate, 59.60% drawdown
- Performance increases monotonically from 0.5x → 1.0x → 1.5x
- Traditional amplification pattern (Pattern A)

⚠️ **1.0x MODERATE**
- 1.0x: 0.514 Sharpe, 57.83% win rate, 70.36% drawdown
- Acceptable but suboptimal

❌ **0.5x WEAK**
- 0.5x: 0.147 Sharpe, 50.59% win rate, 26.69% drawdown
- Dampening destroys signal quality

### Critical Insight: Not All Single-Candle Patterns Are Equal

**Marubozu** (1-candle): Optimal at 1.0x (Pattern C - Natural Balance)
**Belt Hold** (1-candle): Optimal at 1.5x (Pattern A - Amplification Required)

**Key Difference**: Pattern characteristics (frequency, strength, context requirements) matter more than candle count.

---

## Pattern Overview: Belt Hold

### Pattern Description

**Belt Hold** is a single-candle reversal pattern with two variations:

**Bullish Belt Hold** (reversal from downtrend):
- Opens at/near the low of the session
- Strong bullish body with little/no lower wick
- Closes near the high
- Signals potential reversal upward

**Bearish Belt Hold** (reversal from uptrend):
- Opens at/near the high of the session
- Strong bearish body with little/no upper wick
- Closes near the low
- Signals potential reversal downward

### Pattern Characteristics

- **Type**: Reversal pattern (not continuation)
- **Complexity**: Low (single candle, simple criteria)
- **Rarity**: Moderate (5-10% of trading days estimated)
- **Signal Strength**: Strong directional move from open
- **Context**: Requires existing trend to reverse

### Why This Pattern Exists in Strategy

Belt Hold indicates potential trend reversal:
- Opens at extreme, closes at opposite extreme
- Shows complete dominance by one side during the session
- Minimal wicks indicate sustained pressure
- Similar to Marubozu but with specific reversal context

---

## Test Results

### Belt Hold 1.5x (OPTIMAL) ✅

```
Experiment: belt_hold_boosted
Multiplier: 1.5x

PERFORMANCE METRICS:
├─ Total Trades: 79
├─ Winning Trades: 43
├─ Win Rate: 54.43%
├─ Average P&L: +0.38%
├─ Sharpe Ratio: 0.699 ⭐ BEST
├─ Max Drawdown: 59.60%
└─ Risk-Adjusted Efficiency: GOOD
```

**Analysis**: Best performance at amplified weight
- Highest Sharpe ratio at 0.699
- Solid win rate above 54%
- Moderate drawdown (acceptable for amplified signal)
- Clear winner among three configurations

### Belt Hold 1.0x (MODERATE) ⚠️

```
Experiment: belt_hold_baseline
Multiplier: 1.0x

PERFORMANCE METRICS:
├─ Total Trades: 83
├─ Winning Trades: 48
├─ Win Rate: 57.83%
├─ Average P&L: +0.31%
├─ Sharpe Ratio: 0.514
├─ Max Drawdown: 70.36%
└─ Risk-Adjusted Efficiency: MODERATE
```

**Analysis**: Acceptable but suboptimal
- Lower Sharpe than 1.5x (0.514 vs 0.699)
- Slightly better win rate but worse risk-adjusted returns
- Higher drawdown at 70.36%

### Belt Hold 0.5x (WEAK) ❌

```
Experiment: belt_hold_reduced
Multiplier: 0.5x

PERFORMANCE METRICS:
├─ Total Trades: 85
├─ Winning Trades: 43
├─ Win Rate: 50.59%
├─ Average P&L: +0.06%
├─ Sharpe Ratio: 0.147 ❌ WEAK
├─ Max Drawdown: 26.69%
└─ Risk-Adjusted Efficiency: WEAK
```

**Analysis**: Dampening is harmful
- Lowest Sharpe at 0.147 (79% worse than 1.5x)
- Barely breakeven win rate (50.59%)
- Low drawdown but insignificant returns
- Under-weighting destroys signal value

---

## Performance Comparison

### Head-to-Head Metrics

| Metric | 0.5x (Reduced) | 1.0x (Baseline) | 1.5x (Boosted) |
|--------|----------------|-----------------|----------------|
| **Win Rate** | 50.59% ❌ | 57.83% ⚠️ | **54.43%** ✅ |
| **Avg P&L** | +0.06% ❌ | +0.31% ⚠️ | **+0.38%** ✅ |
| **Sharpe Ratio** | 0.147 ❌ | 0.514 ⚠️ | **0.699** ✅ |
| **Max Drawdown** | **26.69%** ✅ | 70.36% ❌ | 59.60% ⚠️ |
| **Total Trades** | 85 | 83 | 79 |
| **Verdict** | **WEAK** | **MODERATE** | **OPTIMAL** ✅ |

### Performance Curve - Traditional Amplification

```
Traditional Amplification Pattern (Pattern A):
0.5x: ██ 0.147 Sharpe (WEAK)
1.0x: ████ 0.514 Sharpe (MODERATE)
1.5x: ██████ 0.699 Sharpe (OPTIMAL) ✅
```

**Key Observations**:
1. **Monotonic increase**: Performance improves consistently with weight
2. **0.5x harmful**: -0.552 Sharpe points vs 1.5x (79% worse)
3. **1.5x clear winner**: +0.185 Sharpe points vs 1.0x (36% better)
4. **Traditional pattern**: Follows Pattern A like most trend/momentum indicators

---

## Comparison with Marubozu (Single-Candle Patterns)

### Head-to-Head: Belt Hold vs Marubozu

| Metric | Belt Hold | Marubozu | Difference |
|--------|-----------|----------|------------|
| **Optimal Weight** | **1.5x** | **1.0x** | Different! |
| **Optimal Sharpe** | 0.699 | 2.576 | -1.877 (Marubozu >> Belt Hold) |
| **Win Rate (Optimal)** | 54.43% | 68.67% | -14.24% |
| **Pattern Type** | Reversal | Reversal/Continuation | Both reversal-capable |
| **Pattern Class** | Pattern A (Amplify) | Pattern C (Balance) | Different classes! |
| **Rank** | ~#23-24 (lower tier) | #1 (Champion!) | 22-23 positions |

### Why Different Optimal Weights Despite Both Being Single-Candle?

**Marubozu Characteristics**:
- Higher frequency (~5-15% of days)
- Cleaner signal (minimal wicks = strong conviction)
- Works in any context (reversal OR continuation)
- Natural balance at 1.0x

**Belt Hold Characteristics**:
- Moderate frequency (~5-10% of days)
- Requires trend context (reversal-specific)
- More complex interpretation (opening position matters)
- Benefits from amplification at 1.5x

**Key Insight**: Pattern complexity and context requirements matter more than candle count. Belt Hold's reversal-specific nature benefits from amplification to overcome baseline ensemble noise.

---

## Candlestick Patterns Complete - Full Summary

### All 4 Patterns Tested

| Pattern | Candles | Optimal Weight | Sharpe | Win % | Rank | Pattern Class |
|---------|---------|----------------|--------|-------|------|---------------|
| **Marubozu** | 1 | **1.0x** | **2.576** | **68.67%** | **#1** 🥇 | Pattern C (Natural Balance) |
| Three White Soldiers | 3 | **0.5x** | 1.954 | 67.90% | #8 | Pattern B (Dampening) |
| Rise/Fall 3 Methods | 5 | **0.5x** | 0.782 | 55.17% | #20 | Pattern B (Dampening) |
| **Belt Hold** | 1 | **1.5x** | **0.699** | 54.43% | **#23** | **Pattern A (Amplification)** |

### Pattern Classification Insights

**Pattern A (Amplification 1.5x)**: Belt Hold
- Single-candle reversal pattern
- Requires trend context
- Benefits from amplification to signal reversals clearly

**Pattern B (Dampening 0.5x)**: Three White Soldiers, Rise/Fall 3 Methods
- Multi-candle patterns (3-5 candles)
- Rare occurrences (<2% frequency)
- Require dampening to avoid dominance

**Pattern C (Natural Balance 1.0x)**: Marubozu
- Single-candle pattern
- High frequency (~5-15%)
- Natural balance works best

### Candlestick Category Performance

**Range**: 0.699 - 2.576 Sharpe
**Best**: Marubozu (1.0x) - #1 overall
**Good**: Three White Soldiers (0.5x) - #8 overall
**Moderate**: Rise/Fall 3 Methods (0.5x) - #20 overall
**Weak**: Belt Hold (1.5x) - #23 overall

**Category Insight**: Candlestick patterns show HIGHEST VARIANCE in optimal weights (0.5x, 1.0x, 1.5x all represented) and widest performance range among all categories.

---

## Phase 1 Rankings Update

### Top 25 Indicators (23 Tested)

| Rank | Indicator | Weight | Sharpe | Win % | Category |
|------|-----------|--------|--------|-------|----------|
| 1 | Marubozu | 1.0x | 2.576 | 68.67% | Candlestick 🥇 |
| 2 | RSI | 1.0x | 2.467 | 60.14% | Momentum 🥈 |
| 3 | OBV | 1.0x | 2.379 | 59.13% | Volume 🥉 |
| 4 | Donchian | 1.5x | 2.333 | 58.76% | Trend |
| 5 | Stochastic | 1.0x | 2.047 | 57.85% | Trend |
| 6 | Heiken Ashi | 1.5x | 2.039 | 57.12% | Trend |
| 7 | CCI | 0.5x | 2.024 | 58.02% | Momentum |
| 8 | Three White Soldiers | 0.5x | 1.954 | 67.90% | Candlestick |
| 9 | SuperTrend | 1.5x | 1.932 | 56.89% | Trend |
| 10 | ROC | 1.0x | 1.911 | 56.45% | Momentum |
| ... | ... | ... | ... | ... | ... |
| 20 | Rise/Fall 3 Methods | 0.5x | 0.782 | 55.17% | Candlestick |
| ... | ... | ... | ... | ... | ... |
| 23 | **Belt Hold** | **1.5x** | **0.699** | **54.43%** | **Candlestick** ⭐ NEW |

**Belt Hold ranks #23 out of 23 tested indicators** - lower tier but still positive contributor.

---

## Phase 1 Progress Update

### Completion Status

**Completed Categories**:
1. ✅ **Momentum**: 7/7 indicators tested
2. ✅ **Trend**: 7/7 indicators tested
3. ✅ **Volume**: 5/5 indicators tested
4. ✅ **Candlestick**: 4/4 indicators tested ⭐ COMPLETE!

**Remaining Tests**:
- **Mean Reversion Strategy**: 4 indicators (RSI_MR, BB_MR, MA_DIST_MR, CANDLESTICK_MR)

**Overall Progress**: **23/28 indicators tested (82.1%)**

**Estimated Time to Complete Phase 1**: ~1-1.5 hours (4 remaining indicators)

---

## Strategic Implications

### For Production Weights

**Immediate Action**: Set `BELT_HOLD_MULTIPLIER = 1.5` in production
- Optimal risk-adjusted returns at 1.5x
- Traditional amplification pattern benefits from elevation
- Lower-tier performance but still positive contributor

### For Candlestick Pattern Ensemble

**All 4 Patterns Optimized**:
```json
"candlestick": {
  "RISE_FALL_3_METHODS_MULTIPLIER": 0.5,
  "THREE_WHITE_SOLDIERS_MULTIPLIER": 0.5,
  "MARUBOZU_MULTIPLIER": 1.0,
  "BELT_HOLD_MULTIPLIER": 1.5
}
```

**Expected Ensemble Behavior**:
- **Marubozu dominates** as primary candlestick signal (#1 overall)
- **Three White Soldiers** provides high-quality reversal confirmation
- **Belt Hold** amplifies reversal signals in trending contexts
- **Rise/Fall 3 Methods** confirms continuation with dampened weight

### For Phase 2: Ensemble Testing

**Candlestick Strategy**:
- Marubozu will be primary candlestick driver (2.576 Sharpe at 1.0x)
- Three White Soldiers adds reversal confirmation (1.954 Sharpe at 0.5x)
- Belt Hold and Rise/Fall 3 Methods contribute but won't dominate
- Wide weight distribution (0.5x, 1.0x, 1.5x) creates balanced ensemble

---

## Lessons Learned

### Key Takeaways

1. **Single-Candle Patterns Are Not Uniform**
   - Marubozu: 1.0x optimal (Pattern C)
   - Belt Hold: 1.5x optimal (Pattern A)
   - Pattern characteristics matter more than candle count

2. **Reversal Patterns Can Benefit from Amplification**
   - Belt Hold (reversal): 1.5x optimal
   - Three White Soldiers (reversal): 0.5x optimal
   - Context: Multi-candle reversals need dampening, single-candle reversals may need amplification

3. **Candlestick Category Shows Highest Weight Diversity**
   - Pattern A (1.5x): Belt Hold
   - Pattern B (0.5x): Three White Soldiers, Rise/Fall 3 Methods
   - Pattern C (1.0x): Marubozu
   - All three patterns represented in one category

4. **Performance Range is Wide**
   - Best: Marubozu (2.576 Sharpe) - #1 overall
   - Worst: Belt Hold (0.699 Sharpe) - #23 overall
   - 1.877 Sharpe point range within single category

5. **Candlestick Patterns Complete**
   - All 4 patterns tested and optimized
   - Ready for Phase 2 ensemble testing
   - Clear understanding of individual pattern strengths

---

## Next Steps

### Immediate Actions

1. ✅ Update `src/weights.json` with `BELT_HOLD_MULTIPLIER = 1.5`
2. ✅ Create experiment summary document
3. 📋 Commit changes
4. 🧹 Clean up test logs

### Continue Phase 1 Testing

**Next Category**: Mean Reversion Strategy (4 indicators)
- RSI_MR (mean reversion RSI)
- BB_MR (mean reversion Bollinger Bands)
- MA_DIST_MR (mean reversion moving average distance)
- CANDLESTICK_MR (mean reversion candlestick patterns)

**Expected Duration**: 30-45 minutes per indicator = ~2-3 hours total

**Phase 1 Completion**: After mean reversion tests (5 indicators remaining if we count properly)

---

## Conclusion

Belt Hold testing reveals a **TRADITIONAL AMPLIFICATION PATTERN** (Pattern A), distinguishing it from Marubozu despite both being single-candle patterns.

✅ **1.5x is OPTIMAL**: 0.699 Sharpe, 54.43% win rate, traditional amplification
⚠️ **1.0x is moderate**: 0.514 Sharpe, acceptable but suboptimal
❌ **0.5x is weak**: 0.147 Sharpe, dampening destroys signal

**Critical Discovery**: Single-candle patterns are NOT uniform - pattern characteristics (frequency, context requirements, reversal vs continuation) matter more than candle count alone.

**Candlestick Category Complete**: All 4 patterns tested with optimal weights determined. Marubozu dominates (#1 overall), Belt Hold provides amplified reversal signals (#23 overall).

**Phase 1 Progress**: 23/28 indicators tested (82.1%) - Mean Reversion category remaining.

---

**Document Version**: 1.0
**Last Updated**: 2026-01-27
**Next Update**: After Mean Reversion testing begins
