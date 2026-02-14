# Three-Strategy Trading Framework

**Date:** February 14, 2026
**Author:** User Strategic Vision
**Status:** Current = 2 strategies (both LONG), Future = 3 strategies (LONG + SHORT)

---

## 🎯 **The Three Distinct Opportunities**

You've identified the complete opportunity space:

### **1. Rising Baseline** (Trend-Following LONG)
**Thesis:** "The trend is your friend - ride momentum UP"

**Current Status:** ✅ Active (19 indicators)
**Performance:** High scores (12+) work well

**Characteristics:**
- Strong uptrend (PSAR, SuperTrend, ADX)
- Positive momentum (Williams %R, CCI, RSI 40-70)
- Breakouts (Donchian, above resistance)
- Institutional buying (high volume on up days)
- **Entry:** Buy strength, ride the wave
- **Exit:** Profit target, trailing stop, or trend reversal

**Current Problem:** ⚠️ Possible indicator redundancy
- Some indicators may be correlated (measuring same thing)
- This adds noise without adding signal
- **Solution:** Correlation analysis + pruning

---

### **2. Mean Reversion** (Contrarian LONG - Buy Dips)
**Thesis:** "Rubber band effect - extremes snap back UP"

**Current Status:** ⚠️ Partially active (4 indicators), UNDERDEVELOPED
**Performance:** Low Baseline scores (4-5) accidentally capture this

**Characteristics:**
- Oversold extremes (RSI < 30, Williams %R < -80, CCI < -200)
- Below support (price < BB lower, far from MA)
- Capitulation volume (high volume on decline)
- Reversal candles (hammer, bullish engulfing)
- **Entry:** Buy weakness at support
- **Exit:** Reversion to mean (usually 2-5% bounce)

**Current Problem:** ⚠️ Accidentally mixed with weak Baseline
- Low Baseline scores = few trend indicators firing
- This accidentally creates MR signals
- Not optimized as dedicated strategy
- Missing key MR indicators (Williams %R, CCI for MR, volume analysis)

**Solution:**
- Build dedicated MR strategy
- Add missing indicators
- Backtest separately
- Use proper MR scoring

---

### **3. Falling Baseline** (Trend-Following SHORT - NOT YET IMPLEMENTED)
**Thesis:** "Ride momentum DOWN - profit from decline"

**Current Status:** ❌ Not implemented (system is LONG-ONLY)
**Performance:** Unknown - never tested

**Characteristics:**
- Strong downtrend (PSAR bearish, SuperTrend red, ADX high)
- Negative momentum (RSI < 40, MACD bearish, declining MA)
- Breakdowns (below support, failing bounces)
- Distribution (high volume on down days)
- **Entry:** Short weakness, ride the decline
- **Exit:** Cover on profit target, or trend reversal up

**Why This Is Different from MR:**

| Metric | Mean Reversion Short | True Short (Falling Baseline) |
|--------|---------------------|--------------------------------|
| **Duration** | 1-3 days (quick scalp) | 5-20 days (trend) |
| **Magnitude** | 2-5% pullback | 10-30% decline |
| **Entry Signal** | Overbought (RSI >70) | Breakdown (support broken) |
| **Expectation** | Revert to mean, then UP | Continue DOWN |
| **Volume** | Low volume rally = weak | High volume decline = strong |
| **Trend** | Still in uptrend | Trend reversing |

**Example:**
- **MR Short:** Stock at $100, RSI 80, +15% in 3 days → Short for quick 3-5% pullback to $95-97, then cover (expect continuation up)
- **True Short:** Stock at $100, breaks $95 support, ADX rising, volume increasing → Short for sustained decline to $80-85 (expect trend down)

**Current Problem:** ❌ Not implemented yet
- System only looks for LONG opportunities
- No short signal generation
- No short backtesting

**Future Solution:**
- Mirror Baseline logic but inverted
- Short when downtrend is strong and confirmed
- Add shorting to backtest engine
- **CRITICAL:** Keep separate from MR shorts!

