# Current Work Status - RSI Indicator Testing

**Date:** 2026-01-23
**Status:** Tests killed for droplet resize (2 vCPU → 4 vCPU)
**Branch:** `Tweak_indicators`

## What We're Doing

Testing the RSI (Relative Strength Index) indicator with different multipliers to find the optimal weight for the baseline strategy. This is part of Phase 1 isolated indicator testing.

## Completed Work

### ✅ Phase 1 Testing Framework
- **Committed:** `0339be6` - "feat: Add Phase 1 isolated indicator testing framework"
- **Pushed to GitHub:** Yes
- Created `src/run_isolated_indicator_test.py` - Isolated indicator testing script
- Created `src/compare_experiments.py` - Statistical comparison tool
- Added documentation: `PHASE1_TESTING_GUIDE.md`
- Fixed script to handle missing backup files with git restore fallback

### ✅ RSI Baseline Test (Multiplier 1.0)
- **Status:** Complete
- **Results:** `src/experiments/results/test_rsi_baseline.json`
- **Metrics:**
  - Win Rate: 59.30% (51/86 trades)
  - Sharpe Ratio: 2.47 (excellent)
  - Average P&L: +1.36% per trade
  - Max Drawdown: 22.78%
  - Total P&L: +117.09%
- **Runs:** 20 backtests with random historical dates
- **Conclusion:** RSI contributes positively to baseline strategy

## In Progress (Tests Killed)

### ⏸️ RSI Reduced Weight Test (Multiplier 0.5)
- **Status:** Killed at Run 1/20 (36.8% progress)
- **Experiment Name:** `rsi_reduced`
- **Config:** `src/experiments/results/rsi_reduced_config.json` (exists)
- **Results:** Not yet generated (need to rerun)
- **Purpose:** Test if reducing RSI weight improves performance

### ⏸️ RSI Boosted Weight Test (Multiplier 1.5)
- **Status:** Killed at Run 1/20 (59.8% progress)
- **Experiment Name:** `rsi_boosted`
- **Config:** `src/experiments/results/rsi_boosted_config.json` (exists)
- **Results:** Not yet generated (need to rerun)
- **Purpose:** Test if boosting RSI weight improves performance

## Why Tests Were Killed

**Problem:** Tests were taking 40+ minutes each on 2 vCPU droplet
- Each test spawns 8 threads
- Two tests running simultaneously = 16 threads on 2 cores
- Heavy thread contention causing slowdown

**Solution:** Upgrading droplet to 4 vCPUs
- Expected speedup: 1.5-1.8x faster
- Better for future Phase 1 testing (40+ indicators to test)
- Tests will restart from Run 1/20 after upgrade

## Next Steps (After Droplet Resize)

### 1. Restart Docker Containers
```bash
cd docker && docker compose up -d
```

### 2. Restart RSI Tests (with warnings suppressed)
```bash
# RSI 0.5x test
docker exec bluehorseshoe bash -c "nohup python -u -W ignore src/run_isolated_indicator_test.py --indicator RSI --multiplier 0.5 --runs 20 --name rsi_reduced > rsi_reduced.log 2>&1 &"

# RSI 1.5x test
docker exec bluehorseshoe bash -c "nohup python -u -W ignore src/run_isolated_indicator_test.py --indicator RSI --multiplier 1.5 --runs 20 --name rsi_boosted > rsi_boosted.log 2>&1 &"
```

### 3. Monitor Progress
```bash
# Check progress
docker exec bluehorseshoe tail -50 rsi_reduced.log | grep "Progress:\|Run [0-9]"
docker exec bluehorseshoe tail -50 rsi_boosted.log | grep "Progress:\|Run [0-9]"

# Check if complete
docker exec bluehorseshoe ls -lh src/experiments/results/rsi_reduced.json
docker exec bluehorseshoe ls -lh src/experiments/results/rsi_boosted.json
```

### 4. Compare Results (When Complete)
```bash
# List all experiments
docker exec bluehorseshoe python src/compare_experiments.py --list

# Compare RSI configurations
docker exec bluehorseshoe python src/compare_experiments.py test_rsi_baseline rsi_reduced rsi_boosted
```

### 5. Test Additional RSI Multipliers (Optional)
```bash
# RSI 2.0x test
docker exec bluehorseshoe python src/run_isolated_indicator_test.py --indicator RSI --multiplier 2.0 --runs 20 --name rsi_double
```

### 6. Move to Other Indicators
After finding optimal RSI weight, test other key indicators:
- **Trend:** ADX, MACD, STOCHASTIC
- **Volume:** OBV, CMF, MFI
- **Momentum:** ROC, WILLIAMS_R, CCI

## Important Notes

### Test Runtime Expectations
- **Before upgrade (2 vCPU):** ~40 minutes per test (20 runs)
- **After upgrade (4 vCPU):** ~20-25 minutes per test (estimated)
- Each run processes 10,870 symbols with full indicator calculations

### Warning Suppression
**Critical:** Always use `-W ignore` flag when running tests:
```bash
python -u -W ignore src/run_isolated_indicator_test.py ...
```
Without this, sklearn warnings flood the logs (47-49MB) and severely slow down execution.

### Process Management
**To pause tests:**
```bash
# Find PIDs
docker exec bluehorseshoe python -c "
import os, glob
for d in glob.glob('/proc/[0-9]*'):
    try:
        with open(f'{d}/cmdline') as f:
            if 'run_isolated_indicator_test' in f.read():
                print(os.path.basename(d))
    except: pass
"

# Pause (replace PIDs)
docker exec bluehorseshoe bash -c "kill -STOP <PID1> <PID2>"

# Resume
docker exec bluehorseshoe bash -c "kill -CONT <PID1> <PID2>"

# Kill
docker exec bluehorseshoe bash -c "kill -9 <PID1> <PID2>"
```

## Files to Keep

**Results (keep):**
- `src/experiments/results/test_rsi_baseline.json` ✅ Committed
- `src/experiments/results/test_rsi_baseline_config.json` ✅ Committed
- `src/experiments/results/rsi_reduced_config.json` ✅ Committed
- `src/experiments/results/rsi_boosted_config.json` ✅ Committed

**Temporary files (can delete):**
- `rsi_reduced.log` (5,036 lines from killed test)
- `rsi_boosted.log` (52,823 lines from killed test)
- `rsi_test.log` (old test log)
- `run_rsi_*.sh` (shell scripts)
- `.env` (not in git, keep local)

## Git Status

**Branch:** `Tweak_indicators`
**Status:** Up to date with origin (pushed commit `0339be6`)
**Uncommitted changes:**
- `celerybeat-schedule` (auto-generated, ignore)
- Various untracked files (logs, scripts, etc.)

## Reference Documents

- **Testing Guide:** `PHASE1_TESTING_GUIDE.md` - Complete Phase 1 workflow
- **Test Script:** `src/run_isolated_indicator_test.py` - Isolated indicator tester
- **Compare Script:** `src/compare_experiments.py` - Statistical comparison
- **Architecture:** `SESSION_STATE.md` - Phase 1-3 completion status

## Context for Next Session

We're systematically testing indicators because:
1. The current system uses 40+ indicators with manually-tuned weights
2. We don't know which ones actually contribute value
3. Some indicators might be redundant or harmful
4. Phase 1 isolates each indicator to measure independent contribution
5. Phase 2 will optimize combinations of the best performers

RSI shows strong performance at 1.0x multiplier. Now testing 0.5x and 1.5x to find optimal weight.
