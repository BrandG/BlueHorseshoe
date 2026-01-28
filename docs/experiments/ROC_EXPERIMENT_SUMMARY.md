# ROC (Rate of Change) Experiment Summary

## Overview
ROC (Rate of Change) is an unbounded momentum oscillator that measures the percentage price change over a given period (typically 9 or 12 periods). Unlike bounded oscillators (RSI, Williams %R), ROC ranges from negative infinity to positive infinity, providing pure momentum measurement without normalization. This experiment tested ROC at three weight configurations to determine optimal influence on baseline strategy scores.

## Experiment Configurations

### Test 1: ROC Reduced (0.5x)
**Configuration:** `ROC_MULTIPLIER = 0.5`

**Results:**
- **Win Rate:** 49.45%
- **Average P&L:** -0.06%
- **Sharpe Ratio:** -0.105
- **Max Drawdown:** 46.24%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At reduced weight, ROC produces negative returns and a below-50% win rate. The -0.105 Sharpe indicates that the indicator signal is too weak to overcome market noise, resulting in essentially random performance with a slight negative bias.

### Test 2: ROC Baseline (1.0x) - OPTIMAL ✓
**Configuration:** `ROC_MULTIPLIER = 1.0`

**Results:**
- **Win Rate:** 60.0%
- **Average P&L:** +1.17%
- **Sharpe Ratio:** 1.911 ⭐
- **Max Drawdown:** 24.13%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At baseline weight, ROC delivers excellent performance with 60% win rate and +1.17% average gain. The 1.911 Sharpe ratio ranks #5 overall in Phase 1 testing. This represents ROC's natural signal strength - properly scaled without needing amplification or reduction.

### Test 3: ROC Boosted (1.5x) - WORST
**Configuration:** `ROC_MULTIPLIER = 1.5`

**Results:**
- **Win Rate:** 43.18%
- **Average P&L:** -0.39%
- **Sharpe Ratio:** -0.745
- **Max Drawdown:** 64.28%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** Boosting ROC produces the worst results across all configurations. The 1.5x weight creates excessive sensitivity to momentum, leading to false signals, large drawdown (64%), and negative returns. This demonstrates that ROC's unbounded nature makes it vulnerable to over-amplification.

## Comparative Analysis

| Metric | 0.5x | 1.0x (Winner) | 1.5x |
|--------|------|---------------|------|
| Win Rate | 49.45% | **60.0%** | 43.18% |
| Avg P&L | -0.06% | **+1.17%** | -0.39% |
| Sharpe Ratio | -0.105 | **1.911** | -0.745 |
| Max Drawdown | 46.24% | **24.13%** | 64.28% |

**Key Insight:** ROC exhibits a classic "Goldilocks" pattern - too weak at 0.5x, too strong at 1.5x, just right at 1.0x. The baseline weight provides optimal signal-to-noise ratio.

## Pattern Recognition: Unbounded vs Bounded Indicators

**ROC (Unbounded) - Optimal at 1.0x:**
- Pure percentage change measurement
- Range: -∞ to +∞
- Already scaled appropriately for scoring
- Amplification creates false signals

**Bounded Oscillators - Optimal at 1.5x:**
- RSI: 0-100 (optimal at 1.0x - exception due to strong inherent signal)
- Williams %R: -100 to 0 (optimal at 1.5x)
- BB: percentile 0-100 (optimal at 1.5x)
- MFI: 0-100 (optimal at 1.5x)
- Need amplification to compete with unbounded/cumulative indicators

**Volume Indicators:**
- OBV (cumulative, unbounded): optimal at 1.0x
- CMF (bounded, period-based): optimal at 1.5x
- MFI (bounded, period-based): optimal at 1.5x

**Hypothesis:** Indicators naturally scaled to show large absolute changes (ROC, OBV) work best at baseline, while indicators normalized to fixed ranges need amplification to match their influence.

