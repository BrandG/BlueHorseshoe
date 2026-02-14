# Backfill Predictions for ML Training

## Problem

The ML Profit Target models need graded trades to train on. Grading requires:
1. A scored prediction on date X
2. Future price data (10 days after X) to evaluate the trade

**Waiting for new predictions:** Would take 7-14 days to accumulate enough samples.

## Solution

Generate predictions on **historical dates** that already have future data available!

```
Example: Predict on Jan 6, 2026 → Grade immediately (Feb data exists)
         Predict on Jan 7, 2026 → Grade immediately (Feb data exists)
         ...repeat for 20-30 dates
```

## Quick Start

### Option 1: Python Script (Recommended)

**Basic usage (25 dates starting Jan 6):**
```bash
docker exec bluehorseshoe python /workspaces/BlueHorseshoe/backfill_predictions.py \
    --start 2026-01-06 \
    --count 25
```

**Fast testing (5 dates, 100 symbols each):**
```bash
docker exec bluehorseshoe python /workspaces/BlueHorseshoe/backfill_predictions.py \
    --start 2026-01-06 \
    --count 5 \
    --limit 100
```

**Custom range:**
```bash
docker exec bluehorseshoe python /workspaces/BlueHorseshoe/backfill_predictions.py \
    --start 2026-01-15 \
    --count 30
```

### Option 2: Bash Script

```bash
# 25 dates starting Jan 6
/root/BlueHorseshoe/backfill_predictions_for_training.sh 2026-01-06 25

# Custom start date and count
/root/BlueHorseshoe/backfill_predictions_for_training.sh 2026-01-20 15
```

## What It Does

1. **Generates trading dates** - Skips weekends, generates N trading days
2. **Runs predictions** - Calls `python src/main.py -p DATE` for each date
3. **Saves scores** - Each prediction saves to MongoDB `trade_scores` collection
4. **Creates reports** - Generates HTML reports for each date
5. **Ready to grade** - All scores can be graded immediately (future data exists)

## Parameters

### Python Script

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--start` | 2026-01-06 | Starting date (YYYY-MM-DD) |
| `--count` | 25 | Number of trading dates to process |
| `--limit` | None | Limit symbols per date (for testing) |

### Bash Script

```bash
./backfill_predictions_for_training.sh [START_DATE] [NUM_DATES]
```

| Position | Default | Description |
|----------|---------|-------------|
| 1 | 2026-01-06 | Starting date |
| 2 | 25 | Number of dates |

## Expected Output

### During Execution

```
======================================================================
BACKFILLING PREDICTIONS FOR ML TRAINING
======================================================================
Start Date: 2026-01-06
Count: 25 dates
======================================================================

[1/25] Processing 2026-01-06...
======================================================================
PREDICTING: 2026-01-06
======================================================================
✅ Success: 127 candidates found
   Report: src/logs/report_2026-01-06.html

[2/25] Processing 2026-01-07...
...
```

### After Completion

```
======================================================================
BACKFILL COMPLETE
======================================================================
Total Dates: 25
Successful: 25
Failed: 0

======================================================================
NEXT STEPS
======================================================================
1. Verify scores in MongoDB:
   [command to check]

2. Train profit target models:
   docker exec bluehorseshoe python src/train_profit_target.py 10000

3. Verify models created:
   ls -lh src/models/ml_profit_target_*.joblib
======================================================================
```

## Time Estimates

### Per Date Prediction

- **Full run (all symbols):** ~50-60 minutes
- **Limited (100 symbols):** ~5-7 minutes

### Total Time

| Dates | Full Run | Limited (100) |
|-------|----------|---------------|
| 5     | ~4-5 hours | ~30-40 min |
| 10    | ~8-10 hours | ~1-1.5 hours |
| 25    | ~20-25 hours | ~2-3 hours |

**Recommendation:** Run overnight with full symbol set, or use `--limit` for quick testing.

## Verification

### Check Score Count

```bash
docker exec bluehorseshoe python -c "
from bluehorseshoe.core.container import create_app_container
c = create_app_container()
db = c.get_database()
total = db['trade_scores'].count_documents({})
with_meta = db['trade_scores'].count_documents({'metadata.entry_price': {'$exists': True}})
print(f'Total scores: {total}')
print(f'With metadata: {with_meta}')
c.close()
"
```

### Check Date Range

```bash
docker exec bluehorseshoe python -c "
from bluehorseshoe.core.container import create_app_container
c = create_app_container()
db = c.get_database()
oldest = db['trade_scores'].find_one(sort=[('date', 1)])
newest = db['trade_scores'].find_one(sort=[('date', -1)])
print(f'Oldest: {oldest[\"date\"]}')
print(f'Newest: {newest[\"date\"]}')
c.close()
"
```

### Check Reports

```bash
ls -lh src/logs/report_2026-01-*.html
```

## Training After Backfill

Once backfill is complete:

### 1. Train Models

```bash
docker exec bluehorseshoe python src/train_profit_target.py 10000
```

**Expected output:**
- `src/models/ml_profit_target_v1.joblib`
- `src/models/ml_profit_target_baseline.joblib`
- `src/models/ml_profit_target_mean_reversion.joblib`

### 2. Verify Training

```bash
ls -lh src/models/ml_profit_target_*.joblib
```

Should show 3 files with recent timestamps.

### 3. Test Predictions

```bash
docker exec bluehorseshoe python src/main.py -p --limit 10
```

Check that predictions include `profit_multiplier` in metadata (should vary by trade).

## Troubleshooting

### "No future data available"

Some dates may fail if historical data doesn't extend far enough. This is normal - the script will continue with other dates.

### "Rate limit exceeded"

If you hit Alpha Vantage rate limits, the prediction will pause. This is handled automatically.

### "Out of memory"

If running all symbols causes memory issues:
- Use `--limit 500` to process fewer symbols per date
- Run fewer dates at a time (`--count 10`)

## Clean Up

### Remove Backfilled Reports (Optional)

```bash
rm src/logs/report_2026-01-*.html
```

Scores remain in MongoDB for training, reports are just for reference.

### Keep Only Training Data

The grading engine will extract MFE from scores automatically during training. No manual cleanup needed.

## Summary

**Goal:** Generate 5,000-10,000 graded trades for ML training

**Method:** Predict on 25 historical dates (Jan 6 - Feb 7)
- ~200 candidates per date
- ~5,000 total scored trades
- All immediately gradable

**Time:** ~20-25 hours (run overnight)

**Result:** Ready to train ML profit target models!

---

**Last Updated:** February 13, 2026
