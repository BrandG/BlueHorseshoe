# Phase 2: Combination Testing - Implementation Plan

**Status:** Starting Phase 2
**Date:** 2026-01-28
**Branch:** `Tweak_indicators`

## Objective

Test combinations of top-performing indicators from Phase 1 to:
1. Identify synergies (indicators that amplify each other)
2. Find redundancies (overlapping indicators)
3. Build the optimal multi-indicator strategy
4. Compare combined performance vs isolated performance

## Phase 1 Results Summary

### Baseline Strategy Top Performers
1. **Marubozu (1.0x):** 2.576 Sharpe, 63.43% WR 🥇
2. **Donchian (1.5x):** 2.333 Sharpe, 57.30% WR 🥈
3. **Heiken Ashi (1.5x):** 2.039 Sharpe, 59.18% WR 🥉
4. **Three White Soldiers (0.5x):** 1.954 Sharpe, 60.98% WR
5. **SuperTrend (1.5x):** 1.932 Sharpe, 57.95% WR

### Mean Reversion Top Performers
1. **MA_DIST_MR (0.5x):** 1.880 Sharpe, 61.63% WR 🥇
2. **BB_MR (0.5x):** 1.248 Sharpe, 53.23% WR 🥈

### All Positive Performers (20 total)
**Top Tier (>2.0 Sharpe):**
- RSI (1.0x): 2.467 Sharpe
- OBV (1.0x): 2.379 Sharpe
- Stochastic (1.0x): 2.047 Sharpe
- CCI (0.5x): 2.024 Sharpe

**Strong Performers (1.5-2.0 Sharpe):**
- ROC (1.0x), PSAR (1.5x), BB (1.5x), Williams %R (1.5x)
- MFI (1.5x), ATR_BAND (0.5x), Ichimoku (1.5x)

## Phase 2 Testing Strategy

### Test Group 1: Top 3 Baseline Combination
**Hypothesis:** The top 3 isolated performers should work well together.

**Configuration:**
```json
{
  "trend": {
    "DONCHIAN_MULTIPLIER": 1.5,
    "HEIKEN_ASHI_MULTIPLIER": 1.5,
    "ALL_OTHERS": 0.0
  },
  "candlestick": {
    "MARUBOZU_MULTIPLIER": 1.0,
    "ALL_OTHERS": 0.0
  },
  "ALL_OTHER_CATEGORIES": 0.0
}
```

**Expected Outcome:**
- If synergistic: Sharpe > 2.6 (better than Marubozu alone)
- If redundant: Sharpe ≈ 2.3-2.5 (diminishing returns)

---

### Test Group 2: Top 2 Mean Reversion Combination
**Hypothesis:** MA_DIST_MR and BB_MR should complement each other.

**Configuration:**
```json
{
  "mean_reversion": {
    "MA_DIST_MULTIPLIER": 0.5,
    "BB_MULTIPLIER": 0.5,
    "RSI_MULTIPLIER": 0.0,
    "CANDLESTICK_MULTIPLIER": 0.0
  },
  "ALL_OTHER_CATEGORIES": 0.0
}
```

**Expected Outcome:**
- If synergistic: Sharpe > 1.9 (better than MA_DIST_MR alone)
- If redundant: Sharpe ≈ 1.5-1.7

---

### Test Group 3: Category Champions
**Hypothesis:** Best performer from each category should create a balanced strategy.

**Configuration:**
```json
{
  "trend": {
    "DONCHIAN_MULTIPLIER": 1.5,
    "ALL_OTHERS": 0.0
  },
  "momentum": {
    "RSI_MULTIPLIER": 1.0,
    "ALL_OTHERS": 0.0
  },
  "volume": {
    "OBV_MULTIPLIER": 1.0,
    "ALL_OTHERS": 0.0
  },
  "candlestick": {
    "MARUBOZU_MULTIPLIER": 1.0,
    "ALL_OTHERS": 0.0
  }
}
```

**Expected Outcome:**
- Diversification across categories
- More stable performance across market conditions

---

### Test Group 4: Momentum Powerhouse
**Hypothesis:** Top momentum indicators (RSI + OBV) should amplify each other.

