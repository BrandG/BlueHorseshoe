# Next Session: Implement Expected P&L Sorting

**Date:** February 14, 2026
**Priority:** HIGH - Critical fix for Wide Barbell filter

---

## Quick Summary

✅ **Completed:** Wide Barbell filter deployed (keeps scores 4-6 OR 12+)
❌ **Problem:** Sorting by score puts best trades (4-5) at BOTTOM of report
🔧 **Solution:** Sort by expected P&L instead

---

## The Issue

**Current flow:**
1. Filter keeps scores 4-6 and 12+ ✓
2. Sort by score DESC ❌
3. Result: Scores 30+ show first, scores 4-5 never seen

**Why this matters:**
- Score 4-5: 1.88% avg P&L (BEST!)
- Score 12-13: 0.19-0.22% avg P&L (worst of filtered)
- User never sees the best trades!

---

## Implementation Task

### File: `src/bluehorseshoe/analysis/strategy.py`

### Change 1: Add constant after imports (line ~51)

```python
# After: from bluehorseshoe.reporting.report_generator import ReportWriter, ReportSingleton

EXPECTED_PNL_BY_SCORE = {
    4.0: 1.88, 4.5: 1.88, 5.0: 0.82, 5.5: 0.82, 6.0: 0.44,
    12.0: 0.22, 13.0: 0.19, 14.0: 0.39, 15.0: 0.83,
    16.0: 0.24, 17.0: 0.73, 18.0: 0.94
}
```

### Change 2: Replace sorting (line ~870)

**Find:**
```python
candidates.sort(key=lambda x: x['score'], reverse=True)
```

**Replace with:**
```python
def get_expected_pnl(candidate):
    score_key = round(candidate['score'] * 2) / 2
    return EXPECTED_PNL_BY_SCORE.get(score_key, candidate['score'] * 0.05)

candidates.sort(key=get_expected_pnl, reverse=True)
logging.info("Sorted %d candidates by expected P&L (top score: %.1f)",
             len(candidates), candidates[0]['score'] if candidates else 0)
```

---

## Test

```bash
docker exec bluehorseshoe python src/main.py -p --limit 100
```

**Expected:** Top 5 should include scores 4.0-5.0

---

## New Ranking Order

After implementation:
1. 4.0 (1.88%) ← BEST
2. 4.5 (1.88%)
3. 18.0 (0.94%)
4. 15.0 (0.83%)
5. 5.0 (0.82%)
6. 5.5 (0.82%)
7. 17.0 (0.73%)
...
11. 12.0 (0.22%)
12. 13.0 (0.19%) ← Weakest

**True barbell:** Best lows + best highs at top!

---

## ML Model Strategy Update

✅ **Keep for optimization:**
- Stop-loss prediction (trade-specific)
- Profit target prediction (trade-specific)

❌ **Don't use for ranking:**
- Win probability (miscalibrated - favors score 8-9)

📊 **Use for ranking:**
- Historical expected P&L (more accurate, 11,960 trades)

---

**Status:** Ready to implement (~10 minutes)
**Risk:** Low (just sorting change)
**Impact:** High (+400% improvement in top 5 quality)

See `EXPECTED_PNL_SORTING_IMPLEMENTATION.md` for full details.
