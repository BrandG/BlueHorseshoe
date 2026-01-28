# Stochastic Oscillator Experiment Summary

## Overview
The Stochastic oscillator is a bounded momentum indicator (0-100) that compares a closing price to its price range over a given period. It measures where price closed relative to the high-low range, indicating momentum and potential reversals. This experiment tested Stochastic at three weight configurations to determine optimal influence on baseline strategy scores.

**MAJOR FINDING:** Stochastic wins **BRONZE MEDAL** with 2.047 Sharpe at 1.0x, ranking #3 overall and displacing CCI to #4!

## Experiment Configurations

### Test 1: Stochastic Reduced (0.5x)
**Configuration:** `STOCHASTIC_MULTIPLIER = 0.5`

**Results:**
- **Win Rate:** 57.65%
- **Average P&L:** +0.10%
- **Sharpe Ratio:** 0.176
- **Max Drawdown:** 46.24%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At reduced weight, Stochastic delivers barely positive returns with weak 0.176 Sharpe. The 0.5x dampening suppresses the indicator's signal strength too much, resulting in minimal profitability despite decent 57.65% win rate.

### Test 2: Stochastic Baseline (1.0x) - OPTIMAL ✓
**Configuration:** `STOCHASTIC_MULTIPLIER = 1.0`