**Configuration:**
```json
{
  "momentum": {
    "RSI_MULTIPLIER": 1.0,
    "ROC_MULTIPLIER": 1.0,
    "BB_MULTIPLIER": 1.5,
    "WILLIAMS_R_MULTIPLIER": 1.5,
    "CCI_MULTIPLIER": 0.5,
    "ALL_OTHERS": 0.0
  },
  "volume": {
    "OBV_MULTIPLIER": 1.0,
    "ALL_OTHERS": 0.0
  },
  "ALL_OTHER_CATEGORIES": 0.0
}
```

**Expected Outcome:**
- Test if momentum indicators are redundant or synergistic
- May show high correlation (redundancy) or confirmation (synergy)

---

### Test Group 5: Current Production (All 20 Enabled)
**Hypothesis:** Our current Phase 1 weights represent the baseline for comparison.

**Configuration:**
- Current weights.json (20/23 indicators enabled)

**Expected Outcome:**
- Baseline for comparison
- Should show how much simpler combinations can match full complexity

---

### Test Group 6: Trend + Candlestick Only
**Hypothesis:** Trend indicators + candlestick patterns might be sufficient.

**Configuration:**
```json
{
  "trend": {
    "STOCHASTIC_MULTIPLIER": 1.0,
    "ICHIMOKU_MULTIPLIER": 1.5,
    "PSAR_MULTIPLIER": 1.5,
    "HEIKEN_ASHI_MULTIPLIER": 1.5,
    "DONCHIAN_MULTIPLIER": 1.5,
    "SUPERTREND_MULTIPLIER": 1.5
  },
  "candlestick": {
    "MARUBOZU_MULTIPLIER": 1.0,
    "THREE_WHITE_SOLDIERS_MULTIPLIER": 0.5,
    "BELT_HOLD_MULTIPLIER": 1.5,
    "RISE_FALL_3_METHODS_MULTIPLIER": 0.5
  },
  "ALL_OTHER_CATEGORIES": 0.0
}
```

**Expected Outcome:**
- Test if momentum/volume add value or are redundant with trend

---

## Testing Methodology

### Backtest Parameters
- **Date Range:** 2026-01-15 to 2026-01-27 (last 2 weeks)
- **Runs per config:** 20 backtests with random dates
- **Symbols:** 1,000 random per run
- **Hold period:** 5 days
- **Top candidates:** 5 per backtest

### Metrics to Compare
1. **Sharpe Ratio** (primary metric)
2. **Win Rate**
3. **Average P&L**
4. **Max Drawdown**
5. **Total Trades** (indicator of signal frequency)

### Success Criteria
- **Synergy:** Combined Sharpe > best individual performer by >10%
- **Redundancy:** Combined Sharpe ≈ best individual (within 5%)
- **Optimal:** Find combination that maximizes Sharpe with minimum complexity

## Execution Plan

### Step 1: Prepare Test Configurations (30 min)
- Create 6 weight configuration files
- Store in `src/experiments/phase2_configs/`

### Step 2: Run Backtests (12-18 hours)
- Run each configuration through backtest framework
- 6 configs × 20 runs = 120 backtests total
- Can run 2-3 in parallel to save time

### Step 3: Analysis (2-3 hours)
- Compare results across all configurations
- Generate comparison report
- Identify best-performing combinations
- Document synergies and redundancies

### Step 4: Final Recommendation
- Recommend optimal weight configuration for production
- Update weights.json with Phase 2 results
- Document findings in PHASE2_COMPLETE.md

## Expected Timeline

- **Phase 2 Start:** 2026-01-28 evening
- **Testing Complete:** 2026-01-29 afternoon
- **Analysis Complete:** 2026-01-29 evening
- **Phase 2 Complete:** 2026-01-30

## Questions to Answer

1. Do top performers work better together or alone?
2. Are momentum indicators redundant with trend indicators?
3. Can we achieve 90% of performance with 30% of indicators?
4. What's the minimum viable indicator set?
5. Do mean reversion indicators interfere with baseline signals?

## Next Steps

1. ✅ Create this plan document
2. ⏳ Create test configuration files
3. ⏳ Run Test Group 1 (Top 3 Baseline)
4. ⏳ Run remaining test groups
5. ⏳ Analyze and compare results
6. ⏳ Update production weights
7. ⏳ Document findings

---

**Phase 2 Status:** Ready to begin testing
**Created:** 2026-01-28 22:17 UTC
