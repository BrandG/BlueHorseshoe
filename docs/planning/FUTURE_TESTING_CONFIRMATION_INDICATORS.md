# Future Testing: Confirmation Indicator Ensemble Testing

**Status:** 📋 Planned (Post-Phase 3E)
**Created:** February 12, 2026
**Priority:** Medium (after Q4 completion and production optimization)

---

## 🎯 Objective

Test indicators that **failed isolated testing** to see if they add value as **confirmation filters** when combined with the optimized production system.

### Hypothesis

Some indicators may not work well in isolation but could improve performance when added to an already-strong ensemble by:
- Filtering out false positives
- Confirming signals from primary indicators
- Reducing drawdowns or improving risk-adjusted returns

---

## 📋 Methodology

### Phase 1: Establish Production Baseline

**Prerequisites:**
- ✅ Phase 3E Q4 complete
- ✅ All validated indicators deployed
- ✅ Production weights optimized
- ✅ System stable and performing

**Steps:**
1. **Select test dates:** Generate 50 random market dates from 2024-01-01 to 2026-01-27
2. **Save dates:** Store in `src/logs/confirmation_test_dates.txt` (ensures reproducibility)
3. **Run baseline:** Execute 50 backtests with production weights
   ```bash
   # For each date in test set
   docker exec bluehorseshoe python src/main.py -t $date
   ```
4. **Calculate baseline metrics:**
   - Average Sharpe ratio
   - Win rate
   - Total P&L
   - Average trade count per date
   - Max drawdown

5. **Save results:** `src/logs/confirmation_baseline.csv`

---

### Phase 2: Test Each Confirmation Indicator

**For each candidate indicator:**

#### Test Setup
```json
// Example: Testing Ichimoku as confirmation
{
  "trend": {
    // All production weights stay THE SAME
    "ADX_MULTIPLIER": 1.0,
    "HEIKEN_ASHI_MULTIPLIER": 1.5,
    "DONCHIAN_MULTIPLIER": 1.5,
    "TTM_SQUEEZE_MULTIPLIER": 2.0,
    "AROON_MULTIPLIER": 1.0,
    "KELTNER_MULTIPLIER": 1.5,
    "PSAR_MULTIPLIER": 0.5,  // Assuming Q3 deployed

    // ADD CONFIRMATION INDICATOR
    "ICHIMOKU_MULTIPLIER": 0.3  // <-- TEST THIS
  },
  // ... all other categories stay at production weights
}
```

#### Test Protocol

**For each weight (0.3x, 0.5x, 0.7x):**

1. **Update weights.json** with confirmation indicator at test weight
2. **Run same 50 dates** from baseline (CRITICAL: use exact same dates)
3. **Save results:** `src/logs/confirmation_test_INDICATOR_WEIGHTx.csv`
4. **Calculate metrics** (same as baseline)
5. **Compare to baseline:**
   - Sharpe delta (e.g., +0.15 or -0.05)
   - Win rate delta
   - P&L delta
   - Trade count delta

#### Success Criteria

**Deploy if:**
- ✅ Sharpe improves by ≥0.10 (e.g., 0.85 → 0.95)
- ✅ Win rate improves OR stays within -2%
- ✅ P&L improves
- ✅ Trade count doesn't drop below 80% of baseline
- ✅ Improvement is statistically significant (not random noise)

**Reject if:**
- ❌ Sharpe decreases or improves <0.05
- ❌ Win rate drops >2%
- ❌ Trade count drops significantly (suggests over-filtering)

---

## 📊 Candidate Confirmation Indicators

### From Phase 3E (Failed Isolation)

| Indicator | Isolated Sharpe | Isolated Trades | Reason for Failure | Confirmation Potential |
|-----------|-----------------|-----------------|-------------------|----------------------|
| **Ichimoku Cloud** | 0.059 to 2.773* | 18-73 | Low weight: too few trades<br>Mid weight: poor performance | **Medium** - Complex system, might filter well |
| **Stochastic** | TBD | TBD | From Q1 testing | **Low** - Simple momentum indicator |
| **PSAR 1.0x** | -1.336 | 73 | Negative Sharpe | **Low** - 0.5x works, 1.0x hurts |
| **PSAR 1.5x** | 11.592* | 8 | Too few trades | **Low** - Unreliable signal |

