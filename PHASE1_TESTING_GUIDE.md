# Phase 1: Isolated Indicator Testing Guide

## Overview

Phase 1 isolates individual indicators to test them independently. This eliminates confounding variables and helps you understand which indicators actually contribute value.

## Quick Start

### 1. Test a Single Indicator

```bash
# Test RSI with default multiplier (1.0)
docker exec bluehorseshoe python src/run_isolated_indicator_test.py \
  --indicator RSI \
  --runs 20

# Test RSI with boosted multiplier
docker exec bluehorseshoe python src/run_isolated_indicator_test.py \
  --indicator RSI \
  --multiplier 2.0 \
  --runs 20 \
  --name rsi_boost_2x

# Test ADX
docker exec bluehorseshoe python src/run_isolated_indicator_test.py \
  --indicator ADX \
  --runs 20
```

### 2. Compare Results

```bash
# List all experiments
docker exec bluehorseshoe python src/compare_experiments.py --list

# Compare two experiments
docker exec bluehorseshoe python src/compare_experiments.py rsi_m1.0 rsi_boost_2x

# Compare multiple experiments (shows ranking)
docker exec bluehorseshoe python src/compare_experiments.py rsi_m1.0 rsi_boost_2x rsi_m0.5
```

## Available Indicators

### Trend Indicators
- `ADX` - Average Directional Index
- `STOCHASTIC` - Stochastic Oscillator
- `ICHIMOKU` - Ichimoku Cloud
- `PSAR` - Parabolic SAR
- `HEIKEN_ASHI` - Heiken Ashi
- `DONCHIAN` - Donchian Channels
- `SUPERTREND` - SuperTrend

### Momentum Indicators
- `RSI` - Relative Strength Index
- `ROC` - Rate of Change
- `MACD` - Moving Average Convergence Divergence
- `MACD_SIGNAL` - MACD Signal Line
- `BB` - Bollinger Bands
- `WILLIAMS_R` - Williams %R
- `CCI` - Commodity Channel Index

### Volume Indicators
- `OBV` - On-Balance Volume
- `CMF` - Chaikin Money Flow
- `ATR_BAND` - ATR Bands
- `ATR_SPIKE` - ATR Spikes
- `MFI` - Money Flow Index

### Candlestick Patterns
- `RISE_FALL_3_METHODS`
- `THREE_WHITE_SOLDIERS`
- `MARUBOZU`
- `BELT_HOLD`

## Workflow Example

### Testing RSI Variations

```bash
# Baseline: RSI with multiplier 1.0
docker exec bluehorseshoe python src/run_isolated_indicator_test.py \
  --indicator RSI --multiplier 1.0 --runs 30 --name rsi_baseline

# Test: Reduce RSI weight
docker exec bluehorseshoe python src/run_isolated_indicator_test.py \
  --indicator RSI --multiplier 0.5 --runs 30 --name rsi_reduced

# Test: Boost RSI weight
docker exec bluehorseshoe python src/run_isolated_indicator_test.py \
  --indicator RSI --multiplier 1.5 --runs 30 --name rsi_boosted

# Test: Double RSI weight
docker exec bluehorseshoe python src/run_isolated_indicator_test.py \
  --indicator RSI --multiplier 2.0 --runs 30 --name rsi_double

# Compare all
docker exec bluehorseshoe python src/compare_experiments.py \
  rsi_baseline rsi_reduced rsi_boosted rsi_double
```

### Testing All Indicators (Find the Best)

```bash
# Test each indicator independently with same multiplier
for indicator in RSI ADX MACD ROC OBV CMF; do
  docker exec bluehorseshoe python src/run_isolated_indicator_test.py \
    --indicator $indicator --multiplier 1.0 --runs 30
done

# Compare all
docker exec bluehorseshoe python src/compare_experiments.py --list
# Then compare the ones you're interested in
```

## Understanding Results

### Metrics

- **Win Rate**: % of profitable trades (higher is better)
- **Avg PnL**: Average profit/loss per trade (higher is better)
- **Sharpe Ratio**: Risk-adjusted returns (higher is better, >1.0 is good)
- **Max Drawdown**: Largest peak-to-trough loss (lower is better)

### Statistical Tests

- **T-Test**: Tests if mean PnL difference is significant
- **Mann-Whitney U**: Non-parametric test for PnL distributions
- **Chi-Square**: Tests if win rate difference is significant
- **Cohen's d**: Effect size (0.2=small, 0.5=medium, 0.8=large)

### When to Keep Changes

✓ **Strong Evidence**: Significant p-value (<0.05) AND medium/large effect size (d>0.5)
⚠ **Moderate Evidence**: Significant p-value OR large effect size (run more tests)
✗ **Weak Evidence**: Neither significant nor large effect

## Files Generated

Results are saved in `src/experiments/results/`:

```
experiments/results/
├── rsi_baseline.json           # Full experiment results
├── rsi_baseline_config.json    # Weights configuration used
├── rsi_boosted.json
├── rsi_boosted_config.json
└── ...
```

## Tips

1. **Run enough tests**: 20-30 runs minimum for statistical power
2. **Test systematically**: Start with multipliers 0.5, 1.0, 1.5, 2.0
3. **Use Sharpe ratio**: Better than raw PnL for comparing indicators
4. **Check significance**: Don't trust results with p-value > 0.05
5. **Look for consistency**: An indicator that wins by a small margin consistently may be better than one that wins big sometimes

## Next Steps

After Phase 1, you'll have:
- ✓ Best configuration for each indicator
- ✓ Understanding of which indicators add value
- ✓ Confidence intervals for performance metrics

Then move to Phase 2: Ensemble weight optimization using your Phase 1 winners!
