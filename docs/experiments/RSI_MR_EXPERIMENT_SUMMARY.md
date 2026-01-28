# RSI Mean Reversion - Isolated Indicator Test Results

**Test Date:** 2026-01-28
**Indicator:** RSI (Mean Reversion Strategy)
**Category:** Mean Reversion
**Test Type:** Isolated (all other indicators zeroed)

## Executive Summary

RSI mean reversion shows **negative performance in isolation** but generates reasonable trade volume at higher multipliers. Unlike baseline RSI (which showed strong performance), mean reversion RSI alone is insufficient for profitable trading. The strategy appears to require multiple confirmations.

**CRITICAL BUG FIXED:** Initial tests returned 0 trades due to a bug in `create_isolated_weights()` that set RSI_MULTIPLIER in the wrong section (momentum instead of mean_reversion). After fixing the function to be strategy-aware, tests now properly activate the mean reversion RSI scoring.

## Test Results

### 0.5x Multiplier (Reduced/Dampened)
```json
{
  "total_trades": 0,
  "winning_trades": 0,
  "win_rate": 0.00%,
  "avg_pnl": 0.00%,
  "total_pnl": 0.00%,
  "sharpe_ratio": 0.000,
  "max_drawdown": 0.00%
}
```

**Analysis:** Dampening RSI MR to 0.5x eliminates all trade signals. The reduced scoring prevents any candidates from passing the filtering thresholds, resulting in zero trades across all 20 runs.

### 1.0x Multiplier (Baseline/Natural)
```json
{
  "total_trades": 74,
  "winning_trades": 36,
  "win_rate": 48.65%,
  "avg_pnl": -0.17%,
  "total_pnl": -12.92%,
  "sharpe_ratio": -0.266,
  "max_drawdown": 46.25%
}
```

**Analysis:** Natural RSI MR weight produces moderate trade volume but negative risk-adjusted returns. Win rate is slightly below 50%, indicating the strategy is no better than random when used in isolation.

### 1.5x Multiplier (Boosted/Elevated) ⭐ **OPTIMAL**
```json
{
  "total_trades": 85,
  "winning_trades": 37,
  "win_rate": 43.53%,
  "avg_pnl": -0.13%,
  "total_pnl": -11.07%,
  "sharpe_ratio": -0.161,
  "max_drawdown": 98.93%
}
```

**Analysis:** Elevation to 1.5x generates the most trades and shows the least negative Sharpe ratio (-0.161 vs -0.266). While still unprofitable in isolation, this is the best-performing configuration.

## Comparative Analysis

| Multiplier | Sharpe | Trades | Win Rate | Avg P&L | Pattern |
|------------|--------|--------|----------|---------|---------|
| 0.5x       | 0.000  | 0      | 0.00%    | 0.00%   | No Signal |
| 1.0x       | -0.266 | 74     | 48.65%   | -0.17%  | Negative |
| 1.5x       | **-0.161** | 85 | 43.53%   | -0.13%  | **Least Bad** |

**Key Finding:** This is the first indicator in Phase 1 testing to show **universally negative performance across all multipliers**. Unlike baseline indicators (where isolated testing often revealed strong signals), mean reversion indicators appear to require confluence with other signals.

## Pattern Classification

**Pattern: D - Insufficient Alone**

RSI mean reversion does not fit the standard Pattern A/B/C framework. Instead, it reveals a fourth pattern:
- RSI alone cannot identify profitable mean reversion opportunities
- The strategy requires multiple confirmations (BB position, MA distance, candlestick reversals)
- Isolated testing reveals the indicator's limitations rather than optimal weight

This contrasts sharply with baseline RSI, which showed strong positive Sharpe ratios in isolation during earlier testing.

## Technical Insights

### Why RSI MR Underperforms in Isolation

1. **Oversold ≠ Reversal**: RSI < 35 indicates oversold conditions, but not all oversold stocks bounce. Many continue downward.

2. **Missing Context**: Mean reversion needs multiple confirmations:
   - RSI oversold (momentum exhaustion)
   - Price below lower BB (statistical extreme)
   - Distance from MA (reversion target)
   - Reversal candlestick patterns (timing)

3. **Scoring Thresholds**:
   - RSI < 30 (extreme): 6.0 points * multiplier
   - RSI < 35 (moderate): 3.0 points * multiplier
   - At 1.5x: max score = 9.0 points

4. **Candidate Scarcity**: RSI < 35 is relatively rare, occurring in ~10-15% of stocks on any given day. Without other indicators contributing scores, many trading days find zero candidates.

### Bug Fix Details

**Problem:** `create_isolated_weights()` used a simple loop with `break` after finding first occurrence of `RSI_MULTIPLIER`. It found it in the "momentum" section (used by baseline strategy) and never set it in the "mean_reversion" section.

**Solution:** Modified function to be strategy-aware:
- For `strategy='mean_reversion'`: only set multipliers in mean_reversion section
- For `strategy='baseline'`: set multipliers in trend/momentum/volume/candlestick sections

**Impact:** After fix, tests properly activate mean reversion scoring and generate trades.

## Recommendation

**Use 1.5x multiplier for RSI_MULTIPLIER in mean_reversion section of weights.json**

While this configuration still shows negative Sharpe, it:
- Generates reasonable trade volume (85 trades)
- Has least negative risk-adjusted returns
- Allows RSI to contribute to mean reversion scoring when combined with other indicators

The negative isolated performance suggests RSI MR should be viewed as a **component** of the mean reversion strategy rather than a standalone signal.

## Next Steps

1. Test remaining mean reversion indicators:
   - BB_MR (Bollinger Band position)
   - MA_DIST_MR (Distance from moving average)
   - CANDLESTICK_MR (Reversal patterns)

2. After individual testing, evaluate **confluence performance**: Test combinations of mean reversion indicators to determine if their combined signals produce positive returns.

3. Consider implementing minimum confluence requirements (e.g., require 2+ mean reversion signals active simultaneously).

## Files Generated

- `src/experiments/results/rsi_mr_reduced.json` (0.5x results)
- `src/experiments/results/rsi_mr_baseline.json` (1.0x results)
- `src/experiments/results/rsi_mr_boosted.json` (1.5x results)
- `src/experiments/results/rsi_mr_*_config.json` (isolated weight configs)

## Code Changes

**Modified:** `src/run_isolated_indicator_test.py`
- Added `strategy` parameter to `create_isolated_weights()` function
- Implemented strategy-aware multiplier setting logic
- Ensures correct section is modified based on strategy type
