# Baseline vs Mean Reversion: Indicator Design Philosophy

**Date:** February 14, 2026
**Question:** Do MR and Baseline use the same indicators differently?
**Answer:** YES - Same indicators, OPPOSITE interpretation!

---

## 🎯 Core Design Philosophy

### Baseline (Trend-Following)
**Thesis:** "Ride the wave - strong momentum continues"
- Rewards: Strength, momentum, breakouts, trend confirmation
- Penalizes: Weakness, oversold conditions, lack of momentum

### Mean Reversion (Contrarian)
**Thesis:** "Rubber band effect - extremes snap back"
- Rewards: Extremes, oversold/overbought, deviation from mean
- Penalizes: Normal conditions, no opportunity for reversion

---

## 📊 How The SAME Indicators Are Read OPPOSITE Ways

### 1. **RSI (Relative Strength Index)**

| Condition | Baseline Interpretation | Mean Reversion Interpretation |
|-----------|------------------------|-------------------------------|
| **RSI < 30** | ❌ **PENALTY -5.0** (too weak, no momentum) | ✅ **REWARD +6.0** (oversold, bounce expected) |
| **RSI < 35** | ❌ **PENALTY -2.0** (weak) | ✅ **REWARD +3.0** (moderately oversold) |
| **RSI 40-70** | ✅ **GOOD** (healthy momentum) | ❌ **BAD** (no extreme, no opportunity) |
| **RSI > 70** | ⚠️ **PENALTY** (overbought, risky) | ✅ **GOOD** (for shorts - extreme to revert) |

**Code Evidence:**
```python
# Baseline (constants.py):
OVERSOLD_RSI_THRESHOLD_EXTREME = 30
OVERSOLD_RSI_REWARD_EXTREME = -5.0  # PENALTY

# Mean Reversion (constants.py):
MR_OVERSOLD_RSI_REWARD_EXTREME = 6.0  # REWARD
```

---

### 2. **Bollinger Bands**

| Condition | Baseline Interpretation | Mean Reversion Interpretation |
|-----------|------------------------|-------------------------------|
| **Price < BB Lower** | ❌ **PENALTY -3.0** (weak, failing) | ✅ **REWARD +4.0** (oversold extreme) |
| **Price BELOW BB Lower** | ❌ **Very bad** (extreme weakness) | ✅ **BONUS +2.0** (even more oversold!) |
| **Price at BB Upper** | ✅ **GOOD** (breaking out) | ✅ **GOOD** (for shorts - overbought) |
| **Price in middle band** | ✅ **GOOD** (trending normally) | ❌ **BAD** (no extreme, no setup) |

**Code Evidence:**
```python
# Mean Reversion (technical_analyzer.py):
if bb_pos < 0.1:  # Price in bottom 10% of BB range
    bb_bonus = MR_OVERSOLD_BB_REWARD  # +4.0
    if close < bb_lower:
        bb_bonus += MR_BELLOW_LOW_BB_BONUS  # +2.0 extra
```

---

### 3. **Distance from Moving Average (EMA)**

| Condition | Baseline Interpretation | Mean Reversion Interpretation |
|-----------|------------------------|-------------------------------|
| **Price > EMA** | ✅ **GOOD** (uptrend, above support) | ❌ **BAD** (no dip to buy) |
| **Price 5-10% below EMA** | ❌ **PENALTY** (losing trend) | ✅ **REWARD +1.5** (stretched, ready to snap back) |
| **Price >10% below EMA** | ❌ **BIG PENALTY** (broken trend) | ✅ **BIG REWARD +3.0** (extreme dip, strong setup) |
| **Price near EMA** | ✅ **GOOD** (finding support) | ❌ **BAD** (no opportunity) |

**Code Evidence:**
```python
# Mean Reversion (technical_analyzer.py):
dist_ema20 = (close / ema20) - 1
if dist_ema20 < -0.05:  # 5% below EMA
    ma_bonus = 3.0 if dist_ema20 < -0.10 else 1.5  # Bigger dip = bigger reward
```

---

### 4. **Williams %R** (Currently in Baseline only)

| Condition | Baseline Interpretation | Mean Reversion Interpretation |
|-----------|------------------------|-------------------------------|
| **%R < -80** | ❌ **PENALTY** (oversold, weak) | ✅ **REWARD** (extreme oversold, bounce) |
| **%R -50 to -20** | ✅ **GOOD** (momentum) | ❌ **BAD** (no extreme) |
| **%R > -20** | ⚠️ **WARNING** (overbought) | ✅ **GOOD** (for shorts) |

---

### 5. **CCI (Commodity Channel Index)** (Currently in Baseline only)

| Condition | Baseline Interpretation | Mean Reversion Interpretation |
|-----------|------------------------|-------------------------------|
| **CCI < -200** | ❌ **PENALTY** (extreme weakness) | ✅ **BIG REWARD** (extreme oversold) |
| **CCI < -100** | ❌ **PENALTY** (weak) | ✅ **REWARD** (oversold) |
| **CCI 0-100** | ✅ **GOOD** (normal strength) | ❌ **BAD** (no opportunity) |
| **CCI > 200** | ⚠️ **WARNING** (overbought) | ✅ **GOOD** (for shorts) |

---

### 6. **Candlestick Patterns**

| Pattern | Baseline Interpretation | Mean Reversion Interpretation |
|---------|------------------------|-------------------------------|
| **Hammer** (at support) | ✅ **GOOD** (potential reversal up) | ✅ **REWARD** (reversal from oversold) |
| **Bullish Engulfing** | ✅ **GOOD** (momentum shift) | ✅ **REWARD** (capitulation bottom) |
| **Doji** (at support) | ⚠️ **NEUTRAL** (indecision) | ✅ **GOOD** (potential turning point) |

