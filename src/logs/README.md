# Logs Directory

This directory contains logs, reports, and prediction archives for the BlueHorseshoe trading system.

## Directory Structure

```
src/logs/
├── README.md                      # This file
├── PREDICTIONS_TRACKING.md        # Trade log and outcomes tracking
├── report_YYYY-MM-DD.html         # Daily prediction reports (HTML)
├── predictions_archive/           # Long-term archive (optional)
├── phase3a_backtest_log.csv      # Phase 3A testing results
├── phase3b_backtest_log.csv      # Phase 3B testing results
├── phase3c_backtest_log.csv      # Phase 3C testing results
├── phase3d_backtest_log.csv      # Phase 3D testing results
├── phase3X_analysis.csv          # Analysis summaries per phase
└── *.log                          # System logs (gitignored)
```

## Prediction Reports

### Naming Convention
- **Format:** `report_YYYY-MM-DD.html`
- **Date Meaning:** The TRADING DAY (not prediction date)
- **Example:** `report_2026-02-09.html` = predictions for Monday Feb 9, 2026

### Report Contents
Each HTML report includes:
- Top 50 baseline (trend-following) candidates
- Top 50 mean reversion (dip-buying) candidates
- Entry prices, stop losses, and targets
- ML win probability predictions
- Risk/reward ratios
- Position sizing calculator widget
- Interactive charts and tables

### Archive Policy
**NEVER DELETE PREDICTION REPORTS!**

These reports are our audit trail and proof of system performance. They allow us to:
1. Track prediction accuracy over time
2. Compare ML predictions vs actual outcomes
3. Demonstrate system performance to others
4. Learn from past predictions
5. Build confidence in the system

## Tracking Predictions

Use `PREDICTIONS_TRACKING.md` to record:
1. **Before trading:** Top candidates from the prediction
2. **After execution:** Actual entry prices and position details
3. **After close:** Outcome (WIN/LOSS), P&L, and notes

This creates a complete audit trail from prediction → execution → outcome.

## Backtest Logs

Phase 3 CSV files contain detailed backtest results:
- Each row = one simulated trade
- Columns: date, symbol, strategy, score, entry, stop, target, outcome, P&L
- Used to validate indicator performance before deployment

## File Retention

### Keep Forever
- ✅ All `report_*.html` files
- ✅ Phase 3 backtest CSVs
- ✅ Phase 3 analysis CSVs
- ✅ PREDICTIONS_TRACKING.md

### Auto-cleaned (gitignored)
- 🗑️ `*.log` files (system logs, regenerated)
- 🗑️ `*.txt` files (temporary reports)
- 🗑️ `*.html` in other directories (graphs)

## Git Strategy

Prediction reports and backtest logs are **committed to git** to preserve the historical record. This ensures:
- Predictions can't be altered after the fact
- Complete audit trail is preserved
- Performance can be verified by anyone

---

**Last Updated:** 2026-02-08
**System Version:** 14 indicators (Phase 3D deployed)
