# Current Work Status - RSI Indicator Testing

**Date:** 2026-01-21
**Status:** In Progress (Test Interrupted)

## What We're Doing

Testing the RSI (Relative Strength Index) indicator in isolation to understand its performance contribution to the baseline strategy. This is part of Phase 1 testing to evaluate individual indicators.

## Test Configuration

- **Indicator:** RSI
- **Multiplier:** 1.0 (default)
- **Runs:** 20 backtests with random historical dates
- **Strategy:** baseline (trend-following)
- **Experiment Name:** test_rsi_baseline

## Current Status

❌ **Test was interrupted at ~55% completion of run 1/20**

The test configuration file was created:
- `src/experiments/results/test_rsi_baseline_config.json` ✓

But the results file was NOT completed:
- `src/experiments/results/test_rsi_baseline.json` ✗ (missing)

## How to Resume

Run the complete test (will take ~10-15 minutes):

```bash
docker exec bluehorseshoe python src/run_isolated_indicator_test.py \
  --indicator RSI \
  --runs 20 \
  --name test_rsi_baseline
```

**Alternative:** Run it detached so it survives session closure:

```bash
docker exec -d bluehorseshoe sh -c "python src/run_isolated_indicator_test.py --indicator RSI --runs 20 --name test_rsi_baseline > /tmp/rsi_test.log 2>&1"

# Check progress later with:
tail -f /tmp/rsi_test.log

# Or check if it completed:
ls -la src/experiments/results/test_rsi_baseline.json
```

## What Happens Next

Once the test completes, you'll have:
1. **Results file:** `src/experiments/results/test_rsi_baseline.json` with:
   - Win rate across 20 backtest runs
   - Average P&L per trade
   - Sharpe ratio
   - Max drawdown
   - Trade statistics

2. **Next Steps:**
   - Review the RSI baseline performance
   - Test RSI with different multipliers (0.5, 1.5, 2.0) to find optimal weight
   - Compare results using `src/compare_experiments.py`
   - Test other indicators in isolation
   - Move to Phase 2: ensemble optimization

## Reference Documents

- **Testing Guide:** `PHASE1_TESTING_GUIDE.md` - Complete guide for Phase 1 testing
- **Test Script:** `src/run_isolated_indicator_test.py` - The test runner
- **Compare Script:** `src/compare_experiments.py` - Statistical comparison tool

## Context

We're systematically testing indicators because:
1. The current system uses 40+ indicators with equal weights
2. We don't know which ones actually contribute value
3. Some indicators might be redundant or even harmful
4. Phase 1 isolates each indicator to measure its independent contribution
5. Phase 2 will optimize combinations of the best performers

## Files Modified Today

- Created `PHASE1_TESTING_GUIDE.md`
- Created `src/run_isolated_indicator_test.py`
- Created `src/compare_experiments.py`
- Modified `src/weights.json` (testing - has backup at `src/weights.json.backup`)
