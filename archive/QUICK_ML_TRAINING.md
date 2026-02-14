# Quick ML Profit Target Training Guide

## TL;DR - Get Training Data Fast

Instead of waiting 7-14 days for future data, **backfill predictions on historical dates** that already have future data available!

### 🚀 Quick Start (3 Steps)

```bash
# 1. Backfill 25 historical predictions (~20-25 hours)
docker exec bluehorseshoe python /workspaces/BlueHorseshoe/backfill_predictions.py \
    --start 2026-01-06 \
    --count 25

# 2. Train the models (~10 minutes)
docker exec bluehorseshoe python src/train_profit_target.py 10000

# 3. Done! Models now active
ls -lh src/models/ml_profit_target_*.joblib
```

### ⚡ Fast Test Version (2-3 hours)

```bash
# Test with limited symbols (100 per date)
docker exec bluehorseshoe python /workspaces/BlueHorseshoe/backfill_predictions.py \
    --start 2026-01-06 \
    --count 25 \
    --limit 100

# Then train
docker exec bluehorseshoe python src/train_profit_target.py 5000
```

## How It Works

### The Problem
```
Normal Flow:
  Day 1: Generate prediction → Save scores
  Day 2-10: Wait...
  Day 11: Grade prediction (now have 10 days future data)

  Result: 7-14 days to get enough samples
```

### The Solution
```
Backfill Flow:
  Jan 6: Predict → Grade immediately ✅ (Feb data exists)
  Jan 7: Predict → Grade immediately ✅
  Jan 8: Predict → Grade immediately ✅
  ...
  Feb 5: Predict → Grade immediately ✅

  Result: 5,000+ samples in 24 hours!
```

## Commands Explained

### Basic Backfill
```bash
docker exec bluehorseshoe python /workspaces/BlueHorseshoe/backfill_predictions.py \
    --start 2026-01-06 \  # Start date (YYYY-MM-DD)
    --count 25            # Number of trading dates
```

**Output:**
- 25 predictions on historical dates (Jan 6 - Feb 7)
- ~200 candidates per date
- ~5,000 total scored trades
- All immediately gradable (future data exists)

### Fast Test Mode
```bash
docker exec bluehorseshoe python /workspaces/BlueHorseshoe/backfill_predictions.py \
    --start 2026-01-06 \
    --count 25 \
    --limit 100  # Only process 100 symbols per date
```

**Tradeoff:**
- ✅ 10x faster (~2-3 hours vs 20-25 hours)
- ⚠️ Fewer samples (~2,500 vs ~5,000)
- ✅ Still enough for training

## Training After Backfill

Once backfill completes:

```bash
# Train all 3 models
docker exec bluehorseshoe python src/train_profit_target.py 10000
```

**Models created:**
- `ml_profit_target_v1.joblib` - General model
- `ml_profit_target_baseline.joblib` - Trend-following
- `ml_profit_target_mean_reversion.joblib` - Dip buying

## Verification

### Check Scores
```bash
docker exec bluehorseshoe python -c "
from bluehorseshoe.core.container import create_app_container
c = create_app_container()
db = c.get_database()
with_meta = db['trade_scores'].count_documents({'metadata.entry_price': {'$exists': True}})
print(f'Scores ready for grading: {with_meta}')
c.close()
"
```

### Check Models
```bash
ls -lh src/models/ml_profit_target_*.joblib
```

Should show 3 files with timestamps after training.

### Test Predictions
```bash
# Run prediction with trained models
docker exec bluehorseshoe python src/main.py -p --limit 10

# Check for dynamic profit targets
grep "profit_multiplier" src/logs/blueHorseshoe.log
```

Should see varying multipliers (not all 3.0 or 2.0).

## Time Estimates

| Configuration | Time | Samples | Good For |
|--------------|------|---------|----------|
| Full (25 dates) | 20-25 hours | ~5,000 | Production |
| Limited 100 (25 dates) | 2-3 hours | ~2,500 | Testing |
| Limited 50 (10 dates) | 1 hour | ~500 | Quick test |

## Monitoring Progress

### Check Current Status
```bash
# Background run
tail -f /workspaces/BlueHorseshoe/src/logs/backfill_predictions.log
```

### Check Reports Created
```bash
ls -lh src/logs/report_2026-01-*.html | wc -l
```

Shows number of completed predictions.

## Alternative: Manual Single Date

If you just want to test with one date:

```bash
# Predict on specific historical date
docker exec bluehorseshoe python src/main.py -p 2026-01-15

# Check it was saved
docker exec bluehorseshoe python -c "
from bluehorseshoe.core.container import create_app_container
c = create_app_container()
db = c.get_database()
count = db['trade_scores'].count_documents({'date': '2026-01-15'})
print(f'Scores for 2026-01-15: {count}')
c.close()
"
```

## Recommended Workflow

### For Production Models
```bash
# 1. Run full backfill overnight
docker exec bluehorseshoe python /workspaces/BlueHorseshoe/backfill_predictions.py \
    --start 2026-01-06 --count 25

# 2. Train next morning
docker exec bluehorseshoe python src/train_profit_target.py 10000

# 3. Verify
ls -lh src/models/ml_profit_target_*.joblib
```

### For Quick Testing
```bash
# 1. Run limited backfill (2-3 hours)
docker exec bluehorseshoe python /workspaces/BlueHorseshoe/backfill_predictions.py \
    --start 2026-01-06 --count 25 --limit 100

# 2. Train with fewer samples
docker exec bluehorseshoe python src/train_profit_target.py 5000

# 3. Test prediction
docker exec bluehorseshoe python src/main.py -p --limit 10
```

## Cleanup (Optional)

After training, you can remove backfilled reports:

```bash
# Keep scores in MongoDB, remove HTML reports
rm src/logs/report_2026-01-*.html
```

Scores stay in database for future retraining.

## Full Documentation

See `BACKFILL_PREDICTIONS_GUIDE.md` for complete details, troubleshooting, and advanced options.

---

**Summary:** Backfill 25 historical predictions → Train models → Start using adaptive profit targets!
**Time:** ~24 hours start to finish (or 2-3 hours with `--limit`)
**Result:** Production-ready ML profit target models