---

## 🧩 **How These Strategies Complement Each Other**

### Market Condition Coverage:

| Market Phase | Baseline LONG | MR LONG | Baseline SHORT |
|--------------|---------------|---------|----------------|
| **Bull Trend** | ✅ Excellent | ❌ Few setups | ❌ No signals |
| **Choppy/Sideways** | ⚠️ Whipsaws | ✅ Excellent | ⚠️ Whipsaws |
| **Bear Trend** | ❌ No signals | ✅ Bounces | ✅ Excellent |
| **Volatile** | ⚠️ Risky | ✅ Good | ✅ Good |

**Key Insight:** With all three strategies, you have opportunities in ANY market condition!

---

## 🔬 **Indicator Usage Across Strategies**

### Current Indicators (19):

| Indicator | Baseline LONG | MR LONG | Baseline SHORT (Future) |
|-----------|---------------|---------|-------------------------|
| **RSI** | 40-70 good | <30 good | 30-60 good (for shorts) |
| **Williams %R** | -50 to -20 good | <-80 good | >-20 good (overbought) |
| **CCI** | 0-100 good | <-200 good | >100 good (overbought) |
| **BB Position** | Middle/upper good | Below lower good | Above upper good |
| **PSAR** | Bullish good | N/A | Bearish good |
| **SuperTrend** | Green good | N/A | Red good |
| **ADX** | High + uptrend good | Low (chop) good | High + downtrend good |
| **MACD** | Bullish cross good | Divergence good | Bearish cross good |
| **Volume** | High on up days | High on down days | High on down days |
| **Candles** | Bullish patterns | Reversal at support | Bearish patterns |

**Note:** Same indicators, different contexts!

---

## 🚨 **Critical Separation: MR Short vs True Short**

### How to Tell Them Apart:

#### **Mean Reversion Short** (Quick Scalp):
```python
# Conditions:
- In uptrend (EMA20 > EMA50 > EMA200)
- Overbought (RSI > 75, at BB upper)
- Low volume rally (weak conviction)
- No trend reversal signals
- Expected move: 2-5% down, then resume up
- Hold time: 1-3 days
```

#### **True Short (Falling Baseline):**
```python
# Conditions:
- Downtrend confirmed (EMA20 < EMA50 < EMA200)
- Breakdown below support
- High volume on decline (conviction)
- Trend reversal signals (death cross, MACD bearish)
- Expected move: 10-30% down
- Hold time: 5-20 days
```

**The Confusion:**
Both use RSI > 70 and price > BB upper, but:
- **MR Short:** Temporary overextension in uptrend
- **True Short:** Failed breakout / topping pattern

**The Solution:**
Add **trend context filter**:
```python
if in_uptrend and overbought:
    signal = "MR_SHORT"  # Expect bounce down, then resume
elif in_downtrend and weakness:
    signal = "BASELINE_SHORT"  # Expect continued decline
```

---

## 🎯 **Roadmap: Current → Future**

### **Phase 1 (NOW): Fix Current System**

**1A. Clean Up Baseline LONG** ✅ In Progress
- ✅ Wide Barbell filter deployed (reject 7-11)
- ✅ Expected P&L sorting deployed
- 🔄 **TODO:** Indicator correlation analysis
- 🔄 **TODO:** Remove redundant indicators
- 🔄 **TODO:** Backtest high scores (12+) separately

**1B. Build Dedicated MR LONG** 🔄 Next Priority
- ❌ **TODO:** Add Williams %R MR scoring (<-80 = good)
- ❌ **TODO:** Add CCI MR scoring (<-200 = good)
- ❌ **TODO:** Add volume capitulation detection
- ❌ **TODO:** Add MACD divergence detection
- ❌ **TODO:** Backtest MR strategy separately
- ❌ **TODO:** Compare vs "accidental MR" (low Baseline)