*Invalid: did not meet statistical threshold

### From Previous Phases (Not Yet Tested)

| Indicator | Category | Confirmation Potential | Notes |
|-----------|----------|----------------------|-------|
| **RSI** | Momentum | **High** | Classic confirmation, untested in isolation |
| **MACD** | Momentum | **High** | Widely used trend confirmation |
| **Bollinger Bands** | Momentum | **Medium** | Already used in mean reversion, might help baseline |
| **OBV** | Volume | **Medium** | Volume confirmation, untested |
| **CMF** | Volume | **Medium** | Chaikin Money Flow, untested |
| **MFI** | Volume | **Medium** | Money Flow Index, untested |
| **ROC** | Momentum | **Low** | Rate of Change, less commonly used |

---

## 🔬 Testing Phases

### Phase A: High-Priority Confirmations (First)
1. **RSI** (0.3x, 0.5x, 0.7x)
2. **MACD** (0.3x, 0.5x, 0.7x)
3. **Ichimoku** (0.3x, 0.5x, 0.7x)

**Estimated time:** 3-4 hours per indicator × 3 = 9-12 hours total

### Phase B: Medium-Priority Confirmations (If Phase A shows promise)
1. **OBV** (0.3x, 0.5x, 0.7x)
2. **CMF** (0.3x, 0.5x, 0.7x)
3. **MFI** (0.3x, 0.5x, 0.7x)
4. **Bollinger Bands** (0.3x, 0.5x, 0.7x)

**Estimated time:** 12-16 hours total

### Phase C: Low-Priority (Only if needed)
- Indicators that failed badly in isolation
- Exotic or niche indicators

---

## 📁 File Structure

```
src/logs/
  confirmation_test_dates.txt           # 50 random dates for reproducibility
  confirmation_baseline.csv             # Baseline performance (production weights only)
  confirmation_test_RSI_03x.csv         # RSI at 0.3x results
  confirmation_test_RSI_05x.csv         # RSI at 0.5x results
  confirmation_test_RSI_07x.csv         # RSI at 0.7x results
  confirmation_test_MACD_03x.csv
  confirmation_test_MACD_05x.csv
  ...
  confirmation_analysis.csv             # Summary comparison table

src/
  run_confirmation_baseline.sh          # Script to run baseline
  run_confirmation_test.sh              # Script to test one indicator at one weight
  analyze_confirmation_results.py       # Analysis script
```

---

## 🚀 Execution Plan

### When to Start
**Trigger conditions:**
- ✅ Phase 3E Q4 complete
- ✅ All validated indicators deployed
- ✅ System running smoothly for 1-2 weeks
- ✅ User satisfied with current performance

**Timeline:** Estimated 2-3 days of compute time (can run overnight)

### Execution Steps

1. **Generate test dates:**
   ```python
   # Create reproducible random date set
   import random
   from datetime import datetime, timedelta

   random.seed(42)  # Fixed seed for reproducibility
   start = datetime(2024, 1, 1)
   end = datetime(2026, 1, 27)

   dates = []
   for i in range(50):
       random_days = random.randint(0, (end - start).days)
       date = start + timedelta(days=random_days)
       dates.append(date.strftime('%Y-%m-%d'))

   # Save to file
   with open('src/logs/confirmation_test_dates.txt', 'w') as f:
       f.write('\n'.join(dates))
   ```

2. **Run baseline:** `./src/run_confirmation_baseline.sh`

3. **For each indicator:** `./src/run_confirmation_test.sh INDICATOR WEIGHT`

4. **Analyze results:** `python src/analyze_confirmation_results.py`

5. **Deploy winners** (if any)

---

## 📊 Expected Outcomes

