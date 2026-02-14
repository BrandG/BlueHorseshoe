# Expected P&L Sorting - Complete Implementation Guide

**Created:** February 14, 2026
**Status:** Ready to implement
**Estimated Time:** 10 minutes

---

## Expected P&L Values (from 11,960 backtested trades)

```python
EXPECTED_PNL_BY_SCORE = {
    4.0: 1.88,   # Best performers
    4.5: 1.88,
    5.0: 0.82,
    5.5: 0.82,
    6.0: 0.44,
    12.0: 0.22,
    13.0: 0.19,
    14.0: 0.39,
    15.0: 0.83,
    16.0: 0.24,
    17.0: 0.73,
    18.0: 0.94,
}
```

---

## Code Changes

### Location 1: After imports (src/bluehorseshoe/analysis/strategy.py, line ~51)

Insert after: `from bluehorseshoe.reporting.report_generator import ReportWriter, ReportSingleton`

```python

# Expected P&L by score based on historical backtest analysis (11,960 trades)
EXPECTED_PNL_BY_SCORE = {
    4.0: 1.88, 4.5: 1.88, 5.0: 0.82, 5.5: 0.82, 6.0: 0.44,
    12.0: 0.22, 13.0: 0.19, 14.0: 0.39, 15.0: 0.83,
    16.0: 0.24, 17.0: 0.73, 18.0: 0.94
}

```

### Location 2: Sorting logic (src/bluehorseshoe/analysis/strategy.py, line ~870)

**Current:**
```python
        # Sort by score desc
        candidates.sort(key=lambda x: x['score'], reverse=True)
```

**New:**
```python
        # Sort by Expected P&L
        def get_expected_pnl(candidate):
            score_key = round(candidate['score'] * 2) / 2
            return EXPECTED_PNL_BY_SCORE.get(score_key, candidate['score'] * 0.05)
        
        candidates.sort(key=get_expected_pnl, reverse=True)
        logging.info("Sorted %d candidates by expected P&L (top score: %.1f)",
                     len(candidates), candidates[0]['score'] if candidates else 0)
```

---

## Testing

```bash
# Run test prediction
docker exec bluehorseshoe python src/main.py -p --limit 100

# Check logs for sorting message
grep "Sorted.*expected P&L" /workspaces/BlueHorseshoe/src/logs/blueHorseshoe.log | tail -1

# Check top candidates
grep "Top 5" /workspaces/BlueHorseshoe/src/logs/blueHorseshoe.log | tail -10
```

**Success criteria:** Top 5 includes scores 4.0-5.0

---

## Expected Result

**Top 5 candidates after sorting:**
- Could be: 4.0, 4.5, 18.0, 5.0, 15.0
- Expected avg P&L: ~1.3-1.4%
- vs Current: 0.3-0.4% (scores 30-40)

**Impact:** +400% improvement in trade quality!
