# ATR_SPIKE Experiment Summary

## Overview
ATR_SPIKE detects abnormal volatility increases by comparing current ATR (Average True Range) to its recent average. When ATR suddenly spikes above its baseline, it signals increased volatility which could indicate breakouts, trend acceleration, or market events. This experiment tested ATR_SPIKE at three weight configurations to determine optimal influence on baseline strategy scores.

**CRITICAL FINDING:** ATR_SPIKE is the **first indicator in Phase 1 testing where ALL weight configurations produce NEGATIVE returns**. This reveals important insights about indicator standalone viability.

## Experiment Configurations

### Test 1: ATR_SPIKE Reduced (0.5x) - WORST
**Configuration:** `ATR_SPIKE_MULTIPLIER = 0.5`

**Results:**
- **Win Rate:** 45.95%
- **Average P&L:** -0.42%
- **Sharpe Ratio:** -0.814 (WORST)
- **Max Drawdown:** 41.25%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At reduced weight, ATR_SPIKE produces the worst performance of all three configurations - below-50% win rate, negative returns, and -0.814 Sharpe. The reduced weight fails to capture enough volatility signal to be meaningful.

### Test 2: ATR_SPIKE Baseline (1.0x)
**Configuration:** `ATR_SPIKE_MULTIPLIER = 1.0`

**Results:**
- **Win Rate:** 45.24%
- **Average P&L:** -0.30%
- **Sharpe Ratio:** -0.594
- **Max Drawdown:** 39.88%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At baseline weight, ATR_SPIKE still produces negative returns with below-50% win rate. Performance is slightly better than 0.5x but still unprofitable. Full-strength volatility spike signals don't provide directional edge.

### Test 3: ATR_SPIKE Boosted (1.5x) - LEAST-BAD
**Configuration:** `ATR_SPIKE_MULTIPLIER = 1.5`

**Results:**
- **Win Rate:** 50.00%
- **Average P&L:** -0.18%
- **Sharpe Ratio:** -0.271 (LEAST-BAD)
- **Max Drawdown:** 87.39%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** Boosting ATR_SPIKE produces the "least bad" results - 50% win rate (random) and smallest negative Sharpe (-0.271). However, it still loses money on average and has catastrophic 87% max drawdown. Even at its best, ATR_SPIKE fails to generate positive returns.

## Comparative Analysis

| Metric | 0.5x | 1.0x | 1.5x (Least-Bad) |
|--------|------|------|------------------|
| Win Rate | 45.95% | 45.24% | **50.00%** |
| Avg P&L | -0.42% | -0.30% | **-0.18%** |
| Sharpe Ratio | -0.814 | -0.594 | **-0.271** |
| Max Drawdown | 41.25% | 39.88% | **87.39%** |

**Key Insight:** ALL configurations produce negative returns. Even the "best" option (1.5x) is still unprofitable with massive drawdown. This is the first indicator in Phase 1 where no viable standalone weight exists.

## Why ATR_SPIKE Fails as Standalone Indicator

**1. Volatility Spikes Lack Directional Information:**
ATR_SPIKE detects *when* volatility increases but provides no information about *which direction* price will move. A volatility spike could signal:
- Breakout beginning (potentially good) ✅
- Breakout failure/whipsaw (bad) ❌
- Trend exhaustion/reversal (bad) ❌
- News reaction (random direction) ❌
- Choppy market acceleration (bad) ❌

**2. Signal-to-Noise Ratio Problem:**
Without directional context from momentum/trend indicators, ATR_SPIKE captures noise as much as genuine signals. Many volatility spikes are false starts or failed breakouts.

**3. Timing Issues:**
By the time ATR spikes enough to trigger the signal, the initial move may already be over-extended. Entries based solely on increased volatility risk buying into exhaustion or selling into bottoms.

**4. Comparison to ATR_BAND:**
Interesting contrast with ATR_BAND's success:
- **ATR_BAND (0.5x):** 1.549 Sharpe, 64.37% win rate - Works standalone!
- **ATR_SPIKE (all weights):** Negative Sharpe, <50% win rate - Doesn't work standalone

