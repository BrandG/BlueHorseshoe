# Phase 2: Ensemble Optimization Planning

**Status:** 📋 Planning Phase (Phase 1 in progress)
**Created:** 2026-01-24
**Branch:** `Tweak_indicators`

## Overview

Phase 1 tests each indicator in **isolation** to find its optimal individual weight. Phase 2 will optimize the **ensemble combination** - determining which indicators should have more influence in the final scoring system based on their predictive power.

## The Core Question

**Phase 1 asks:** "What's the optimal weight for each indicator individually?"
- Example: RSI works best at 1.0x, MACD at 0.5x, CMF at 1.5x

**Phase 2 asks:** "Which indicators should dominate the final score?"
- Should OBV (Sharpe 2.379) have MORE influence than ADX (Sharpe 0.738)?
- Are volume indicators collectively more valuable than trend indicators?
- Do some indicators add redundancy rather than value?

## Why Ensemble Weighting Matters

### Current Problem: Equal Voice for Unequal Performance

In production, all indicators contribute equally to the final score:
```python
# Current approach (implicit equal weighting)
final_score = (
    (ADX * 2.0) +      # Sharpe 0.738
    (RSI * 1.0) +      # Sharpe 2.467
    (OBV * 1.0) +      # Sharpe 2.379
    (CMF * 1.5) +      # Sharpe 1.200
    (MACD * 0.5) +     # Sharpe 1.146
    ...
)
```

**Problem:** ADX (weak performer) gets equal vote to RSI (elite performer)!

### Proposed Solution: Weighted Ensemble

Give stronger indicators more influence:
```python
# Phase 2 approach (ensemble weighting)
ensemble_weights = {
    'RSI': 0.32,   # Elite performer → 32% influence
    'OBV': 0.31,   # Elite performer → 31% influence
    'CMF': 0.15,   # Strong performer → 15% influence
    'MFI': 0.21,   # Strong performer → 21% influence
    'ADX': 0.10    # Weak performer → 10% influence
}

final_score = (
    (ADX * 2.0 * 0.10) +
    (RSI * 1.0 * 0.32) +
    (OBV * 1.0 * 0.31) +
    (CMF * 1.5 * 0.15) +
    (MFI * 1.5 * 0.21)
)
```

**Benefit:** Top performers (RSI, OBV) collectively control 63% of scoring power!

## Phase 1 Learnings (To Date)

### Performance Hierarchy

**Tier 1: Elite (Sharpe > 2.0)**
- RSI (1.0x): 59.30% win rate, 2.467 Sharpe, 22.78% max DD
- OBV (1.0x): 64.63% win rate, 2.379 Sharpe, 11.71% max DD ⭐ Best risk control

**Tier 2: Strong (Sharpe 1.0-2.0)**
- CMF (1.5x): 60.47% win rate, 1.200 Sharpe, 16.10% max DD
- MACD (0.5x): 59.04% win rate, 1.146 Sharpe, 33.47% max DD
- MFI (1.5x): ~59% win rate, ~1.6 Sharpe (preliminary)

**Tier 3: Moderate (Sharpe < 1.0)**
- ADX (2.0x): 60.00% win rate, 0.738 Sharpe, 56.09% max DD

### Key Insights

1. **Volume indicators dominate**
   - OBV: 64.63% win rate (best overall)
   - CMF: 60.47% win rate (2nd best)
   - MFI: ~59% win rate (preliminary, likely 3rd)
   - Volume confirmation is highly predictive

2. **Not all indicators are equal**
   - Top performer (OBV): 2.379 Sharpe
   - Bottom performer (ADX): 0.738 Sharpe
   - **3.2x difference in risk-adjusted returns!**

3. **Each indicator has unique optimal weight**
   - Standard (1.0x): RSI, OBV
   - Reduced (0.5x): MACD
   - Elevated (1.5x): CMF, MFI
   - Very elevated (2.0x): ADX

4. **Some indicators needed major corrections**
   - MACD: 1.5x → 0.5x (was producing negative returns)
   - CMF: 1.0x → 1.5x (was producing negative returns)
   - Production settings were significantly suboptimal

## Phase 2 Methodology

### Step 1: Complete Phase 1 Testing

Test remaining indicators:
- Bollinger Bands (BB)
- Williams %R
- CCI (Commodity Channel Index)
- ROC (Rate of Change)
- Stochastic
- SuperTrend
- PSAR (Parabolic SAR)
- Candlestick patterns