### Optimistic Scenario
- 1-2 confirmation indicators improve Sharpe by 0.1-0.2
- Final system: 18-20 indicators (primary + confirmations)
- Sharpe improvement: 5-15%

### Realistic Scenario
- 0-1 confirmation indicators provide marginal improvement
- Most indicators don't add value (already captured by ensemble)
- Confirms that isolation testing was effective

### Learning Outcome (Either Way)
- ✅ Validates or invalidates ensemble hypothesis
- ✅ Identifies optimal system size (diminishing returns point)
- ✅ Provides data for future indicator selection

---

## 🔧 Implementation Scripts (To Be Created)

### 1. `src/run_confirmation_baseline.sh`
```bash
#!/bin/bash
# Run baseline performance test with production weights

echo "Running Confirmation Testing Baseline"
echo "======================================"

dates_file="src/logs/confirmation_test_dates.txt"
output_file="src/logs/confirmation_baseline.csv"

# Clear previous results
> $output_file

# Run backtests for each date
while IFS= read -r date; do
  echo "Testing date: $date"
  docker exec bluehorseshoe python src/main.py -t $date
done < "$dates_file"

# Copy results
cp src/logs/backtest_log.csv $output_file

echo "Baseline complete. Results saved to $output_file"
```

### 2. `src/run_confirmation_test.sh`
```bash
#!/bin/bash
# Test a single confirmation indicator at a specific weight

indicator=$1  # e.g., "ICHIMOKU"
weight=$2     # e.g., "0.3"

if [ -z "$indicator" ] || [ -z "$weight" ]; then
  echo "Usage: ./run_confirmation_test.sh INDICATOR WEIGHT"
  exit 1
fi

echo "Testing Confirmation: $indicator at ${weight}x"
echo "============================================="

# Backup current weights
cp src/weights.json src/weights.json.backup

# Modify weights.json to add confirmation indicator
# (Requires python script or manual edit)
python src/scripts/add_confirmation_indicator.py $indicator $weight

# Run backtests on same dates
dates_file="src/logs/confirmation_test_dates.txt"
output_file="src/logs/confirmation_test_${indicator}_$(echo $weight | tr '.' '')x.csv"

while IFS= read -r date; do
  echo "Testing date: $date"
  docker exec bluehorseshoe python src/main.py -t $date
done < "$dates_file"

# Save results
cp src/logs/backtest_log.csv $output_file

# Restore original weights
cp src/weights.json.backup src/weights.json

echo "Test complete. Results saved to $output_file"
```

### 3. `src/analyze_confirmation_results.py`
```python
#!/usr/bin/env python3
"""
Analyze confirmation indicator testing results.
Compare each test configuration to baseline.
"""

import pandas as pd
import numpy as np
from pathlib import Path

# Load baseline
baseline = pd.read_csv('src/logs/confirmation_baseline.csv')

# Calculate baseline metrics
# ... (similar to existing analysis scripts)

# Load test results
test_files = Path('src/logs').glob('confirmation_test_*.csv')

results = []
for test_file in test_files:
    # Parse indicator and weight from filename
    # Calculate metrics
    # Compare to baseline
    # ...

# Generate comparison report
# ...
```

---

## 📝 Notes

- **Reproducibility:** Using fixed dates ensures apples-to-apples comparison
- **Statistical validity:** 50 dates provides ~500-1000 trades for reliable metrics
- **Low risk:** Testing doesn't affect production system until winners are deployed
- **Cost:** ~20-30 hours compute time total (can run in background)
- **Benefit:** Maximizes system performance by testing ensemble effects

---

## ✅ Success Definition

**This testing phase is successful if:**
1. We definitively know whether confirmation indicators help
2. Any deployed indicators improve Sharpe by ≥0.10
3. We validate that isolation testing captured most signal value
4. System architecture is optimized (right number of indicators)

**Even if no indicators pass:** We learn that the isolation methodology was effective and the system is already well-optimized.

---

**Created by:** Claude Code
**Date:** February 12, 2026
**Status:** Awaiting Phase 3E completion before execution
