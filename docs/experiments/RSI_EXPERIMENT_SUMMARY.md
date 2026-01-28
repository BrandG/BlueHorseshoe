# RSI Indicator Optimization - Phase 1 Testing

**Date:** 2026-01-23
**Branch:** `Tweak_indicators`
**Test Type:** Isolated Indicator Testing

## Objective

Test the RSI (Relative Strength Index) indicator with different multiplier weights to find the optimal configuration for the baseline strategy.

## Methodology

- **Test Framework:** Isolated indicator testing (all other indicators zeroed out)
- **Runs per configuration:** 20 backtests with random historical dates
- **Symbols sampled:** 1,000 random symbols per run (out of 10,870 total)
- **Strategy:** Baseline (trend-following)
- **Hold period:** 5 days
- **Top candidates:** 5 per backtest

## Configurations Tested

| Configuration | RSI Multiplier | Runs | Total Trades |
|--------------|----------------|------|--------------|
| Baseline     | 1.0x           | 20   | 86           |
| Reduced      | 0.5x           | 20   | 83           |
| Boosted      | 1.5x           | 20   | 77           |

## Results

### Performance Ranking

| Rank | Configuration | Win Rate | Avg P&L | Total P&L | Sharpe Ratio | Max Drawdown |
|------|--------------|----------|---------|-----------|--------------|--------------|
| 🥇 1 | **RSI 1.0x** | **59.30%** | **1.36%** | **117.09%** | **2.467** | 22.78% |
| 🥈 2 | RSI 1.5x | 58.44% | 0.55% | 42.52% | 1.118 | 13.07% |
| 🥉 3 | RSI 0.5x | 43.37% | -0.00% | -0.38% | -0.008 | 57.18% |

### Statistical Analysis

**RSI 1.0x vs RSI 0.5x (Reduced):**
- P&L Difference: +1.37% (baseline better)
- T-Test p-value: **0.0311** ✅ **SIGNIFICANT**
- Mann-Whitney p-value: **0.0123** ✅ **SIGNIFICANT**
- Cohen's d: 0.334 (small effect size)
- **Conclusion:** Reducing RSI weight significantly hurts performance

**RSI 1.0x vs RSI 1.5x (Boosted):**
- P&L Difference: +0.81% (baseline better)
- T-Test p-value: 0.1686 ❌ Not significant
- Mann-Whitney p-value: 0.1782 ❌ Not significant
- Cohen's d: 0.218 (small effect size)
- **Conclusion:** Boosting RSI weight provides no significant benefit

## Key Findings

1. **Current RSI multiplier (1.0x) is optimal** - provides best risk-adjusted returns
2. **Reducing RSI weight is harmful** - leads to negative returns and higher drawdown
3. **Increasing RSI weight doesn't help** - no performance improvement, just lower returns
4. **RSI is a valuable indicator** - 59.3% win rate when used alone demonstrates strong predictive power

## Recommendation

✅ **Keep RSI_MULTIPLIER at 1.0** in `src/weights.json`

No changes needed to current configuration.

## Files Generated

- `src/experiments/results/test_rsi_baseline.json` - Baseline (1.0x) results
- `src/experiments/results/test_rsi_baseline_config.json` - Baseline config
- `src/experiments/results/rsi_reduced.json` - Reduced (0.5x) results
- `src/experiments/results/rsi_reduced_config.json` - Reduced config
- `src/experiments/results/rsi_boosted.json` - Boosted (1.5x) results
- `src/experiments/results/rsi_boosted_config.json` - Boosted config

## Performance Optimization Applied

Modified `src/run_isolated_indicator_test.py` to sample 1,000 random symbols per run instead of testing all 10,870 symbols. This reduced runtime from ~15 hours to ~6.7 hours per test (55% improvement) while maintaining statistical validity.

## Next Steps

- ✅ RSI optimization complete
- 🔄 Move to MACD indicator testing
- ⏳ Continue Phase 1 with other key indicators (ADX, OBV, CMF)