ATR_BAND uses ATR to define price position within volatility-adjusted bands (provides context), while ATR_SPIKE only signals volatility changes (no context).

## Phase 1 Rankings (After 13 Indicators - Volume Category COMPLETE!)

**Top 11 Indicators:**
1. RSI (1.0x): 2.467 Sharpe 🥇
2. OBV (1.0x): 2.379 Sharpe 🥈
3. CCI (0.5x): 2.024 Sharpe 🥉
4. ROC (1.0x): 1.911 Sharpe
5. BB (1.5x): 1.647 Sharpe (tied)
5. Williams %R (1.5x): 1.647 Sharpe (tied)
7. MFI (1.5x): 1.612 Sharpe
8. ATR_BAND (0.5x): 1.549 Sharpe
9. CMF (1.5x): 1.200 Sharpe
10. MACD (0.5x): 1.146 Sharpe
11. ADX (2.0x): 0.738 Sharpe

**Failed Indicators:**
12. **ATR_SPIKE (DISABLED):** Best -0.271 Sharpe (all negative) ❌

ATR_SPIKE becomes the first indicator to fail at all tested weights, providing valuable insight into which signals work standalone vs ensemble-only.

## MILESTONE: Volume Category Complete! 🎉

**All 5 Volume Indicators Tested:**

| Indicator | Optimal Weight | Sharpe | Rank | Win Rate | Status |
|-----------|---------------|--------|------|----------|--------|
| OBV | 1.0x | 2.379 | #2 | ~60% | ✅ Silver |
| MFI | 1.5x | 1.612 | #7 | 58.97% | ✅ Solid |
| ATR_BAND | 0.5x | 1.549 | #8 | 64.37% | ✅ Solid |
| CMF | 1.5x | 1.200 | #9 | 60.47% | ✅ Solid |
| ATR_SPIKE | 0.0x | -0.271 | FAIL | 50.00% | ❌ Disabled |

**Volume Category Insights:**
- **4 of 5 indicators successful** with average 1.685 Sharpe (excluding ATR_SPIKE)
- **OBV ranks #2 overall** - volume direction is powerful signal
- **ATR_BAND highest win rate** (64.37%) in entire Phase 1
- **Diverse weight needs:** 1 at 0.0x (disabled), 1 at 0.5x, 1 at 1.0x, 2 at 1.5x
- **Volume indicators critical** for confirming price moves

## Recommendation

**Set `ATR_SPIKE_MULTIPLIER = 0.0` (DISABLED) in production weights.json**

**Rationale:**
1. **All weights produce negative returns:** Best -0.271 Sharpe still unprofitable
2. **No standalone viability:** Below-50% win rates at 0.5x and 1.0x, random at 1.5x
3. **Excessive risk:** 87% max drawdown at "best" weight (1.5x)
4. **Volatility ≠ directional edge:** ATR spikes don't predict price direction
5. **Better as ensemble component:** May add value in Phase 2 when combined with directional indicators

**Important:** This doesn't mean ATR_SPIKE is useless - it may provide valuable confirmation when combined with momentum/trend signals in Phase 2 ensemble testing. Some indicators work better as filters than primary signals.

## Technical Context

**ATR_SPIKE Detection:**
```
ATR_Current = Average True Range (14 periods)
ATR_Average = Moving Average of ATR (e.g., 20 periods)
ATR_Spike = ATR_Current / ATR_Average

Signal triggered when ATR_Spike > Threshold (e.g., 1.5x)
```

**What ATR_SPIKE Measures:**
- Sudden increase in price volatility
- Deviation from normal trading range
- Potential breakout or trend acceleration

**What ATR_SPIKE DOESN'T Measure:**
- Price direction (up or down)
- Trend strength or momentum
- Volume confirmation
- Support/resistance levels

**Why Directional Context Matters:**
Volatility spikes are ambiguous without additional information:
- **With bullish momentum (RSI>50, MACD>0, OBV rising):** Spike could signal upside breakout ✅
- **With bearish momentum:** Spike could signal downside breakdown ✅
- **With no clear momentum:** Spike is noise ❌