## Phase 1 Rankings (After 10 Indicators)

1. **RSI (1.0x):** 2.467 Sharpe 🥇
2. **OBV (1.0x):** 2.379 Sharpe 🥈
3. **BB (1.5x):** 1.647 Sharpe 🥉 (tied)
3. **Williams %R (1.5x):** 1.647 Sharpe 🥉 (tied)
5. **ROC (1.0x):** 1.911 Sharpe ⭐ (NEW - #5)
6. **MFI (1.5x):** 1.612 Sharpe
7. **CMF (1.5x):** 1.200 Sharpe
8. **MACD (0.5x):** 1.146 Sharpe
9. **ADX (2.0x):** 0.738 Sharpe

ROC ranks #5 overall with solid 1.911 Sharpe, placing it in the upper tier of momentum indicators tested so far.

## Recommendation

**Set `ROC_MULTIPLIER = 1.0` in production weights.json**

**Rationale:**
1. **Best risk-adjusted returns:** 1.911 Sharpe ratio
2. **Strong win rate:** 60% (11 percentage points higher than 1.5x)
3. **Controlled drawdown:** 24.13% max DD (63% lower than 1.5x)
4. **Consistent profitability:** +1.17% average gain per trade
5. **Natural scaling:** 1.0x represents ROC's inherent signal strength without distortion

The 1.0x weight allows ROC to contribute momentum confirmation without over-weighting short-term price changes. ROC complements other momentum indicators by providing pure percentage change measurement, distinct from oscillator-based signals (RSI, Williams %R) and moving average crossovers (MACD).

## Technical Context

**ROC Calculation:**
```
ROC = [(Close - Close_n_periods_ago) / Close_n_periods_ago] × 100
```

Typically uses 9-12 period lookback. Positive values indicate upward momentum, negative values indicate downward momentum. The magnitude indicates strength of the move.

**Baseline Strategy Application:**
ROC contributes to momentum scoring in the baseline (trend-following) strategy. Positive ROC values reward upward momentum, while negative values penalize or disqualify. The 1.0x multiplier ensures ROC signals carry appropriate weight alongside trend (ADX), volume (OBV, CMF, MFI), and other momentum indicators (RSI, MACD, BB, Williams %R).

## Strategic Insights

**Momentum Category Progress:** 5 of 6 complete (ROC, RSI, MACD, BB, Williams %R tested; CCI remaining)

**Emerging Patterns:**
1. **Unbounded indicators (ROC, OBV):** Optimal at 1.0x
2. **Bounded oscillators (Williams %R, BB, MFI, CMF):** Generally optimal at 1.5x
3. **RSI exception:** Despite being bounded, optimal at 1.0x due to exceptionally strong signal
4. **MACD exception:** Optimal at 0.5x, requires dampening

**ROC's Unique Value:**
Unlike RSI/Williams %R which measure relative position within recent range, ROC measures absolute percentage change. This provides complementary momentum signal:
- **RSI/Williams %R:** "Is price stretched relative to recent range?"
- **ROC:** "How much has price changed in percentage terms?"

Both perspectives together create more robust momentum assessment.

## Files Generated
- `roc_reduced.log` (0.5x test output)
- `roc_baseline.log` (1.0x test output)
- `roc_boosted.log` (1.5x test output)
- `src/experiments/results/roc_reduced.json`
- `src/experiments/results/roc_baseline.json`
- `src/experiments/results/roc_boosted.json`

## Next Steps
- Clean up log files
- Test CCI (final momentum indicator)
- After momentum category complete, move to trend indicators (Stochastic, Ichimoku, PSAR, Heiken Ashi, Donchian, SuperTrend)
- Continue Phase 1 isolated testing across all 40+ indicators
- Proceed to Phase 2 ensemble optimization once Phase 1 completes

---

**Experiment Date:** 2026-01-25
**Branch:** Tweak_indicators
**Commit:** [To be added]
