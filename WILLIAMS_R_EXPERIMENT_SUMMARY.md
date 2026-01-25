# Williams %R Experiment Summary

## Overview
Williams %R is a momentum oscillator measuring overbought/oversold conditions, ranging from 0 to -100. Values below -80 indicate oversold (potential buy), while above -20 indicates overbought conditions. This experiment tested Williams %R at three weight configurations to determine optimal influence on baseline strategy scores.

## Experiment Configurations

### Test 1: Williams %R Reduced (0.5x)
**Configuration:** `WILLIAMS_R_MULTIPLIER = 0.5`

**Results:**
- **Win Rate:** 58.70%
- **Average P&L:** +0.67%
- **Sharpe Ratio:** 1.245
- **Max Drawdown:** 16.69%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At reduced weight, Williams %R shows solid performance with nearly 59% win rate. The 1.245 Sharpe ratio indicates good risk-adjusted returns, but doesn't maximize the indicator's potential.

### Test 2: Williams %R Baseline (1.0x) - THE PARADOX
**Configuration:** `WILLIAMS_R_MULTIPLIER = 1.0`

**Results:**
- **Win Rate:** 59.55% ⬆ (HIGHEST)
- **Average P&L:** +0.42% ⬇ (LOWEST)
- **Sharpe Ratio:** 0.768 ⬇ (WORST)
- **Max Drawdown:** 29.74%
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis - The "Winning Battles, Losing War" Pattern:**
This configuration revealed a fascinating paradox - highest win rate but worst risk-adjusted returns. The 1.0x weight produces frequent small wins but allows larger losses to dominate P&L. This suggests 1.0x captures many marginal signals (boosting win count) but fails to properly weight high-quality setups vs weak ones. The poor Sharpe ratio (0.768) indicates unacceptable risk/reward profile despite winning ~60% of trades.

### Test 3: Williams %R Boosted (1.5x) - OPTIMAL ✓
**Configuration:** `WILLIAMS_R_MULTIPLIER = 1.5`

**Results:**
- **Win Rate:** 57.95%
- **Average P&L:** +0.90% ⬆ (BEST)
- **Sharpe Ratio:** 1.647 ⬆ (BEST - TIED #3 OVERALL)
- **Max Drawdown:** 14.37% ⬇ (BEST)
- **Total Runs:** 20
- **Symbols Tested:** ~1,000 per run

**Analysis:** At 1.5x, Williams %R delivers optimal risk-adjusted performance. While win rate drops slightly from 1.0x, the average gain per trade more than doubles (+0.90% vs +0.42%), and drawdown is cut in half (14.37% vs 29.74%). The elevated weight better discriminates between strong and weak signals, filtering out marginal trades that win often but gain little.

## Comparative Analysis

| Metric | 0.5x | 1.0x | 1.5x (Winner) |
|--------|------|------|---------------|
| Win Rate | 58.70% | **59.55%** | 57.95% |
| Avg P&L | +0.67% | +0.42% | **+0.90%** |
| Sharpe Ratio | 1.245 | 0.768 | **1.647** |
| Max Drawdown | 16.69% | 29.74% | **14.37%** |

**Key Insight:** Win rate peaked at 1.0x but profitability and risk management both optimal at 1.5x. This demonstrates that raw win percentage is a misleading metric without considering trade quality (P&L per win) and risk exposure (drawdown).

## Pattern Recognition: The 1.5x Elevation Cluster

Williams %R joins a growing cluster of indicators requiring 1.5x amplification:

1. **CMF (1.5x):** 1.200 Sharpe, volume-based momentum
2. **MFI (1.5x):** 1.612 Sharpe, volume + price momentum
3. **BB (1.5x):** 1.647 Sharpe, volatility bands
4. **Williams %R (1.5x):** 1.647 Sharpe, momentum oscillator

**Common Traits:**
- Bounded ranges (0-100 or -100 to 0)
- Period-based smoothing calculations
- Small absolute values requiring amplification to compete with cumulative indicators (like OBV)

**Notable Exception:**
- **RSI (1.0x):** 2.467 Sharpe - Despite being a bounded oscillator like Williams %R, RSI performs optimally at baseline weight. This suggests RSI has inherently stronger signal strength, possibly due to its exponential smoothing vs Williams %R's simple min/max calculation.

## Phase 1 Rankings (After 9 Indicators Tested)

1. **RSI (1.0x):** 2.467 Sharpe 🥇
2. **OBV (1.0x):** 2.379 Sharpe 🥈
3. **BB (1.5x):** 1.647 Sharpe 🥉 (tied)
3. **Williams %R (1.5x):** 1.647 Sharpe 🥉 (tied)
5. **MFI (1.5x):** 1.612 Sharpe
6. **CMF (1.5x):** 1.200 Sharpe
7. **MACD (0.5x):** 1.146 Sharpe
8. **ADX (2.0x):** 0.738 Sharpe

Williams %R ties for #3 overall, matching Bollinger Bands at 1.647 Sharpe.

## Recommendation

**Set `WILLIAMS_R_MULTIPLIER = 1.5` in production weights.json**

**Rationale:**
1. **Best risk-adjusted returns:** 1.647 Sharpe ratio (114% higher than 1.0x)
2. **Highest P&L:** +0.90% average gain (214% higher than 1.0x)
3. **Lowest drawdown:** 14.37% max DD (52% lower than 1.0x)
4. **Elite tier performance:** Ties for #3 overall in Phase 1 testing
5. **Signal quality over quantity:** Trades less frequently but with much better outcomes

The 1.5x weight optimally balances Williams %R's oversold/overbought signals with other baseline indicators, creating a discriminating filter that emphasizes high-probability setups over marginal entries.

## Technical Context

**Williams %R Calculation:**
```
%R = (Highest High - Close) / (Highest High - Lowest Low) × -100
```

Ranges from 0 (maximum overbought) to -100 (maximum oversold). Typically:
- Below -80: Oversold, potential buy signal
- Above -20: Overbought, potential sell signal

**Baseline Strategy Application:**
Williams %R contributes to momentum scoring in the baseline (trend-following) strategy. When below -80, it rewards potential reversals from oversold conditions. The 1.5x multiplier ensures these signals carry sufficient weight to influence the composite score when combined with trend (ADX), volume (OBV, CMF), and other momentum indicators (RSI, MACD).

## Files Generated
- `williams_r_reduced.log` (0.5x test output)
- `williams_r_baseline.log` (1.0x test output)
- `williams_r_boosted.log` (1.5x test output)
- `src/experiments/results/williams_r_reduced.json`
- `src/experiments/results/williams_r_baseline.json`
- `src/experiments/results/williams_r_boosted.json`

## Next Steps
- Clean up log files
- Continue Phase 1 testing with remaining indicators (ROC, CCI, Stochastic, Ichimoku, PSAR, Heiken Ashi, Donchian, SuperTrend, candlestick patterns, mean reversion indicators)
- After Phase 1 completion, proceed to Phase 2 ensemble optimization using Sharpe-proportional weighting strategy

---

**Experiment Date:** 2026-01-25
**Branch:** Tweak_indicators
**Commit:** [To be added]
