# Heiken Ashi Experiment Summary

## Overview
Heiken Ashi (Japanese for "average bar") is a modified candlestick charting technique that uses averaged open, high, low, and close values to smooth price data and filter market noise. Unlike standard candlesticks that show raw price movements, Heiken Ashi candles incorporate previous bar data to create a smoother, more continuous representation of trends. This experiment tested Heiken Ashi at three weight configurations to determine optimal influence on baseline strategy scores.

## Experiment Configurations

### Test 1: Heiken Ashi Reduced (0.5x)
**Configuration:** `HEIKEN_ASHI_MULTIPLIER = 0.5`

**Results:**
- **Win Rate:** 48.81%
- **Average P&L:** +0.04%
- **Sharpe Ratio:** 0.072
- **Max Drawdown:** 43.83%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At reduced weight, Heiken Ashi barely breaks even with 0.072 Sharpe. The 0.5x dampening suppresses the smoothing benefits too much, resulting in near-random performance (48.81% win rate barely above coin flip) with significant 43.83% drawdown.

### Test 2: Heiken Ashi Baseline (1.0x)
**Configuration:** `HEIKEN_ASHI_MULTIPLIER = 1.0`

**Results:**
- **Win Rate:** 47.19%
- **Average P&L:** +0.49%
- **Sharpe Ratio:** 0.930
- **Max Drawdown:** 29.63%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At baseline weight, Heiken Ashi shows moderate improvement with 0.930 Sharpe. However, the below-50% win rate (47.19%) indicates the smoothing isn't strong enough to consistently identify quality setups at standard weight.

### Test 3: Heiken Ashi Boosted (1.5x) - OPTIMAL ✓
**Configuration:** `HEIKEN_ASHI_MULTIPLIER = 1.5`

