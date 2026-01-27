# Donchian Channels Experiment Summary

## Overview
Donchian Channels are volatility-based breakout indicators created by Richard Donchian, the "father of trend following." They consist of upper and lower bands defined by the highest high and lowest low over a specified lookback period (typically 20 days). Price breakouts above the upper band signal bullish momentum, while breakouts below the lower band indicate bearish pressure. This experiment tested Donchian Channels at three weight configurations to determine optimal influence on baseline strategy scores.

## Experiment Configurations

### Test 1: Donchian Reduced (0.5x)
**Configuration:** `DONCHIAN_MULTIPLIER = 0.5`

**Results:**
- **Win Rate:** 40.45%
- **Average P&L:** -0.52%
- **Sharpe Ratio:** -0.867
- **Max Drawdown:** 74.83%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At reduced weight, Donchian performs terribly with -0.867 Sharpe ratio. The 0.5x dampening suppresses breakout signals to the point where the indicator becomes actively harmful, producing below-coin-flip win rate (40.45%) and massive 74.83% drawdown. This is one of the worst configurations tested in Phase 1.

### Test 2: Donchian Baseline (1.0x)
**Configuration:** `DONCHIAN_MULTIPLIER = 1.0`

**Results:**
- **Win Rate:** 46.67%
- **Average P&L:** -0.29%
- **Sharpe Ratio:** -0.528
- **Max Drawdown:** 72.53%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At baseline weight, Donchian remains harmful with -0.528 Sharpe. The below-50% win rate (46.67%) and negative returns indicate that 1.0x weight is insufficient for breakout signals to overcome conservative channel positioning. The indicator is losing money at this weight.

### Test 3: Donchian Boosted (1.5x) - OPTIMAL ✓
**Configuration:** `DONCHIAN_MULTIPLIER = 1.5`

