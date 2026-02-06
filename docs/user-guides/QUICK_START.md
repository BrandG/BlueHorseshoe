# Quick Start for Next Session

**Date:** 2026-01-23
**Status:** Ready to restart tests after 4 vCPU upgrade

## Immediate Action Required

### 1. Start Docker (if not running)
```bash
cd /root/BlueHorseshoe/docker && docker compose up -d
```

### 2. Restart RSI Tests
```bash
# Clean up old logs
docker exec bluehorseshoe bash -c "rm -f rsi_reduced.log rsi_boosted.log"

# Start RSI 0.5x test
docker exec bluehorseshoe bash -c "nohup python -u -W ignore src/run_isolated_indicator_test.py --indicator RSI --multiplier 0.5 --runs 20 --name rsi_reduced > rsi_reduced.log 2>&1 &"

# Start RSI 1.5x test
docker exec bluehorseshoe bash -c "nohup python -u -W ignore src/run_isolated_indicator_test.py --indicator RSI --multiplier 1.5 --runs 20 --name rsi_boosted > rsi_boosted.log 2>&1 &"
```

### 3. Monitor Progress
```bash
# Check progress every few minutes
docker exec bluehorseshoe tail -20 rsi_reduced.log | grep "Run [0-9]\|Progress:"
docker exec bluehorseshoe tail -20 rsi_boosted.log | grep "Run [0-9]\|Progress:"

# Check when complete (results files appear)
watch -n 60 'docker exec bluehorseshoe ls -lh src/experiments/results/rsi*.json 2>/dev/null'
```

## What We're Testing

**RSI Indicator Optimization** - Finding the optimal multiplier weight:
- ✅ **1.0x (baseline):** Complete - 59.3% win rate, 2.47 Sharpe
- ⏳ **0.5x (reduced):** Needs to run (20 runs, ~20-25 min)
- ⏳ **1.5x (boosted):** Needs to run (20 runs, ~20-25 min)

## When Tests Complete

### Compare Results
```bash
docker exec bluehorseshoe python src/compare_experiments.py test_rsi_baseline rsi_reduced rsi_boosted
```

This will show:
- Win rate comparison
- P&L comparison
- Statistical significance (t-test, Mann-Whitney U, Chi-square)
- Effect size (Cohen's d)
- Which multiplier is optimal

## Next Indicators to Test

After RSI, test these key indicators:
- ADX (trend strength)
- MACD (momentum)
- OBV (volume)
- CMF (money flow)

## Full Documentation

See `CURRENT_WORK_STATUS.md` for complete details.
