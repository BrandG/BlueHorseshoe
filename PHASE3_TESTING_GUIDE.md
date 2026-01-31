# Phase 3A Testing Guide

## Overview

Phase 3A tests all 8 Phase 3 indicators in isolation to determine:
1. Standalone performance (Sharpe ratio, win rate, etc.)
2. Optimal weight multiplier (0.5x, 1.0x, 1.5x, 2.0x)
3. Comparison to Phase 2 baseline (0.310 Sharpe)

## Testing Scope

**Total Tests:** 640 backtests
- 8 indicators
- 4 weight levels each (0.5x, 1.0x, 1.5x, 2.0x)
- 20 backtest runs per configuration

**Estimated Time:** 12-24 hours (depends on system performance)

## Quick Start

### Test Single Indicator at One Weight (Validation)
```bash
# Test RS at 1.0x with 5 runs (quick validation)
python src/run_phase3_testing.py --indicator RS --weight 1.0 --runs 5

# Test RS at 1.0x with full 20 runs
python src/run_phase3_testing.py --indicator RS --weight 1.0 --runs 20
```

### Test Single Indicator at All Weights
```bash
# Test RS at all 4 weights (0.5x, 1.0x, 1.5x, 2.0x) with 20 runs each
python src/run_phase3_testing.py --indicator RS --runs 20
```

### Test All Indicators (Full Phase 3A)
```bash
# Run all 640 backtests (will take 12-24 hours)
python src/run_phase3_testing.py --indicator all --runs 20
```

## Available Indicators

| Code | Indicator | Category | Type |
|------|-----------|----------|------|
| RS | Relative Strength vs SPY | momentum | Market-relative |
| GAP | Gap Analysis | price_action | Overnight momentum |
| VWAP | VWAP | volume | Institutional positioning |
| TTM | TTM Squeeze | trend | Volatility compression |
| AROON | Aroon Indicator | trend | Time-based trend |
| KELTNER | Keltner Channels | trend | ATR-based bands |
| FORCE | Elder's Force Index | volume | Power measurement |
| AD | A/D Line | volume | Divergence detection |

## Testing Strategy

### Recommended Approach 1: Test in Batches

**Day 1: Market Context Indicators**
```bash
python src/run_phase3_testing.py --indicator RS --runs 20
python src/run_phase3_testing.py --indicator GAP --runs 20
```

**Day 2: Volume Indicators**
```bash
python src/run_phase3_testing.py --indicator VWAP --runs 20
python src/run_phase3_testing.py --indicator FORCE --runs 20
python src/run_phase3_testing.py --indicator AD --runs 20
```

**Day 3: Trend Indicators**
```bash
python src/run_phase3_testing.py --indicator TTM --runs 20
python src/run_phase3_testing.py --indicator AROON --runs 20
python src/run_phase3_testing.py --indicator KELTNER --runs 20
```

### Recommended Approach 2: Test Top Priorities First

Based on strategic value:
```bash
# Priority 1: Market context (most likely to improve system)
python src/run_phase3_testing.py --indicator RS --runs 20
python src/run_phase3_testing.py --indicator GAP --runs 20

# Priority 2: Volume intelligence (VWAP vs OBV comparison)
python src/run_phase3_testing.py --indicator VWAP --runs 20

# Priority 3: Volatility patterns
python src/run_phase3_testing.py --indicator TTM --runs 20

# Lower priority: Test if priority 1-3 show promise
python src/run_phase3_testing.py --indicator AROON --runs 20
python src/run_phase3_testing.py --indicator KELTNER --runs 20
python src/run_phase3_testing.py --indicator FORCE --runs 20
python src/run_phase3_testing.py --indicator AD --runs 20
```

## How It Works

### 1. Test Configuration
The script creates a zero-config (all indicators disabled) and enables only the indicator being tested:

```json
{
  "trend": { "ALL": 0.0 },
  "momentum": { "RS_MULTIPLIER": 1.0, "ALL_OTHERS": 0.0 },
  "volume": { "ALL": 0.0 },
  ...
}
```