**Results:**
- **Win Rate:** 63.10%
- **Average P&L:** +1.03%
- **Sharpe Ratio:** 2.039 (#4 OVERALL!)
- **Max Drawdown:** 14.65% (BEST IN PHASE 1!)
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At boosted weight, Heiken Ashi transforms into an elite performer with 2.039 Sharpe, ranking #4 overall. The +1.03% average gain and exceptional 63.10% win rate demonstrate superior trend identification. **Outstanding 14.65% drawdown is the BEST in all Phase 1 testing**, showcasing Heiken Ashi's smoothing excellence for risk control.

## Comparative Analysis

| Metric | 0.5x | 1.0x | 1.5x (Winner) |
|--------|------|------|---------------|
| Win Rate | 48.81% | 47.19% | **63.10%** |
| Avg P&L | +0.04% | +0.49% | **+1.03%** |
| Sharpe Ratio | 0.072 | 0.930 | **2.039** |
| Max Drawdown | 43.83% | 29.63% | **14.65%** |

**Key Insight:** Massive performance improvement from 0.5x → 1.5x. Sharpe ratio improves 28x from 0.5x to 1.5x, while drawdown is cut by 67%. The non-linear improvement demonstrates that Heiken Ashi's smoothing benefits require sufficient amplification to overcome signal lag inherent in averaged calculations.

## Pattern Recognition: Smoothing Indicators Need Amplification

Heiken Ashi joins the "elevation required" category at 1.5x optimal weight:

**Elevation Required (1.5x optimal):**
- **Heiken Ashi (1.5x):** 2.039 Sharpe - Averaged candlestick smoothing (NEW - #4!)
- **PSAR (1.5x):** 1.703 Sharpe - Trailing stop and trend reversal
- **BB (1.5x):** 1.647 Sharpe - Volatility bands, normalized percentile
- **Williams %R (1.5x):** 1.647 Sharpe - Bounded momentum oscillator
- **MFI (1.5x):** 1.612 Sharpe - Volume-weighted momentum
- **Ichimoku (1.5x):** 1.535 Sharpe - Multi-component trend system
- **CMF (1.5x):** 1.200 Sharpe - Money flow accumulation

**Why Smoothing Indicators Need Amplification:**

Heiken Ashi's design inherently trades immediacy for clarity:
1. **Averaging lag:** Uses previous bar data, creating inherent delay
2. **Signal smoothness:** Reduces noise but also dulls sharp reversals
3. **Trend continuity:** Emphasizes sustained moves over quick pivots
4. **Visual clarity:** Optimized for human interpretation, not raw signal strength

In a multi-indicator ensemble with real-time indicators (RSI, MACD, Stochastic), Heiken Ashi's lagging smoothed signals get drowned out at 1.0x. The 1.5x amplification compensates by:
- Elevating smoothed trend confirmations to match fast indicators' signal strength
- Ensuring averaged candle patterns have meaningful impact on scoring
- Balancing lag disadvantage with stronger conviction when trends are confirmed

## Phase 1 Rankings (After 17 Indicators)

1. **RSI (1.0x):** 2.467 Sharpe 🥇
2. **OBV (1.0x):** 2.379 Sharpe 🥈
3. **Stochastic (1.0x):** 2.047 Sharpe 🥉
4. **Heiken Ashi (1.5x):** 2.039 Sharpe (NEW - #4!) ⭐
5. **CCI (0.5x):** 2.024 Sharpe
6. **ROC (1.0x):** 1.911 Sharpe
7. **PSAR (1.5x):** 1.703 Sharpe
8. **BB (1.5x):** 1.647 Sharpe (tied)
8. **Williams %R (1.5x):** 1.647 Sharpe (tied)
10. **MFI (1.5x):** 1.612 Sharpe
11. **ATR_BAND (0.5x):** 1.549 Sharpe
12. **Ichimoku (1.5x):** 1.535 Sharpe
13. **CMF (1.5x):** 1.200 Sharpe
14. **MACD (0.5x):** 1.146 Sharpe
15. **ADX (2.0x):** 0.738 Sharpe

**Failed:**
16. **ATR_SPIKE (0.0x):** -0.271 Sharpe (disabled)

**Heiken Ashi ranks #4 overall** with elite 2.039 Sharpe! This bumps CCI from #4 to #5. Heiken Ashi barely trails Stochastic's bronze-medal 2.047 Sharpe, making it a top-tier indicator just outside the podium.

## Trend Category Progress

**Trend Indicators (5 of 7 tested):**

| Indicator | Optimal Weight | Sharpe | Rank | Status |
|-----------|---------------|--------|------|--------|
| Stochastic | 1.0x | 2.047 | #3 | ✅ Bronze |
| Heiken Ashi | 1.5x | 2.039 | #4 | ✅ Elite (NEW) ⭐ |
| PSAR | 1.5x | 1.703 | #7 | ✅ Strong |
| Ichimoku | 1.5x | 1.535 | #12 | ✅ Solid |
| ADX | 2.0x | 0.738 | #15 | ✅ Weak |
| Donchian | TBD | TBD | TBD | ⏳ Next |
| SuperTrend | TBD | TBD | TBD | ⏳ Pending |

**Trend category insights (5 tested):**
- Excellent performance range: 0.738 to 2.047 Sharpe
- **2 of 5 in top 5 overall** (Stochastic #3, Heiken Ashi #4)
- Strong average: 1.605 Sharpe across 5 tested (excellent category showing)
- **4 of 5 require amplification** (Heiken Ashi 1.5x, PSAR 1.5x, Ichimoku 1.5x, ADX 2.0x)
- Only Stochastic works naturally at 1.0x

**Trend category is proving ELITE** - 2 podium/near-podium finishers from 5 tested!

## Recommendation

**Set `HEIKEN_ASHI_MULTIPLIER = 1.5` in production weights.json**

**Rationale:**
1. **Elite performance:** 2.039 Sharpe ranks #4 overall (near podium)
2. **Best risk control:** 14.65% max drawdown is THE BEST in all Phase 1 testing
3. **High win rate:** 63.10% shows exceptional trade selection quality
4. **Strong profitability:** +1.03% average gain per trade
5. **Dramatic improvement:** From 0.072 Sharpe at 0.5x to 2.039 at 1.5x (28x gain!)
6. **Smoothing value:** Provides unique noise filtering that complements fast indicators
7. **Risk-adjusted excellence:** Delivers near-bronze performance with best drawdown control

The 1.5x weight transforms Heiken Ashi from mediocre (0.930 Sharpe at 1.0x) into elite territory (#4 overall).

## Technical Context

**Heiken Ashi Calculation:**

Unlike standard candlesticks that use actual OHLC values, Heiken Ashi candles use modified formulas incorporating previous bar data:

```
HA_Close = (Open + High + Low + Close) / 4

HA_Open = (Previous HA_Open + Previous HA_Close) / 2

HA_High = Max(High, HA_Open, HA_Close)

HA_Low = Min(Low, HA_Open, HA_Close)
```

**Key Properties:**
- **Smoothing effect:** Averaging reduces noise and false signals
- **Trend continuation:** Consecutive same-color candles are more common
- **No gaps:** HA_Open always at midpoint of previous HA bar (no opening gaps)
- **Modified wicks:** HA_High/Low may differ significantly from actual High/Low

**Traditional Interpretation:**
- **Green/white candles:** Uptrend (HA_Close > HA_Open)
- **Red/black candles:** Downtrend (HA_Close < HA_Open)
- **Small body, long lower wick:** Potential reversal from downtrend
- **Small body, long upper wick:** Potential reversal from uptrend
- **No lower wick:** Strong bullish momentum
- **No upper wick:** Strong bearish momentum

**Baseline Strategy Application:**
Heiken Ashi contributes to trend scoring in the baseline (trend-following) strategy by:
1. Rewarding consecutive bullish HA candles (trend confirmation)
2. Penalizing trend reversals (HA color changes)
3. Measuring trend strength via HA candle body size
4. Identifying momentum exhaustion via HA wick patterns
5. Filtering noise that plagues raw candlestick analysis

The 1.5x multiplier ensures Heiken Ashi's smoothed, lagging signals carry appropriate weight alongside real-time indicators (RSI, Stochastic, ROC) and other trend indicators (PSAR, Ichimoku, ADX).

## Strategic Insights

**Heiken Ashi's Unique Value:**

Heiken Ashi is the first **pure smoothing** indicator tested in Phase 1 that modifies price visualization itself:
- **Noise reduction:** Filters market "chop" that causes whipsaws
- **Trend clarity:** Makes sustained moves easier to identify
- **Lag trade-off:** Accepts slight delay for improved signal quality
- **Visual continuity:** Creates cleaner patterns than raw candles

This makes Heiken Ashi particularly valuable for:
- **Trend confirmation:** Validates trends identified by faster indicators
- **False signal reduction:** Smoothing eliminates many fake breakouts
- **Momentum assessment:** Candle body size shows trend strength
- **Risk management:** Cleaner signals = better entry/exit timing

**Heiken Ashi vs Other Trend Indicators:**

| Indicator | Type | Optimal Weight | Sharpe | Rank |
|-----------|------|---------------|--------|------|
| Stochastic | Momentum oscillator | 1.0x | 2.047 | #3 |
| Heiken Ashi | Smoothed candles | 1.5x | 2.039 | #4 |
| PSAR | Trailing stop | 1.5x | 1.703 | #7 |
| Ichimoku | Multi-component cloud | 1.5x | 1.535 | #12 |
| ADX | Trend strength | 2.0x | 0.738 | #15 |

**Key Differences:**
- **Stochastic:** Measures momentum extremes, fastest signals
- **Heiken Ashi:** Smooths price itself, moderate lag
- **PSAR:** Provides stop levels, moderate lag
- **Ichimoku:** Comprehensive structure, high lag
- **ADX:** Measures strength only (no direction), no lag

Heiken Ashi sits in the middle - slower than Stochastic but faster than Ichimoku, providing balanced trend confirmation.

**Complementary with Stochastic:**
Using both in Phase 2 ensemble provides:
- **Stochastic:** Fast momentum signals, overbought/oversold detection
- **Heiken Ashi:** Smoothed trend confirmation, noise filtering
- Together they provide both immediacy (Stochastic) and clarity (Heiken Ashi)

## Why 1.5x Works for Heiken Ashi

**The Smoothing Penalty:**

Heiken Ashi's strength (noise reduction) is also its weakness (lag). Key challenges:
1. **Delayed signals:** Averaging previous bar data means Heiken Ashi "sees" trends later than raw prices
2. **Muted extremes:** Smoothing reduces both noise AND legitimate sharp moves
3. **Momentum dampening:** Trend reversals appear more gradual on HA charts
4. **Lower volatility:** HA ranges are typically smaller than actual OHLC ranges

In a multi-indicator ensemble with real-time indicators, these penalties create a **signal strength deficit**:
- RSI, Stochastic, ROC see reversals immediately → strong signals
- Heiken Ashi sees reversals with 1-2 bar delay → weak signals at 1.0x
- Result: HA confirmations arrive late and score too low to matter

**The 1.5x Fix:**

Amplification compensates for smoothing lag:
- When HA confirms a trend, the 1.5x weight makes that confirmation meaningful
- Fast indicators get the entry, HA provides continuation confidence
- HA's lower false positive rate justifies higher weight per signal
- Balances "late but reliable" against "early but noisy"

## Transformation Analysis: From Weak to Elite

**Heiken Ashi's Performance Journey:**
- **0.5x:** 0.072 Sharpe (near-zero returns)
- **1.0x:** 0.930 Sharpe (mediocre)
- **1.5x:** 2.039 Sharpe (elite - #4!)

**What Changes at 1.5x?**

At low weights, Heiken Ashi's lag is fatal:
- Fast indicators (RSI, Stochastic) identify trends first → high scores
- Heiken Ashi confirms 1-2 bars later → low scores (too late)
- By the time HA signals strongly, opportunity is missed
- System trades on fast signals, ignores lagging HA confirmations

At 1.5x weight, Heiken Ashi's confirmations finally matter:
- Fast indicators still spot trends first (entry trigger)
- Heiken Ashi confirms 1-2 bars later (continuation filter)
- 1.5x weight makes HA confirmation boost score meaningfully
- System holds winners longer when HA confirms trend remains intact

**Result:** Lower win rate (63% vs RSI's 59%) but MUCH better risk control (14.65% drawdown vs RSI's 27.47%).

## Risk-Adjusted Performance Leaders

**Best Risk-Adjusted (Sharpe ÷ Drawdown):**
1. **Heiken Ashi (1.5x):** 2.039 Sharpe ÷ 14.65% DD = **13.92 efficiency** ⭐ BEST!
2. **Stochastic (1.0x):** 2.047 Sharpe ÷ 16.53% DD = 12.38 efficiency
3. **PSAR (1.5x):** 1.703 Sharpe ÷ 18.35% DD = 9.28 efficiency
4. **Williams %R (1.5x):** 1.647 Sharpe ÷ 20.19% DD = 8.16 efficiency
5. **BB (1.5x):** 1.647 Sharpe ÷ 22.59% DD = 7.29 efficiency

**Heiken Ashi wins the risk-adjusted efficiency crown!** Despite ranking #4 in raw Sharpe, its exceptional drawdown control makes it THE most efficient performer in Phase 1.

## Highest Win Rates (Top 5)

1. **OBV (1.0x):** 63.17% win rate, 2.379 Sharpe
2. **Heiken Ashi (1.5x):** 63.10% win rate, 2.039 Sharpe ⭐
3. **PSAR (1.5x):** 62.92% win rate, 1.703 Sharpe
4. **CCI (0.5x):** 60.68% win rate, 2.024 Sharpe
5. **ROC (1.0x):** 60.49% win rate, 1.911 Sharpe

Heiken Ashi ranks #2 in win rate (tied with OBV), showing exceptional trade selection quality!

## Next Steps

**Trend Category Progress: 5/7 Complete**

**Remaining Trend Indicators:**
- Donchian (channel breakouts - price envelope)
- SuperTrend (ATR-based trend following)

**Other Remaining Categories:**
- **Candlestick (4 patterns):** RISE_FALL_3_METHODS, THREE_WHITE_SOLDIERS, MARUBOZU, BELT_HOLD
- **Mean Reversion indicators:** RSI, BB, MA_DIST, CANDLESTICK (separate strategy)

**Suggested Next Steps:**
- Continue trend category testing with Donchian
- Complete final trend indicator (SuperTrend)
- Proceed to candlestick pattern testing
- Complete all 40+ indicators in Phase 1
- Proceed to Phase 2 ensemble optimization

## Files Generated
- `heiken_ashi_reduced.log` (0.5x test output)
- `heiken_ashi_baseline.log` (1.0x test output)
- `heiken_ashi_boosted.log` (1.5x test output)
- `src/experiments/results/heiken_ashi_reduced.json`
- `src/experiments/results/heiken_ashi_baseline.json`
- `src/experiments/results/heiken_ashi_boosted.json`

---

**Experiment Date:** 2026-01-27
**Branch:** Tweak_indicators
**Commit:** [To be added]
**Achievement:** Heiken Ashi ranks #4 overall with elite 2.039 Sharpe AND the best drawdown control (14.65%) in all Phase 1 testing! Smoothed candle technique requires 1.5x amplification to shine.
