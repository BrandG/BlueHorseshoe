# Production Configuration Update - January 30, 2026

## Summary

Based on comprehensive Phase 2 combination testing (140 backtests), we have deployed **Group 1 (Top 3 Baseline)** configuration to production, replacing the 20-indicator Phase 1 configuration.

## Performance Improvement

| Metric | Phase 1 (20 indicators) | Group 1 (3 indicators) | Improvement |
|--------|------------------------|------------------------|-------------|
| **Sharpe Ratio** | 0.162 | 0.310 | **+91%** |
| **Total Return** | +29.94% | +41.60% | **+39%** |
| **Win Rate** | 59.7% | 56.4% | -5% |
| **Avg PnL/Trade** | +0.447% | +1.067% | **+139%** |
| **Total Trades** | 67 | 39 | -42% |

## Active Indicators (3 only)

1. **Marubozu (1.0x)** - Candlestick pattern indicator
   - Phase 1 Sharpe: 2.576 (best performer)
   - Identifies strong directional momentum bars

2. **Donchian Channels (1.5x)** - Trend breakout indicator
   - Phase 1 Sharpe: 2.333 (second best)
   - Detects price breakouts to new highs/lows

3. **Heiken Ashi (1.5x)** - Smoothed trend indicator
   - Phase 1 Sharpe: 2.039 (third best)
   - Filters noise and confirms trend direction

## Why This Works

### 1. Quality Over Quantity
- Fewer, stronger signals beat many weak signals
- 3 indicators = fewer conflicting signals = clearer decision-making

### 2. Focused Strategy
- All 3 indicators are **trend-following**
- No mixing of mean reversion or momentum strategies
- Coherent, aligned signals

### 3. The Pareto Principle
- 80% of performance from 20% of indicators (3 out of 26 tested)
- Adding more indicators diluted performance (see Group 7 results)

## Phase 2 Testing Results Ranked by Sharpe

1. 🥇 **Group 1: Top 3 Baseline** - 0.310 Sharpe, +41.60%
2. 🥈 Group 3: Category Champions - 0.238 Sharpe, +32.33%
3. 🥉 Group 5: Current Production (20 indicators) - 0.162 Sharpe, +29.94%
4. Group 7: High Sharpe (6 indicators) - 0.056 Sharpe, +8.66%
5. Group 2: Mean Reversion - 0.050 Sharpe, +8.26%
6. Group 6: Trend + Candlestick - 0.037 Sharpe, +5.61%
7. ❌ Group 4: Momentum Powerhouse - -0.120 Sharpe, -21.87%

## Key Insights

- **Adding more "good" indicators does NOT improve performance**
  - Group 7 (6 high-Sharpe indicators) performed 82% worse than Group 1
  
- **Strategy coherence matters more than indicator count**
  - Mixing trend-following + mean reversion weakens both
  
- **Simplicity wins**
  - Faster execution, easier debugging, clearer signals

## Files Changed

- `/root/BlueHorseshoe/src/weights.json` - Updated to Group 1 configuration
- Backup: `/root/BlueHorseshoe/src/weights.json.phase1_production_backup`

## Services Restarted

- bluehorseshoe_worker
- bluehorseshoe_beat

## Next Steps

1. Monitor tomorrow's daily pipeline run (08:00 UTC)
2. Compare report quality vs previous days
3. Track performance over next 1-2 weeks
4. Consider reverting if performance degrades (backup available)

## Rollback Instructions

If needed, restore previous configuration:
```bash
cp /root/BlueHorseshoe/src/weights.json.phase1_production_backup /root/BlueHorseshoe/src/weights.json
docker restart bluehorseshoe_worker bluehorseshoe_beat
```