### 2. Random Date Selection
Generates random dates between 2024-01-01 and 2026-01-27 to test across various market conditions.

### 3. Backtest Execution
Runs `docker exec bluehorseshoe python src/main.py -t DATE` for each random date.

### 4. Config Restoration
Automatically restores original weights.json after testing.

## Analyzing Results

After running tests, analyze results from backtest log:

```bash
# View recent results
tail -100 src/logs/backtest_log.csv

# Analyze specific indicator results
docker exec bluehorseshoe python -c "
import pandas as pd
df = pd.read_csv('src/logs/backtest_log.csv')

# Filter last 80 trades (4 weights × 20 runs)
recent = df.tail(80)

print('Summary Statistics:')
print(f'Win Rate: {recent[\"outcome\"].eq(\"win\").mean() * 100:.2f}%')
print(f'Avg P&L: {recent[\"pnl_percent\"].mean():.2f}%')
print(f'Total Return: {recent[\"pnl_percent\"].sum():.2f}%')
print(f'Sharpe Ratio: {recent[\"pnl_percent\"].mean() / recent[\"pnl_percent\"].std():.3f}')
"
```

## Interpreting Results

### Strong Standalone Performer
- **Sharpe > 1.5**
- Win Rate > 58%
- Low max drawdown (<25%)
- **Action:** Add to production config, test combinations

### Moderate Standalone Performer
- **Sharpe 0.8-1.5**
- Win Rate 52-58%
- **Action:** Test in combination with current config

### Weak Standalone Performer
- **Sharpe < 0.5**
- Win Rate < 52%
- **Action:** Likely not worth using, even in combinations

### Comparison to Phase 1/2

| Metric | Phase 1 Best (Marubozu) | Phase 2 Config | Phase 3 Target |
|--------|-------------------------|----------------|----------------|
| Sharpe | 2.576 | 0.310 | >0.8 standalone |
| Win Rate | 63.43% | 56.4% | >55% |
| Avg P&L | N/A | +1.067% | >0.5% |

## Troubleshooting

### Backtest Failures
If backtests fail:
- Check Docker container is running: `docker ps | grep bluehorseshoe`
- Check MongoDB is accessible
- Ensure enough historical data for selected dates
- Check logs: `docker exec bluehorseshoe tail -50 src/logs/blueHorseshoe.log`

### Config Not Restoring
If weights.json doesn't restore properly:
```bash
# Manual restore from backup
cp src/weights.json.phase3_backup src/weights.json

# Or restore production config
cp src/weights.json.phase1_production_backup src/weights.json
```

### Out of Memory
If running all 640 tests causes memory issues:
- Test in smaller batches (1-2 indicators at a time)
- Reduce runs per config: `--runs 10` instead of 20
- Restart Docker between batches: `docker restart bluehorseshoe`

## Expected Timeline

**Quick Validation (1 indicator, 1 weight, 5 runs):** 15-30 minutes
**Single Indicator (4 weights, 20 runs each):** 2-3 hours
**Full Phase 3A (all 8 indicators):** 12-24 hours

## Next Steps After Phase 3A

1. **Analyze Results:** Calculate Sharpe, win rate, drawdown for each indicator
2. **Rank Indicators:** Order by standalone performance
3. **Compare to Phase 1/2:** Are any Phase 3 indicators competitive?
4. **Phase 3B:** Test top performers in combination with current production config
5. **Update Production:** If any Phase 3 indicator improves 0.310 Sharpe baseline

## Quick Reference Commands

```bash
# Validation run (5 runs)
python src/run_phase3_testing.py --indicator RS --weight 1.0 --runs 5

# Full single indicator
python src/run_phase3_testing.py --indicator RS --runs 20

# Full Phase 3A (all indicators)
python src/run_phase3_testing.py --indicator all --runs 20

# Custom date range
python src/run_phase3_testing.py --indicator VWAP --runs 20 \
    --start-date 2025-01-01 --end-date 2026-01-27

# Check results
tail -100 src/logs/backtest_log.csv
```

---

**Created:** 2026-01-31
**Status:** Ready for Testing