**Results:**
- **Win Rate:** 58.23%
- **Average P&L:** +1.08%
- **Sharpe Ratio:** 2.047 🥉 (BRONZE MEDAL - #3 OVERALL!)
- **Max Drawdown:** 16.53% (LOWEST)
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At baseline weight, Stochastic delivers exceptional performance with 2.047 Sharpe ratio, winning the bronze medal and ranking #3 overall in Phase 1! The +1.08% average P&L and remarkably low 16.53% drawdown demonstrate excellent risk-adjusted returns. The 1.0x weight allows Stochastic's natural signal strength to shine without distortion.

### Test 3: Stochastic Boosted (1.5x)
**Configuration:** `STOCHASTIC_MULTIPLIER = 1.5`

**Results:**
- **Win Rate:** 60.49%
- **Average P&L:** +0.51%
- **Sharpe Ratio:** 0.763
- **Max Drawdown:** 50.71%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** Boosting Stochastic produces degraded results despite highest win rate (60.49%). The 1.5x amplification creates excessive sensitivity, leading to more frequent trades with smaller gains and larger drawdown. Sharpe ratio falls 63% from 1.0x, indicating poor risk/reward profile.

## Comparative Analysis

| Metric | 0.5x | 1.0x (Winner) | 1.5x |
|--------|------|---------------|------|
| Win Rate | 57.65% | 58.23% | **60.49%** |
| Avg P&L | +0.10% | **+1.08%** | +0.51% |
| Sharpe Ratio | 0.176 | **2.047** | 0.763 |
| Max Drawdown | 46.24% | **16.53%** | 50.71% |

**Key Insight:** Clear optimal at 1.0x baseline weight. While 1.5x achieves highest win rate, P&L is cut in half and drawdown triples. The 1.0x weight provides best balance of profitability, risk control, and signal quality.

## Pattern Recognition: The Elite Bounded Oscillator Duo

Stochastic joins RSI as the second bounded oscillator (0-100 range) optimal at baseline weight:

**Elite Bounded Oscillators (1.0x optimal):**
- **RSI (1.0x):** 2.467 Sharpe 🥇 - Gold medal
- **Stochastic (1.0x):** 2.047 Sharpe 🥉 - Bronze medal

**Other Bounded Oscillators:**
- **CCI (0.5x):** 2.024 Sharpe - Loosely bounded (±200 typical), needs dampening
- **Williams %R (1.5x):** 1.647 Sharpe - Bounded (-100 to 0), needs amplification
- **BB (1.5x):** 1.647 Sharpe - Volatility percentile (0-100), needs amplification
- **MFI (1.5x):** 1.612 Sharpe - Volume-weighted (0-100), needs amplification

**Why RSI and Stochastic Work at 1.0x:**

Both indicators share key characteristics:
1. **Strictly bounded (0-100):** Clear mathematical limits
2. **Strong inherent signal:** Well-calibrated for overbought/oversold detection
3. **Proven track record:** Decades of widespread use have validated their scaling
4. **Similar calculation philosophy:** Measure position within recent range
   - RSI: Ratio of average gains to average losses
   - Stochastic: Position of close within high-low range

These characteristics produce naturally optimal signal strength without needing amplification or dampening.

## Phase 1 Rankings - STOCHASTIC WINS BRONZE! 🥉

**Updated Rankings (After 14 Indicators):**

1. **RSI (1.0x):** 2.467 Sharpe 🥇 - Gold
2. **OBV (1.0x):** 2.379 Sharpe 🥈 - Silver
3. **Stochastic (1.0x):** 2.047 Sharpe 🥉 - Bronze (NEW!)
4. **CCI (0.5x):** 2.024 Sharpe (drops from #3 to #4)
5. **ROC (1.0x):** 1.911 Sharpe
6. **BB (1.5x):** 1.647 Sharpe (tied)
6. **Williams %R (1.5x):** 1.647 Sharpe (tied)
8. **MFI (1.5x):** 1.612 Sharpe
9. **ATR_BAND (0.5x):** 1.549 Sharpe
10. **CMF (1.5x):** 1.200 Sharpe
11. **MACD (0.5x):** 1.146 Sharpe
12. **ADX (2.0x):** 0.738 Sharpe

**Failed:**
13. **ATR_SPIKE (0.0x):** -0.271 Sharpe (disabled)

**Medal Ceremony Update:**
Stochastic captures the bronze medal, displacing CCI to #4. The top 3 now features:
- Two momentum oscillators (RSI #1, Stochastic #3)
- One volume indicator (OBV #2)

## Trend Category Progress

**Trend Indicators (2 of 7 tested):**

| Indicator | Optimal Weight | Sharpe | Rank | Status |
|-----------|---------------|--------|------|--------|
| Stochastic | 1.0x | 2.047 | #3 | ✅ Bronze |
| ADX | 2.0x | 0.738 | #12 | ✅ Weak |
| Ichimoku | TBD | TBD | TBD | 🔄 Next |
| PSAR | TBD | TBD | TBD | ⏳ Pending |
| Heiken Ashi | TBD | TBD | TBD | ⏳ Pending |
| Donchian | TBD | TBD | TBD | ⏳ Pending |
| SuperTrend | TBD | TBD | TBD | ⏳ Pending |

**Trend category insights (2 tested):**
- Stochastic delivers elite performance (#3 overall)
- ADX struggles as standalone indicator (#12 overall)
- Wide performance variance: 0.738 to 2.047 Sharpe
- 5 more trend indicators to test

## Recommendation

**Set `STOCHASTIC_MULTIPLIER = 1.0` in production weights.json**

**Rationale:**
1. **Elite performance:** 2.047 Sharpe ranks #3 overall (bronze medal)
2. **Best risk-adjusted returns:** Dramatically outperforms 0.5x (11.6x better) and 1.5x (2.7x better)
3. **Exceptional risk control:** 16.53% max drawdown (lowest among all tested configurations)
4. **Strong profitability:** +1.08% average gain per trade
5. **Natural signal strength:** 1.0x weight allows Stochastic's proven scaling to work optimally

The 1.0x baseline weight positions Stochastic as a premier momentum indicator alongside RSI, providing complementary overbought/oversold signals with different calculation methodology.

## Technical Context

**Stochastic Oscillator Calculation:**
```
%K (Fast) = 100 × [(Close - Lowest Low) / (Highest High - Lowest Low)]
%D (Slow) = 3-period SMA of %K

Typical periods:
- Fast Stochastic: %K = 14, %D = 3
- Slow Stochastic: %K = 3-period SMA of Fast %K, %D = 3-period SMA of Slow %K
```

**Traditional Interpretation:**
- **Above 80:** Overbought conditions, potential reversal down
- **Below 20:** Oversold conditions, potential reversal up
- **%K crosses above %D:** Bullish signal
- **%K crosses below %D:** Bearish signal

**Baseline Strategy Application:**
Stochastic contributes to trend/momentum scoring in the baseline (trend-following) strategy by:
1. Rewarding positive momentum (%K in bullish range)
2. Penalizing overbought extremes (%K >80)
3. Identifying oversold bounces (%K <20 with reversal)
4. Confirming trend strength via %K/%D alignment

The 1.0x multiplier ensures Stochastic signals carry appropriate weight alongside RSI, ROC, CCI, MACD, BB, and Williams %R in the composite momentum assessment, plus ADX for trend strength.

## Strategic Insights

**Stochastic vs RSI - Similar Yet Different:**

Both are 0-100 bounded momentum oscillators, but with different approaches:

| Aspect | RSI | Stochastic |
|--------|-----|------------|
| **Measures** | Gain/loss ratio | Position in range |
| **Calculation** | Exponential smoothing | High/low comparison |
| **Sensitivity** | Moderate (14-period EMA) | Higher (raw range position) |
| **Optimal weight** | 1.0x (2.467 Sharpe) | 1.0x (2.047 Sharpe) |
| **Rank** | #1 Gold | #3 Bronze |

**Key Differences:**
- **RSI** is smoother due to exponential averaging → slightly more stable signal
- **Stochastic** is more responsive to price position → faster reaction to changes
- Both complement each other: RSI for stability, Stochastic for sensitivity

**Using Both Together:**
In Phase 2 ensemble optimization, having both RSI (#1) and Stochastic (#3) provides:
- Dual confirmation: Both signaling overbought/oversold increases confidence
- Different sensitivities: RSI catches sustained momentum, Stochastic catches short-term extremes
- Divergence detection: When they disagree, signals potential trend change

**Stochastic's Unique Value:**
While RSI measures momentum via gain/loss ratios, Stochastic measures momentum via closing position in the range. This provides different perspective:
- **RSI asks:** "How strong are the gains vs losses?"
- **Stochastic asks:** "Where did price close relative to the high/low range?"

Both answers together create more robust momentum assessment.

## Comparison to Other Oscillators

**Bounded Oscillator Performance Summary:**

| Indicator | Range | Optimal Weight | Sharpe | Rank |
|-----------|-------|---------------|--------|------|
| RSI | 0-100 | 1.0x | 2.467 | #1 |
| Stochastic | 0-100 | 1.0x | 2.047 | #3 |
| CCI | ±200 typical | 0.5x | 2.024 | #4 |
| ROC | Unbounded | 1.0x | 1.911 | #5 |
| BB | 0-100 | 1.5x | 1.647 | #6T |
| Williams %R | -100 to 0 | 1.5x | 1.647 | #6T |
| MFI | 0-100 | 1.5x | 1.612 | #8 |

**Pattern Observations:**
- Strictly bounded 0-100 with strong signal (RSI, Stochastic): 1.0x optimal
- Strictly bounded 0-100 with moderate signal (BB, MFI): 1.5x optimal
- Loosely bounded/volatile (CCI): 0.5x optimal
- Unbounded pure momentum (ROC): 1.0x optimal

**Why Williams %R Differs from Stochastic:**
Despite both measuring position in range, Williams %R needs 1.5x while Stochastic optimal at 1.0x:
- **Williams %R:** Inverted scale (-100 to 0), less common, may have weaker historical calibration
- **Stochastic:** Standard scale (0-100), widely used for decades, well-calibrated

## Next Steps

**Trend Category Progress: 2/7 Complete**

**Remaining Trend Indicators:**
- Ichimoku (multi-component cloud indicator)
- PSAR (Parabolic SAR - price trailing stop)
- Heiken Ashi (modified candlesticks)
- Donchian (channel breakouts)
- SuperTrend (ATR-based trend indicator)

**Other Remaining Categories:**
- **Candlestick (4 patterns):** RISE_FALL_3_METHODS, THREE_WHITE_SOLDIERS, MARUBOZU, BELT_HOLD
- **Mean Reversion indicators:** RSI, BB, MA_DIST, CANDLESTICK (separate strategy)

**Suggested Next Steps:**
- Continue trend category testing with Ichimoku
- Complete all 40+ indicators in Phase 1
- Proceed to Phase 2 ensemble optimization

## Files Generated
- `stochastic_reduced.log` (0.5x test output)
- `stochastic_baseline.log` (1.0x test output)
- `stochastic_boosted.log` (1.5x test output)
- `src/experiments/results/stochastic_reduced.json`
- `src/experiments/results/stochastic_baseline.json`
- `src/experiments/results/stochastic_boosted.json`

---

**Experiment Date:** 2026-01-26
**Branch:** Tweak_indicators
**Commit:** [To be added]
**Achievement:** BRONZE MEDAL! Stochastic ranks #3 overall! 🥉