**Note:** Candlestick patterns work for BOTH strategies but in different contexts:
- **Baseline:** Looks for reversal patterns at support in an uptrend
- **Mean Reversion:** Looks for reversal patterns at extremes/oversold levels

---

### 7. **Volume**

| Condition | Baseline Interpretation | Mean Reversion Interpretation |
|-----------|------------------------|-------------------------------|
| **High volume on up day** | ✅ **VERY GOOD** (institutional buying) | ❌ **BAD** (no dip to buy) |
| **High volume on down day** | ❌ **BAD** (distribution) | ✅ **GOOD** (capitulation, washout) |
| **Low volume decline** | ❌ **PENALTY** (weak support) | ✅ **REWARD** (no conviction, easy bounce) |
| **Declining volume on uptrend** | ⚠️ **WARNING** (weakening) | N/A (not in uptrend) |

---

### 8. **MACD** (Baseline uses, MR could use differently)

| Condition | Baseline Interpretation | Mean Reversion Interpretation |
|-----------|------------------------|-------------------------------|
| **Bullish crossover** | ✅ **GOOD** (momentum starting) | ❌ **BAD** (trend starting, no dip) |
| **Bearish crossover** | ❌ **BAD** (momentum failing) | ✅ **GOOD** (oversold developing) |
| **Extreme divergence** | ⚠️ **WARNING** (losing steam) | ✅ **GREAT** (reversion setup) |

---

## 🧮 Mathematical Example

**Scenario:** Stock at $100, RSI = 25, Price = $95 (5% below 20 EMA), at BB lower band

### Baseline Score Calculation:
```
RSI < 30:           -5.0  (penalty - too weak)
Below EMA 5%:       -2.0  (penalty - losing trend)
At BB Lower:        -3.0  (penalty - failing support)
-----------------------------------
Baseline Score:    -10.0  ❌ REJECTED (negative score)
```

### Mean Reversion Score Calculation:
```
RSI < 30:           +6.0  (reward - oversold!)
Below EMA 5%:       +1.5  (reward - stretched)
At BB Lower:        +4.0  (reward - extreme)
Below BB Lower:     +2.0  (bonus - very extreme)
Confluence Bonus:   +2.0  (RSI + BB both triggered)
-----------------------------------
MR Score:          +15.5  ✅ STRONG BUY
```

**Same stock, OPPOSITE signals!**

---

## 🎭 Why This Is Brilliant Design

### 1. **Complementary, Not Redundant**
- Baseline catches trending stocks (momentum plays)
- MR catches oversold stocks (bounce plays)
- Together they work in ALL market conditions

### 2. **Different Market Regimes**
- **Strong uptrend:** Baseline shines (ride the trend)
- **Choppy/sideways:** MR shines (buy dips, sell rips)
- **Bear market:** MR finds oversold bounces

### 3. **Efficient Code**
- Same 19 indicators, same calculations
- Just different scoring logic
- No duplicate indicator computation

### 4. **Natural Risk Management**
- Baseline avoids "falling knives" (oversold weak stocks)
- MR avoids "chasing" (overbought extended stocks)
- Each strategy stays in its lane

---

## 🔬 Current System Status

### Indicators Currently Used:

**Baseline (19 indicators):**
- ✅ PSAR, SuperTrend, ADX (Trend)
- ✅ Williams %R, CCI (Momentum)
- ✅ RSI, MACD, Bollinger Bands (shared, penalty for extremes)
- ✅ VWAP, Force Index, AD Line (Volume)
- ✅ Candlestick patterns
- ✅ GAP analysis

**Mean Reversion (4 indicators - UNDERDEVELOPED!):**
- ✅ RSI oversold (reward for extremes)
- ✅ Bollinger Bands (reward for extremes)
- ✅ MA Distance (reward for deviation)
- ✅ Candlestick reversals

### Missing from MR (But Available to Add):
- ❌ Williams %R (would reward <-80)
- ❌ CCI (would reward <-200)
- ❌ Volume analysis (reward high volume declines)
- ❌ MACD divergence (reward negative divergence)

---

## 💡 Why Low Baseline Scores (4-5) Work Like MR

### Low Baseline Score = Accidental Mean Reversion

**A score of 4-5 means:**
- Few trend indicators firing → Weak trend → **Good for MR**
- Low momentum → Oversold territory → **Good for MR**
- Not breaking out → Dipping → **Good for MR**
- Near support levels → Bounce zone → **Good for MR**

**You've been accidentally trading Mean Reversion with Baseline scores!**

The U-shaped performance curve makes perfect sense:
- **Score 4-5 (Low Baseline):** Accidentally MR → **WINS**
- **Score 8-9 (Mid Baseline):** Over-confirmed trend → **LOSES** (too late)
- **Score 12+ (High Baseline):** Exceptional setups → **WINS** (rare but good)

---

## 🎯 Recommendation

### Test Pure Mean Reversion Strategy:
```bash
# Backtest MR directly
docker exec bluehorseshoe python src/main.py -t 2024-10-01 \
  --end 2024-12-31 \
  --strategy mean_reversion \
  --interval 7
```

### Hypothesis:
1. **MR scores 4-5** should ALSO outperform MR scores 8-9
2. **Pure MR strategy** should have similar or better performance than "accidental MR" (low Baseline)
3. **Combining both** (Baseline for trends + MR for dips) should maximize opportunities

---

## 📚 References

- **Code:** `src/bluehorseshoe/analysis/technical_analyzer.py`
- **Constants:** `src/bluehorseshoe/analysis/constants.py`
- **Indicators:** `src/bluehorseshoe/analysis/indicators/`

---

**Key Insight:** Same ingredients, different recipes! Like how lemon can be used in both desserts (sweet) and seafood (savory) - same lemon, opposite flavors.
