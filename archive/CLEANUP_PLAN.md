# Phase 3 Testing Cleanup Plan
**Date:** February 12, 2026

## Files to Archive (move to archive/):
### Old Test Logs (keep analysis CSVs, archive raw logs)
- phase3a_test_run.log
- phase3b_test_run.log  
- phase3d_test_run.log
- phase3e_q3.log (superseded by phase3e_q3_parallel.log)
- phase3e_q3_rerun.log

### Old Backtest Logs (superseded by current backtest_log.csv)
- phase3a_backtest_log.csv
- phase3b_backtest_log.csv
- phase3c_backtest_log.csv
- phase3d_backtest_log.csv
- backtest_log_fixed.csv

### Old Test Scripts (superseded by phase3e scripts)
- run_phase3_priority.sh
- run_phase3_sequential.sh
- run_phase3b_testing.sh
- run_phase3c_testing.sh
- run_phase3d_testing.sh
- test_phase3_simple.sh

### Old Weight Backups (keep 2 most recent)
- weights.json.phase1_production_backup
- weights.json.phase3d_backup
- weights.json.phase3d_deployed
- weights.json.before_ichimoku_test

## Files to Delete (no longer needed)
### Empty/Debug Logs
- fail_script.log (0 bytes)
- test.log (6 bytes)
- mean_reversion_backtest.log (0 bytes)
- rebuild_jan05.log (0 bytes)

### Old Debugging CSVs
- failure_analysis.csv
- failure_analysis_baseline.csv
- failure_analysis_mean_reversion.csv

### Very Old Logs
- backfill_v2.log (from Jan 14)
- maintenance_overviews_news.log (from Jan 4)
- ml_training.log (from Jan 4)
- data_audit.log (from Jan 20)

## Files to KEEP (important)
### Analysis Results
- All phase3e_q*_analysis.csv files
- psar_05_combined_analysis.csv
- phase3a/b_analysis_corrected.csv
- audit_report.csv
- indicator_analysis_report.csv

### Current Logs
- blueHorseshoe.log (active)
- backtest_log.csv (current)

### Current Scripts
- All phase3e_q*.sh scripts (reproducibility)
- retest_psar_05.sh (reproducibility)
- cron_weekly_retrain.sh (active)

### Current Weights
- weights.json (production)
- weights.json.pre_phase3e_final (latest backup - 17 indicators)
- weights.json.phase3e_backup (17 indicators, pre Q3/Q4)

## Estimated Space Savings
- Archive: ~2.5 MB
- Delete: ~3.5 MB
- Total freed: ~6 MB (78% reduction)
- Remaining: ~1.7 MB