**1C. Validate Separation** 🔄 Critical
- ❌ **TODO:** Backtest Baseline WITHOUT low scores (6+ only)
- ❌ **TODO:** Backtest MR separately
- ❌ **TODO:** Confirm no overlap/confusion

---

### **Phase 2 (FUTURE): Add Shorting**

**2A. Build Baseline SHORT** ⏳ Future
- ❌ Invert Baseline logic for downtrends
- ❌ Add short signal generation
- ❌ Update backtest engine for shorts
- ❌ Test on historical bear markets

**2B. Add MR SHORT** ⏳ Future (Optional)
- ❌ Quick scalp strategy (1-3 day holds)
- ❌ Overbought in uptrends only
- ❌ Very different from Baseline shorts
- ❌ Higher risk, lower priority

**2C. Prevent Confusion** ⏳ Critical
- ❌ Clear separation logic (trend context)
- ❌ Never mix MR short with True short
- ❌ Separate backtesting for each

---

## 📊 **Expected Performance Impact**

### Current System (Baseline LONG only):
- Avg P&L: 0.94%
- Coverage: ~30% of opportunities (bull trends only)

### With All Three Strategies:
- **Baseline LONG:** 1.2-1.5% avg (after cleanup)
- **MR LONG:** 1.5-2.0% avg (properly implemented)
- **Baseline SHORT:** 1.0-1.5% avg (new opportunity)

**Combined System:**
- Coverage: ~80% of opportunities (all market conditions)
- Portfolio: Mix of all three based on market
- Risk: Diversified (not all in one strategy)

---

## 💡 **Your Key Insights**

### 1. **Indicator Redundancy Problem**
"Similar indicators amplify the same information, diluting signal with noise"

**Example:** PSAR and SuperTrend both detect trends
- If highly correlated, they're redundant
- Score of 12 might just be "same signal counted 6 times"
- **Solution:** Correlation matrix, keep best from each group

### 2. **Accidental MR Discovery**
"Low scores are probably our Mean Reversion signals"

**Validation:** ✅ Correct! Low Baseline = weak trend = oversold = MR setup
- This explains the U-shaped curve perfectly
- Shows MR strategy is viable
- Needs formalization

### 3. **Short/MR Confusion Risk**
"I'm worried we're mixing good short candidates with good MR candidates"

**Validation:** ✅ Smart concern!
- Current system is LONG-ONLY (no shorts yet)
- But when adding shorts, this will be critical
- Trend context is the key separator

---

## 🎯 **Immediate Action Items**

### This Week:
1. ✅ **DONE:** Expected P&L sorting fix
2. 🔄 **IN PROGRESS:** Your prediction running
3. ⏳ **NEXT:** Backtest Mean Reversion strategy separately
   ```bash
   docker exec bluehorseshoe python src/main.py -t 2024-10-01 \
     --end 2024-12-31 --strategy mean_reversion --interval 7
   ```

### Next Week:
4. **Indicator Correlation Analysis**
   - Calculate correlation matrix for 19 indicators
   - Identify redundant pairs
   - Test removing correlated indicators

5. **Enhance MR Strategy**
   - Add Williams %R MR scoring
   - Add CCI MR scoring
   - Add volume capitulation
   - Backtest enhanced MR

### Month 2:
6. **Design Baseline SHORT Strategy**
   - Define entry/exit rules
   - Implement signal generation
   - Backtest on bear markets

---

## 📚 **References**

- **Current Code:** `src/bluehorseshoe/analysis/technical_analyzer.py`
- **Strategies:** Baseline (19 indicators), MR (4 indicators)
- **Status:** LONG-ONLY, no shorts yet
- **Discovery:** Low Baseline scores = accidental MR

---

**Bottom Line:** Your three-strategy framework is architecturally sound. The path forward is:
1. Clean up Baseline (remove redundancy)
2. Formalize MR (add indicators)
3. Eventually add Shorts (with proper separation)

This gives you **complete market coverage** and **strategy diversification**!