### Step 2: Rank All Indicators

Primary metric: **Sharpe Ratio** (risk-adjusted returns)

Secondary metrics:
- Win Rate (signal reliability)
- Avg P&L (absolute returns)
- Max Drawdown (risk control)

Example ranking:
```
Rank  Indicator   Sharpe   Win Rate   Avg P&L   Max DD
1     RSI         2.467    59.30%     1.36%     22.78%
2     OBV         2.379    64.63%     1.26%     11.71%
3     MFI         1.612    58.97%     0.86%     24.60%
4     CMF         1.200    60.47%     0.57%     16.10%
5     MACD        1.146    59.04%     0.72%     33.47%
6     ADX         0.738    60.00%     0.43%     56.09%
...
```

### Step 3: Calculate Ensemble Weights

**Method A: Sharpe-Proportional Weighting** (Recommended starting point)

```python
# Calculate total Sharpe of top N performers
top_performers = [RSI, OBV, MFI, CMF, MACD]  # Example
total_sharpe = 2.467 + 2.379 + 1.612 + 1.200 + 1.146 = 8.804

# Calculate proportional weights
ensemble_weights = {
    'RSI':  2.467 / 8.804 = 0.280  (28.0%)
    'OBV':  2.379 / 8.804 = 0.270  (27.0%)
    'MFI':  1.612 / 8.804 = 0.183  (18.3%)
    'CMF':  1.200 / 8.804 = 0.136  (13.6%)
    'MACD': 1.146 / 8.804 = 0.130  (13.0%)
}
```

**Method B: Tiered Weighting**

Elite performers get boosted:
```python
# Tier 1 (Sharpe > 2.0): 60% of total weight
# Tier 2 (Sharpe 1.0-2.0): 30% of total weight
# Tier 3 (Sharpe < 1.0): 10% of total weight

ensemble_weights = {
    'RSI':  0.30,  # Tier 1: 30%
    'OBV':  0.30,  # Tier 1: 30%
    'MFI':  0.10,  # Tier 2: 10%
    'CMF':  0.10,  # Tier 2: 10%
    'MACD': 0.10,  # Tier 2: 10%
    'ADX':  0.10   # Tier 3: 10%
}
```

**Method C: Win Rate-Based**

Weight by signal reliability:
```python
total_win_rate = sum of all win rates
weight = indicator_win_rate / total_win_rate
```

**Method D: Composite Score**

Combine multiple metrics:
```python
composite_score = (
    (Sharpe * 0.50) +        # 50% weight to risk-adjusted returns
    (Win Rate * 0.30) +      # 30% weight to reliability
    (Avg P&L * 0.20)         # 20% weight to absolute returns
)
```

### Step 4: Test Ensemble Combinations

Run backtests with different ensemble configurations:

**Test 1: Sharpe-Proportional (All indicators)**
- Use all Phase 1 indicators weighted by Sharpe
- Baseline for comparison

**Test 2: Top 5 Only (Quality over quantity)**
- Use only top 5 performers by Sharpe
- Remove weak performers entirely

**Test 3: Volume-Heavy Ensemble**
- OBV + CMF + MFI = 70% weight
- RSI + MACD = 30% weight
- Test if volume dominance improves results

**Test 4: Volume + Momentum Pair**
- OBV (50%) + RSI (50%)
- Minimal ensemble, maximum quality

**Test 5: Diversified Ensemble**
- Volume (40%): OBV + CMF + MFI
- Momentum (40%): RSI + MACD
- Trend (20%): ADX
- Balanced coverage across signal types

**Test 6: Boosted Star Performer**
- OBV at 150% of Sharpe-proportional weight
- Test if best indicator should dominate further

### Step 5: Grid Search Optimization

For the most promising ensemble from Step 4, optimize weights:

```python
# Example: Optimize OBV + RSI + CMF + MFI combo
grid = {
    'OBV': [0.20, 0.25, 0.30, 0.35, 0.40],
    'RSI': [0.20, 0.25, 0.30, 0.35, 0.40],
    'CMF': [0.10, 0.15, 0.20, 0.25],
    'MFI': [0.10, 0.15, 0.20, 0.25]
}
# Constraint: weights sum to 1.0
```

Test all combinations, rank by Sharpe ratio.