## Strategic Insights

**Standalone vs Ensemble Indicators:**

Phase 1 isolated testing reveals two categories:

**Standalone Viable (11 indicators):**
- Work profitably when tested alone
- Provide both signal strength AND directional bias
- Examples: RSI, OBV, CCI, ROC, BB, Williams %R, MFI, ATR_BAND, CMF, MACD, ADX

**Ensemble-Only Candidates (1 indicator so far):**
- Fail when tested alone (negative returns)
- May provide value as filter/confirmation in combination
- Examples: **ATR_SPIKE**

This distinction will be crucial for Phase 2 optimization - ensemble-only indicators might still contribute value in the full system even if they fail individually.

**ATR_BAND vs ATR_SPIKE Contrast:**

Both use ATR but with different applications:

| Aspect | ATR_BAND (Works!) | ATR_SPIKE (Fails!) |
|--------|-------------------|-------------------|
| **What it measures** | Price position in volatility bands | Volatility level changes |
| **Context provided** | Relative price level + volatility | Volatility only |
| **Directional info** | Yes (above/below bands) | No (just "more volatile") |
| **Standalone viability** | Yes (1.549 Sharpe) | No (all negative) |
| **Optimal weight** | 0.5x | 0.0x (disabled) |

This teaches us that **indicators need to provide actionable context**, not just signal presence of market conditions.

## Lessons Learned

**1. Not All Indicators Work Standalone:**
Phase 1 isolated testing is valuable precisely because it identifies indicators that:
- Work well alone (use these as primary signals)
- Only work in combination (save for Phase 2 ensemble)

**2. Volatility Needs Direction:**
Measuring *that* something is happening isn't enough - need to know *what* is happening. ATR_SPIKE says "volatility increased" but not "price going up" or "price going down."

**3. Context is Critical:**
ATR_BAND works because it provides context (price position relative to volatility-adjusted bands). ATR_SPIKE fails because it lacks context (just reports volatility increase).

**4. Phase 2 Opportunity:**
ATR_SPIKE may still add value in ensemble:
- Filter trades: Only take RSI/MACD signals when ATR_SPIKE confirms volatility expansion
- Confirmation: Require volatility surge for breakout trades
- Position sizing: Reduce size during low volatility (inverse ATR_SPIKE)

## Next Steps

**Volume Category: COMPLETE! ✅ (5/5)**

**Categories Complete:**
1. **Momentum (6/6):** RSI, CCI, ROC, BB, Williams %R, MACD ✅
2. **Volume (5/5):** OBV, MFI, ATR_BAND, CMF, ATR_SPIKE ✅

**Remaining Categories:**
1. **Trend (6 indicators):** STOCHASTIC, ICHIMOKU, PSAR, HEIKEN_ASHI, DONCHIAN, SUPERTREND (ADX already tested)
2. **Candlestick (4 patterns):** RISE_FALL_3_METHODS, THREE_WHITE_SOLDIERS, MARUBOZU, BELT_HOLD
3. **Mean Reversion indicators:** RSI, BB, MA_DIST, CANDLESTICK (separate strategy)

**Suggested Next Steps:**
- Begin trend category testing with Stochastic
- Continue systematic Phase 1 isolated testing
- After all categories complete, proceed to Phase 2 ensemble optimization
- In Phase 2, revisit ATR_SPIKE as potential filter/confirmation indicator

## Files Generated
- `atr_spike_reduced.log` (0.5x test output)
- `atr_spike_baseline.log` (1.0x test output)
- `atr_spike_boosted.log` (1.5x test output)
- `src/experiments/results/atr_spike_reduced.json`
- `src/experiments/results/atr_spike_baseline.json`
- `src/experiments/results/atr_spike_boosted.json`

---

**Experiment Date:** 2026-01-26
**Branch:** Tweak_indicators
**Commit:** [To be added]
**Milestone:** Volume Category Complete (5/5) 🎉
**Important Finding:** First indicator to fail at all weights - valuable insight for ensemble design!
