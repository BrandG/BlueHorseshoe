# Email-Friendly Report Generation

**Status:** ✅ Implemented and Tested (Feb 11, 2026)

## Overview

The system now generates **two versions** of every report:
1. **Full Interactive Report** - With charts, JavaScript, dark mode toggle, calculator
2. **Email-Friendly Report** - Simplified HTML optimized for email clients

## Changes Made

### 1. HTMLReporter (`src/bluehorseshoe/reporting/html_reporter.py`)

**New Method: `generate_email_report()`**
- Simplified HTML with no JavaScript
- No interactive elements (dark mode toggle, share calculator)
- No embedded charts or sparklines
- Inline CSS optimized for email clients
- Focus on core data: top candidates tables and previous performance
- ~70% smaller file size (8KB vs 27KB)

**New Method: `save_both()`**
- Saves both full and email-friendly versions
- Naming convention: `report_YYYY-MM-DD.html` and `report_YYYY-MM-DD_email.html`

### 2. Main CLI (`src/main.py`)

**Updated Sections:**
- Prediction flow (`-p` flag) - Lines 188-207
- Report regeneration (`-r` flag) - Lines 284-302

**Changes:**
- Now generates both report versions
- Logs both file paths
- Both versions available for local viewing

### 3. API Tasks (`src/bluehorseshoe/api/tasks.py`)

**Updated Task: `generate_report_task()`**
- Generates both versions in daily pipeline
- Returns paths for both versions
- Email task receives email-friendly path

### 4. Email Service (`src/bluehorseshoe/core/email_service.py`)

**Updated Method: `send_report()`**
- Automatically detects email-friendly version (`*_email.html`)
- Uses email-friendly version for email body if available
- Falls back to full report if email version doesn't exist
- Still attaches full interactive report as file attachment

## Email-Friendly Features

### What's Included ✅
- Market regime summary table
- Top 5 Baseline (Trend Following) candidates
- Top 5 Mean Reversion candidates
- Complete candidate tables with scores, prices, stop-loss, targets
- Previous day performance tracking
- Clickable Yahoo Finance links
- Clean responsive design

### What's Removed ❌
- JavaScript (theme toggle, calculator)
- Collapsible sections (details/summary)
- Embedded candlestick sparklines (base64 images)
- Chart.js graphs
- Interactive elements
- Complex CSS that email clients don't support

## File Naming Convention

```
report_YYYY-MM-DD.html        # Full interactive version
report_YYYY-MM-DD_email.html  # Email-friendly version
```

## Testing

### Generate Both Versions
```bash
# Predict and generate reports
docker exec bluehorseshoe python src/main.py -p

# Regenerate from existing scores
docker exec bluehorseshoe python src/main.py -r 2026-02-10
```

### Verify Files
```bash
ls -lh src/logs/report_*_email.html
```

### Test Email Logic
```python
from bluehorseshoe.core.email_service import EmailService
service = EmailService()
# Will automatically use email-friendly version if it exists
service.send_report('src/logs/report_2026-02-10.html')
```

## Daily Pipeline Behavior

**Automated Workflow (8:00 AM UTC):**
1. Update market data
2. Generate predictions
3. Create both report versions:
   - Full: `src/logs/report_YYYY-MM-DD.html`
   - Email: `src/logs/report_YYYY-MM-DD_email.html`
4. Send email:
   - Body: Email-friendly version (simplified, no JS)
   - Attachment: Full interactive version (for offline viewing)

## Benefits

### For Email Clients
- ✅ No JavaScript security concerns
- ✅ Faster loading (70% smaller)
- ✅ Better rendering compatibility
- ✅ Works in mobile email apps
- ✅ Inline CSS for consistent styling

### For Users
- ✅ Quick data review in email
- ✅ Full interactive report still attached
- ✅ Best of both worlds
- ✅ No loss of functionality

## Future Enhancements

Potential improvements:
- [ ] Add inline data visualizations using Unicode charts (▁▂▃▄▅▆▇█)
- [ ] Include key metrics summary at top (total candidates, win rate, etc.)
- [ ] Add risk warnings or market alerts
- [ ] Optimize for dark mode email clients
- [ ] A/B test different layouts

## Notes

- Email-friendly version is generated alongside full report (no extra API calls)
- Both versions use the same data source
- File size reduction: ~70% (27KB → 8KB)
- No changes required to existing workflows
- Backward compatible (falls back to full report if email version missing)

---

**Last Updated:** February 11, 2026
**Implementation Status:** ✅ Complete and Tested