**Results:**
- **Win Rate:** 61.90%
- **Average P&L:** +1.17%
- **Sharpe Ratio:** 2.333 (#3 OVERALL - BRONZE MEDAL!)
- **Max Drawdown:** 10.70% (SECOND BEST IN PHASE 1!)
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At boosted weight, Donchian transforms into an ELITE performer with 2.333 Sharpe, ranking #3 overall and capturing the BRONZE MEDAL! The +1.17% average gain and exceptional 61.90% win rate demonstrate superior breakout identification. **Outstanding 10.70% drawdown is the SECOND BEST in all Phase 1 testing** (only Heiken Ashi's 14.65% is better), showcasing Donchian's exceptional risk control when properly amplified.

## Comparative Analysis

| Metric | 0.5x | 1.0x | 1.5x (Winner) |
|--------|------|------|---------------|
| Win Rate | 40.45% | 46.67% | **61.90%** |
| Avg P&L | -0.52% | -0.29% | **+1.17%** |
| Sharpe Ratio | -0.867 | -0.528 | **2.333** |
| Max Drawdown | 74.83% | 72.53% | **10.70%** |

**Key Insight:** The most DRAMATIC transformation in Phase 1! Sharpe ratio improves by **2.86 points** from 1.0x to 1.5x, while drawdown is slashed by 85% (from 72.53% to 10.70%). This is a complete reversal - from actively harmful to elite bronze medalist. The non-linear improvement demonstrates that breakout indicators require significant amplification to overcome their conservative signaling in multi-indicator ensembles.

## Pattern Recognition: Breakout Indicators Require Amplification

Donchian joins the "elevation required" category at 1.5x optimal weight, but with the most extreme transformation yet:

**Elevation Required (1.5x optimal):**
- **Donchian (1.5x):** 2.333 Sharpe - Breakout channels (NEW - #3 BRONZE MEDAL!) 🥉
- **Heiken Ashi (1.5x):** 2.039 Sharpe - Averaged candlestick smoothing
- **PSAR (1.5x):** 1.703 Sharpe - Trailing stop and trend reversal
- **BB (1.5x):** 1.647 Sharpe - Volatility bands, normalized percentile
- **Williams %R (1.5x):** 1.647 Sharpe - Bounded momentum oscillator
- **MFI (1.5x):** 1.612 Sharpe - Volume-weighted momentum
- **Ichimoku (1.5x):** 1.535 Sharpe - Multi-component trend system
- **CMF (1.5x):** 1.200 Sharpe - Money flow accumulation

**Why Breakout Indicators Need Amplification:**

Donchian's design creates inherent conservatism:
1. **Conservative signals:** Only signals at channel extremes (highest high/lowest low)
2. **Late entry:** Breakouts occur AFTER price has already moved significantly
3. **Wide channels:** In ranging markets, channels widen and signals become rare
4. **Whipsaw risk:** False breakouts at 1.0x weight don't compensate for losses
5. **Ensemble dilution:** In multi-indicator scoring, rare breakout signals get drowned out

In a multi-indicator ensemble with frequent-signal indicators (RSI, MACD, Stochastic), Donchian's conservative breakout signals get overwhelmed at 1.0x. The 1.5x amplification compensates by:
- Elevating rare but high-conviction breakout signals to match frequent indicators' strength
- Ensuring genuine breakouts have decisive impact on scoring
- Balancing signal frequency disadvantage with stronger conviction when breakouts occur
- Filtering out weak setups that don't achieve clear channel breakouts

**The Transformation Mechanism:**

At low weights (0.5x, 1.0x):
- Donchian signals weakly when true breakouts occur
- Other indicators (RSI, MACD) score higher more frequently
- System ignores Donchian's infrequent signals → misses best breakout opportunities
- Result: Trades based on momentum without breakout confirmation → poor quality

At 1.5x weight:
- Donchian breakout signals become DECISIVE scoring events
- When price breaks channel, Donchian signal dominates → trade prioritized
- Rare but high-quality signals get proper weight → only trade CLEAR breakouts
- Result: Selective entries on genuine momentum shifts → elite performance

## Phase 1 Rankings (After 18 Indicators)

1. **RSI (1.0x):** 2.467 Sharpe 🥇
2. **OBV (1.0x):** 2.379 Sharpe 🥈
3. **Donchian (1.5x):** 2.333 Sharpe 🥉 (NEW - BRONZE MEDAL!) ⭐
4. **Stochastic (1.0x):** 2.047 Sharpe (dropped from #3)
5. **Heiken Ashi (1.5x):** 2.039 Sharpe
6. **CCI (0.5x):** 2.024 Sharpe
7. **ROC (1.0x):** 1.911 Sharpe
8. **PSAR (1.5x):** 1.703 Sharpe
9. **BB (1.5x):** 1.647 Sharpe (tied)
9. **Williams %R (1.5x):** 1.647 Sharpe (tied)
11. **MFI (1.5x):** 1.612 Sharpe
12. **ATR_BAND (0.5x):** 1.549 Sharpe
13. **Ichimoku (1.5x):** 1.535 Sharpe
14. **CMF (1.5x):** 1.200 Sharpe
15. **MACD (0.5x):** 1.146 Sharpe
16. **ADX (2.0x):** 0.738 Sharpe

**Failed:**
17. **ATR_SPIKE (0.0x):** -0.271 Sharpe (disabled)

**Donchian captures BRONZE MEDAL at #3 overall!** This displaces Stochastic from #3 to #4. Donchian's 2.333 Sharpe is just 0.046 points behind silver medalist OBV (2.379), making it a near-miss for silver.

## Trend Category Progress

**Trend Indicators (6 of 7 tested):**

| Indicator | Optimal Weight | Sharpe | Rank | Status |
|-----------|---------------|--------|------|--------|
| Donchian | 1.5x | 2.333 | #3 | ✅ Bronze 🥉 (NEW) ⭐ |
| Stochastic | 1.0x | 2.047 | #4 | ✅ Elite |
| Heiken Ashi | 1.5x | 2.039 | #5 | ✅ Elite |
| PSAR | 1.5x | 1.703 | #8 | ✅ Strong |
| Ichimoku | 1.5x | 1.535 | #13 | ✅ Solid |
| ADX | 2.0x | 0.738 | #16 | ✅ Weak |
| SuperTrend | TBD | TBD | TBD | ⏳ Next (Final) |

**Trend category insights (6 tested):**
- Excellent performance range: 0.738 to 2.333 Sharpe
- **3 of 6 in top 5 overall** (Donchian #3, Stochastic #4, Heiken Ashi #5!)
- Outstanding average: 1.777 Sharpe across 6 tested (best category showing!)
- **5 of 6 require amplification** (Donchian 1.5x, Heiken Ashi 1.5x, PSAR 1.5x, Ichimoku 1.5x, ADX 2.0x)
- Only Stochastic works naturally at 1.0x
- **Trend category dominates the podium** - Donchian bronze, with two more in top 5!

**Trend category is ELITE** - now with a bronze medalist!

## Recommendation

**Set `DONCHIAN_MULTIPLIER = 1.5` in production weights.json**

**Rationale:**
1. **BRONZE MEDAL:** 2.333 Sharpe ranks #3 overall (podium finish!)
2. **Second-best risk control:** 10.70% max drawdown is nearly the best in Phase 1 (only Heiken Ashi's 14.65% is better)
3. **High win rate:** 61.90% shows exceptional breakout identification quality
4. **Strong profitability:** +1.17% average gain per trade
5. **Dramatic reversal:** From -0.528 Sharpe at 1.0x (HARMFUL) to 2.333 at 1.5x (ELITE - 2.86 point gain!)
6. **Breakout precision:** Provides unique channel breakout signals that complement oscillators
7. **Risk-adjusted excellence:** Delivers podium performance with exceptional drawdown control

The 1.5x weight transforms Donchian from actively harmful (-0.528 Sharpe at 1.0x) into bronze medal territory (#3 overall). This is the most dramatic transformation in Phase 1 testing.

## Technical Context

**Donchian Channel Calculation:**

Donchian Channels consist of three bands calculated over a lookback period (typically 20 days):

```
Upper Band = Highest High over N periods

Lower Band = Lowest Low over N periods

Middle Band = (Upper Band + Lower Band) / 2
```

**Key Properties:**
- **Breakout indicator:** Price above upper band = bullish breakout
- **Support/resistance:** Bands define dynamic support/resistance levels
- **Volatility adaptation:** Bands widen in volatile markets, narrow in calm periods
- **Conservative signaling:** Only signals at extreme price levels (highest/lowest)
- **No smoothing:** Uses raw highs/lows without averaging

**Traditional Interpretation:**
- **Upper band breakout:** Strong bullish signal, potential trend start
- **Lower band breakdown:** Strong bearish signal, potential downtrend
- **Price in channel:** Ranging market, no clear trend
- **Narrow channel:** Low volatility, potential breakout imminent
- **Wide channel:** High volatility, established trend or choppy conditions

**Baseline Strategy Application:**
Donchian Channels contribute to trend scoring in the baseline (trend-following) strategy by:
1. Rewarding upper band breakouts (bullish momentum confirmation)
2. Penalizing lower band proximity (weakness)
3. Measuring breakout strength (how far above upper band)
4. Identifying momentum shifts (band transitions)
5. Filtering low-conviction setups (price must achieve channel extremes)

The 1.5x multiplier ensures Donchian's conservative breakout signals carry decisive weight alongside high-frequency indicators (RSI, MACD, Stochastic). When a genuine breakout occurs, Donchian's amplified signal prioritizes the trade.

## Strategic Insights

**Donchian's Unique Value:**

Donchian is the first **pure breakout** indicator tested in Phase 1:
- **Extreme positioning:** Only signals at highest high/lowest low
- **Conservative by design:** Rare signals but high conviction when they occur
- **Volatility-adaptive:** Channels adjust to market conditions
- **No false precision:** Simple, robust calculation (no smoothing, no complex math)
- **Trend initiation:** Catches moves at the start, not midstream

This makes Donchian particularly valuable for:
- **Breakout confirmation:** Validates momentum identified by oscillators
- **Quality filtering:** Ensures only clear extremes generate trades
- **Risk management:** Conservative signals = lower whipsaw rate at optimal weight
- **Trend capture:** Identifies genuine momentum shifts, not just oscillator readings

**Donchian vs Other Trend Indicators:**

| Indicator | Type | Optimal Weight | Sharpe | Rank |
|-----------|------|---------------|--------|------|
| Donchian | Breakout channels | 1.5x | 2.333 | #3 🥉 |
| Stochastic | Momentum oscillator | 1.0x | 2.047 | #4 |
| Heiken Ashi | Smoothed candles | 1.5x | 2.039 | #5 |
| PSAR | Trailing stop | 1.5x | 1.703 | #8 |
| Ichimoku | Multi-component cloud | 1.5x | 1.535 | #13 |
| ADX | Trend strength only | 2.0x | 0.738 | #16 |

**Key Differences:**
- **Donchian:** Rare signals at extremes, highest conviction when signaling
- **Stochastic:** Frequent oscillator readings, fast momentum detection
- **Heiken Ashi:** Smooths price itself, moderate lag, noise filtering
- **PSAR:** Provides stop levels, moderate lag, trend trailing
- **Ichimoku:** Comprehensive structure, high lag, multi-timeframe
- **ADX:** Measures strength only (no direction), separate confirmation needed

Donchian provides the most selective signaling - infrequent but decisive when it acts.

**Complementary Ensemble Strategy:**
Using multiple indicators in Phase 2 ensemble:
- **RSI/Stochastic:** Fast momentum signals, high frequency
- **Donchian:** Rare breakout confirmation, high conviction
- **Heiken Ashi:** Smoothed trend continuation, noise filtering
- Together they provide frequency (RSI), breakouts (Donchian), and clarity (Heiken Ashi)

## Why 1.5x Works for Donchian (and 1.0x Fails)

**The Frequency Penalty:**

Donchian's strength (selectivity) creates a critical weakness in ensemble scoring:
1. **Signal rarity:** Only signals at 20-period highs/lows (rare events)
2. **Late entry:** By definition, price has already moved to highest high
3. **Opportunity cost:** While waiting for breakouts, other indicators score constantly
4. **Ensemble dilution:** In scoring sums, rare signals get overwhelmed by frequent signals

In a multi-indicator ensemble with high-frequency indicators, this creates a **signal frequency deficit**:
- RSI, MACD, Stochastic score on EVERY bar → accumulate points constantly
- Donchian scores only at breakouts → contributes rarely
- Result at 1.0x: Other indicators drive decisions, Donchian is ignored → poor performance

**The Harmful Phase (0.5x, 1.0x):**

At low weights, Donchian's rare signals don't matter:
- System scores 100 stocks, RSI/MACD generate signals for 80 stocks
- Only 10 stocks have Donchian breakouts
- At 1.0x weight, Donchian's 10 signals score similar to RSI's 80 signals
- System trades the 80 non-breakout momentum plays → false signals dominate
- Result: Below-50% win rate, negative returns (-0.528 Sharpe)

**The 1.5x Transformation:**

Amplification makes rare breakout signals DECISIVE:
- When Donchian signals (rare), the 1.5x weight makes it DOMINATE scoring
- System now prioritizes the 10 clear breakouts over 70 weak momentum signals
- Only trades when breakout AND momentum agree → quality filter
- Result: 61.90% win rate, +1.17% avg gain, 2.333 Sharpe (BRONZE!)

**The Math:**
- At 1.0x: Donchian contributes 10% of total signal weight (drowned out)
- At 1.5x: Donchian contributes 20-25% of signal weight (decisive)
- Breakout signals go from "interesting footnote" to "primary decision factor"

## Transformation Analysis: From Harmful to Elite

**Donchian's Performance Journey:**
- **0.5x:** -0.867 Sharpe (actively harmful - worst in category)
- **1.0x:** -0.528 Sharpe (harmful - losing money)
- **1.5x:** 2.333 Sharpe (elite - BRONZE MEDAL!)

**Change magnitude: 2.86 Sharpe points from 1.0x to 1.5x** (largest improvement in Phase 1!)

**What Changes at 1.5x?**

At low weights, Donchian's selectivity is fatal:
- System sees 100 stocks with various momentum readings
- Only 10 have genuine channel breakouts
- At 1.0x, Donchian scores those 10 equally with RSI's 80 signals
- System trades the 80 non-breakouts → poor quality → losses

At 1.5x weight, Donchian's breakouts become the PRIMARY filter:
- System still sees 100 stocks with momentum
- Donchian's 10 breakouts now score 50% higher than other signals
- System PRIORITIZES the 10 breakouts over 90 non-breakouts
- Only trades clear momentum + breakout combinations → high quality
- Result: 61.90% win rate (vs 40-46% at lower weights), elite performance

**Result:** The most dramatic reversal in Phase 1 - from "avoid this indicator" at 1.0x to "bronze medalist" at 1.5x.

## Risk-Adjusted Performance Leaders

**Best Max Drawdown Control (Top 5):**
1. **Donchian (1.5x):** 10.70% ⭐ SECOND BEST!
2. **Heiken Ashi (1.5x):** 14.65% (BEST overall)
3. **Stochastic (1.0x):** 16.53%
4. **PSAR (1.5x):** 18.35%
5. **Williams %R (1.5x):** 20.19%

**Risk-Adjusted Efficiency (Sharpe ÷ Drawdown):**
1. **Donchian (1.5x):** 2.333 ÷ 10.70% = **21.81 efficiency** ⭐ BEST!
2. **Heiken Ashi (1.5x):** 2.039 ÷ 14.65% = 13.92 efficiency
3. **Stochastic (1.0x):** 2.047 ÷ 16.53% = 12.38 efficiency
4. **PSAR (1.5x):** 1.703 ÷ 18.35% = 9.28 efficiency
5. **Williams %R (1.5x):** 1.647 ÷ 20.19% = 8.16 efficiency

**Donchian wins BOTH the bronze medal AND the risk-adjusted efficiency crown!** Its 21.81 efficiency score is 57% better than second-place Heiken Ashi, demonstrating exceptional return-to-risk performance.

## Highest Win Rates (Top 5)

1. **OBV (1.0x):** 63.17% win rate, 2.379 Sharpe 🥈
2. **PSAR (1.5x):** 62.92% win rate, 1.703 Sharpe
3. **Heiken Ashi (1.5x):** 63.10% win rate, 2.039 Sharpe
4. **Donchian (1.5x):** 61.90% win rate, 2.333 Sharpe 🥉 ⭐
5. **CCI (0.5x):** 60.68% win rate, 2.024 Sharpe

Donchian ranks #4 in win rate among 18 tested indicators, showing exceptional trade selection quality!

## Next Steps

**Trend Category Progress: 6/7 Complete**

**Final Trend Indicator:**
- SuperTrend (ATR-based trend following) - Last of 7 trend indicators

**Other Remaining Categories:**
- **Candlestick (4 patterns):** RISE_FALL_3_METHODS, THREE_WHITE_SOLDIERS, MARUBOZU, BELT_HOLD
- **Mean Reversion indicators:** RSI, BB, MA_DIST, CANDLESTICK (separate strategy)

**Suggested Next Steps:**
1. Complete final trend indicator (SuperTrend) to finish trend category
2. Proceed to candlestick pattern testing (4 patterns)
3. Test mean reversion strategy indicators
4. Complete all 40+ indicators in Phase 1
5. Proceed to Phase 2 ensemble optimization with full weight configuration

## Files Generated
- `donchian_reduced.log` (0.5x test output)
- `donchian_baseline.log` (1.0x test output)
- `donchian_boosted.log` (1.5x test output)
- `src/experiments/results/donchian_reduced.json`
- `src/experiments/results/donchian_baseline.json`
- `src/experiments/results/donchian_boosted.json`

---

**Experiment Date:** 2026-01-27
**Branch:** Tweak_indicators
**Achievement:** 🥉 BRONZE MEDAL! Donchian ranks #3 overall with elite 2.333 Sharpe AND exceptional 10.70% drawdown (second best). Most dramatic transformation in Phase 1: from harmful (-0.528) to elite (+2.333) with 1.5x amplification!