### Step 6: Validate Winner

Full backtest on winning ensemble:
- 100+ runs (vs 20 in Phase 1)
- Full date range (2000-2025)
- All symbols (not sampled)
- Multiple market regimes
- Out-of-sample testing

## Success Criteria

Phase 2 is successful if we achieve:

1. **Higher Sharpe than best individual indicator**
   - Target: Sharpe > 2.5 (beat RSI's 2.467)
   - Diversification benefit

2. **Higher win rate than best individual indicator**
   - Target: Win rate > 65% (beat OBV's 64.63%)
   - Ensemble should be more reliable

3. **Lower max drawdown than individual indicators**
   - Target: Max DD < 20%
   - Risk reduction through diversification

4. **Clear performance improvement over equal weighting**
   - Ensemble weighting should beat naive equal-weight approach
   - Justify the complexity

5. **Statistical significance**
   - T-test p-value < 0.05
   - Improvement is not due to chance

## Important Considerations

### 1. Correlation and Redundancy

**Problem:** OBV, CMF, and MFI all measure volume flow
- High correlation means redundant signals
- Using all three at full weight might overweight volume

**Solution:**
- Test correlation matrix
- If correlation > 0.7, reduce combined weight
- Prefer complementary indicators (volume + momentum + trend)

### 2. Complementarity

**Volume indicators:** Identify smart money flow (OBV, CMF, MFI)
**Momentum indicators:** Identify overextension (RSI, MACD)
**Trend indicators:** Identify trend strength (ADX)

Ideal ensemble covers all signal types without redundancy.

### 3. Overfitting Risk

**Danger:** Optimizing on the same data we tested on
**Mitigation:**
- Use different date ranges for Phase 1 vs Phase 2
- Reserve 2024-2025 data for final validation
- Prefer simple weighting schemes (Sharpe-proportional) over complex grid search
- Cross-validation

### 4. Market Regime Dependence

Different indicators may perform differently in:
- Bull markets (trending)
- Bear markets (volatile)
- Sideways markets (range-bound)

Should we:
- Use fixed weights across all regimes?
- Adjust weights dynamically based on regime?

### 5. Diminishing Returns

Adding more indicators doesn't always help:
- Top 3 indicators might capture 80% of the value
- Adding 10 more might only add 10% more value
- Complexity cost > benefit

## Expected Outcomes

### Scenario 1: Volume Indicators Dominate (Likely)

Based on Phase 1 trends:
- OBV, CMF, MFI control 60-70% of scoring power
- Volume confirmation is the strongest signal
- Final ensemble: Volume-heavy with momentum support

### Scenario 2: OBV + RSI Pair is Sufficient (Possible)

Minimal ensemble performs best:
- OBV (volume) + RSI (momentum) = comprehensive coverage
- Additional indicators add noise, not signal
- Simplicity wins

### Scenario 3: Balanced Ensemble (Less Likely)

All indicator types contribute equally:
- Volume, momentum, trend each get ~33% weight
- Diversification across signal types provides stability
- No single indicator dominates

### Scenario 4: Current Production Mix is Near-Optimal (Unlikely)

Phase 1 optimal weights are sufficient:
- Ensemble weighting provides minimal benefit
- Individual weight optimization was the key improvement
- Keep current approach

## Implementation Plan

### Phase 2.1: Ensemble Weight Calculation

**Input:** Phase 1 results for all indicators
**Output:** Optimal ensemble weight configuration

**Script:** `src/calculate_ensemble_weights.py`
```python
def calculate_ensemble_weights(phase1_results, method='sharpe_proportional'):
    """
    Args:
        phase1_results: Dict of {indicator: {sharpe, win_rate, pnl, ...}}
        method: 'sharpe_proportional', 'tiered', 'composite', etc.

    Returns:
        ensemble_weights: Dict of {indicator: weight}
    """
```

### Phase 2.2: Ensemble Testing

**Script:** `src/run_ensemble_test.py`
```python
def run_ensemble_test(ensemble_config, num_runs=50):
    """
    Args:
        ensemble_config: {
            'weights': {'OBV': 0.30, 'RSI': 0.30, ...},
            'indicator_multipliers': {'OBV': 1.0, 'RSI': 1.0, ...}
        }
        num_runs: Number of backtest runs

    Returns:
        ensemble_results: Performance metrics
    """
```

### Phase 2.3: Grid Search Optimization

**Script:** `src/optimize_ensemble_grid.py`
```python
def grid_search_ensemble(indicators, grid_params, num_runs=50):
    """
    Test all combinations of ensemble weights.

    Args:
        indicators: List of indicators to include
        grid_params: Dict of {indicator: [weight_options]}
        num_runs: Backtest runs per configuration

    Returns:
        best_config: Optimal ensemble configuration
        all_results: Performance of all tested configs
    """
```

### Phase 2.4: Validation

**Script:** `src/validate_ensemble.py`
```python
def validate_ensemble(ensemble_config, out_of_sample_dates):
    """
    Full validation backtest on unseen data.

    Args:
        ensemble_config: Winning config from Phase 2.3
        out_of_sample_dates: Dates not used in Phase 1 or 2

    Returns:
        validation_results: Out-of-sample performance
    """
```

## Deliverables

### Phase 2 Outputs

1. **PHASE_2_RESULTS.md**
   - All ensemble configurations tested
   - Performance comparison table
   - Statistical analysis
   - Winner selection rationale

2. **Updated weights.json**
   - Individual indicator weights (from Phase 1)
   - NEW: Ensemble weights for each indicator

3. **Ensemble configuration file**
   - `src/ensemble_config.json`:
   ```json
   {
     "indicators": {
       "OBV": {
         "multiplier": 1.0,
         "ensemble_weight": 0.30
       },
       "RSI": {
         "multiplier": 1.0,
         "ensemble_weight": 0.30
       },
       ...
     },
     "ensemble_method": "sharpe_proportional",
     "phase2_sharpe": 2.85,
     "validation_sharpe": 2.72
   }
   ```

4. **Production update**
   - Modify `technical_analyzer.py` to use ensemble weights
   - Update documentation
   - Add ensemble weight visualization to reports

## Timeline Estimate

- **Phase 2.1:** 1 day (calculate weights, design tests)
- **Phase 2.2:** 3-5 days (test 10-15 ensemble configurations)
- **Phase 2.3:** 2-3 days (grid search optimization)
- **Phase 2.4:** 1-2 days (validation + documentation)

**Total:** ~1-2 weeks after Phase 1 completes

## Open Questions

1. **Should we use ensemble weighting for both strategies?**
   - Baseline (trend-following) AND Mean Reversion?
   - Or different ensembles for each?

2. **Dynamic vs Static weights?**
   - Adjust ensemble weights based on market regime?
   - Or use fixed weights across all conditions?

3. **How many indicators in final ensemble?**
   - Top 3? Top 5? Top 10?
   - Where's the point of diminishing returns?

4. **Should we test indicator combinations?**
   - Some pairs might work better together
   - OBV + RSI might have synergy
   - Test pairwise, or just ensemble?

5. **Production cutoff for inclusion?**
   - Minimum Sharpe to be included? (e.g., > 1.0)
   - Or include all, just heavily weighted toward best?

## References

- Phase 1 results: `*_EXPERIMENT_SUMMARY.md` files
- Phase 1 code: `src/run_isolated_indicator_test.py`
- Current weights: `src/weights.json`
- Scoring logic: `src/bluehorseshoe/analysis/technical_analyzer.py`

## Next Steps

1. ✅ Complete Phase 1 testing (all indicators)
2. ✅ Document all Phase 1 results
3. 📋 Calculate Sharpe-proportional ensemble weights
4. 🔄 Implement ensemble testing framework
5. 🔄 Run ensemble configuration tests
6. 🔄 Optimize winning configuration
7. 🔄 Validate on out-of-sample data
8. 🔄 Update production code
9. 🔄 Deploy optimized ensemble

## Conclusion

Phase 2 ensemble optimization is the natural next step after Phase 1. While Phase 1 finds the "volume knob" for each indicator, Phase 2 determines which indicators deserve the "lead vocals" vs "background harmony" in the final ensemble.

The goal is to build a weighted ensemble that leverages the elite performers (OBV, RSI) while minimizing the influence of weaker performers, ultimately achieving better risk-adjusted returns than any single indicator alone.

Based on Phase 1 trends, we expect **volume indicators to dominate** the final ensemble, with OBV and RSI as the core duo and CMF/MFI providing supporting confirmation. The key insight is that not all indicators are equal - and our scoring system should reflect that.
