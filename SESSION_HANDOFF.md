# Session Handoff

**Date:** February 18, 2026 (Tuesday afternoon)
**Status:** LOO analysis running in background (~21 hrs total), plan mode for split-exit backtester

---

## What Was Done This Session

### LOO (Leave-One-Out) Weight Analyzer
Built and wired up a full LOO weight analysis system. New CLI flag `-w` runs it.

**New files (uncommitted, untracked):**
- `src/bluehorseshoe/analysis/loo_analyzer.py` — LOO engine: scores all active symbols per date, backtests baseline (all indicators), then backtests each LOO variant (one indicator removed) to measure P&L impact
- `src/bluehorseshoe/analysis/loo_report.py` — Console + CSV report output
- `src/bluehorseshoe/analysis/indicators/detailed_scoring.py` — `DetailedScorer` for per-sub-indicator raw/weighted score collection
- `src/tests/test_loo_analyzer.py` — Tests

**Modified files (uncommitted):**
- `src/main.py` — Added `-w START_DATE [--end] [--interval] [--top] [--hold] [--symbols]` CLI flag
- `src/bluehorseshoe/analysis/indicators/trend_indicators.py` — Extracted `calc_stochastic` closure into `calculate_stochastic()` method (needed for DetailedScorer access)

### Initial LOO Run (small sample)
- First run completed with a narrow date range → only 8 trades in baseline
- Results in `src/logs/loo_analysis_2026-02-18.csv` — too small to be statistically meaningful
- 24 of 28 indicators showed zero P&L delta (same candidates selected regardless)

### Large LOO Run (IN PROGRESS)
**Command:**
```bash
docker exec bluehorseshoe python src/main.py -w 2025-08-01 --end 2026-02-07 --interval 7 --top 50 --hold 10
```
- **28 dates**, 4,428 active symbols per date
- ~45 min per date → estimated ~21 hours total
- Started at 15:39:59 UTC on Feb 18
- Background task output: `/tmp/claude-0/-root-BlueHorseshoe/tasks/b092420.output`
- **Check progress:** `tail -20 /tmp/claude-0/-root-BlueHorseshoe/tasks/b092420.output`
- Will overwrite `src/logs/loo_analysis_2026-02-18.csv` when complete

**NOTE:** This run will likely be killed by the reboot. You'll need to re-launch it:
```bash
docker exec bluehorseshoe python src/main.py -w 2025-08-01 --end 2026-02-07 --interval 7 --top 50 --hold 10
```

---

## Next Task: Split-Exit Backtester (NOT YET STARTED)

We were in plan mode designing a split-exit (two-tranche) backtest mode. No code written yet. The user wants two strategies to compare against the current single-exit approach:

### Plan A: Fixed 2% + Run
- Entry: same as current
- When price reaches entry + 2%: sell 50%, move stop to +2% level
- Remaining 50%: continues with original take_profit target, stop now at +2%
- Time exit still applies to remaining position

### Plan B: ATR-Tiered
- Entry: same as current
- When price reaches entry + 1×ATR: sell 50%, move stop to +1×ATR level
- Remaining 50%: target is entry + 2×ATR, stop at +1×ATR
- Time exit still applies to remaining position

**User's philosophy:** 2% is the success goal, not a consolation prize. Locking in 2% on half the position early is achieving the goal; the second half is upside.

**Key design decisions still needed:**
- New method vs mode parameter on existing `evaluate_prediction()`
- How to handle TradeState for two tranches
- Where ATR comes from for Plan B (LOO's setup_data has it; -t backtest path may need it added to prediction dict)
- Blended P&L format compatible with both LOO accumulator and -t CSV logger

**Relevant files to read:**
- `src/bluehorseshoe/analysis/backtest.py` — current backtester (BacktestConfig, TradeState, evaluate_prediction, _check_entry, _check_active_trade)
- `src/bluehorseshoe/analysis/loo_analyzer.py` — LOO's `_backtest_variant()` calls `evaluate_prediction()`
- `src/main.py` — `-t` flag backtest path

---

## Still-Pending Uncommitted Changes (from prior sessions)

### Arcade report (from Feb 17 session)
- `src/bluehorseshoe/reporting/html_reporter.py` — arcade report generator + refinements + percentage display
- `src/main.py` — arcade report wiring (also has -w flag changes from this session)
- `src/bluehorseshoe/api/routes.py` — `/api/v1/arcade/{date}` endpoint
- `BlueHorseshoeBanner.png` — banner image (untracked)

### Other
- `.gitignore` — model and report ignores
- `src/graphs/arcade_dashboard.html` — superseded by generated version
- 20 report HTML files staged for removal from tracking

---

## Prior Work (still relevant)

### Parallelized Prediction Pipeline (strategy.py)
3-phase architecture: I/O preload (ThreadPool, 4 threads) → CPU scoring (ProcessPool, 3 `fork` workers) → collect results. Key: 350-symbol chunks, pool refresh every 3 chunks, `gc.collect()` between chunks. Workers use `SwingTrader.__new__()` to bypass `__init__`.

### Numpy-Optimized Indicators
SuperTrend (~40x), PSAR (major), Aroon (~19.5x), TTM Squeeze (~1.6x), Keltner (~1.6x), Williams %R, CCI, WMA/VWMA all replaced with pure numpy.

### Recent feature commits
- `c86174a` - feat: Attach arcade report to email notifications
- `f79ee6d` - ML-based profit target prediction module
- `5ae0126` - Tiered symbol updates (active-only weekdays, full Saturday)
- `20e9597` - Cron pipeline script and standalone email sender
- `8cf6985` - Replace Celery/Redis with FastAPI BackgroundTasks

---

## Git Status

**Branch:** master
**Latest pushed commit:** `c86174a` - feat: Attach arcade report to email notifications

---

## Production System Status

- **19 indicators** deployed and running
- **Automated daily pipeline:** FastAPI BackgroundTasks + cron (`run_daily_pipeline.sh`)
- **Email notifications:** Brevo on port 2525
- **ML models:** Win probability (XGBoost), stop-loss, profit target (3 joblib files)
- **Tests:** 53/53 passing
- **MongoDB collections:** historical_prices (10,481 symbols), trade_scores (4 dates), symbols (10,443)

---

## Quick Commands

```bash
docker exec bluehorseshoe python src/main.py -p    # Run prediction
docker exec bluehorseshoe python src/main.py -r     # Regenerate reports
docker exec bluehorseshoe python src/main.py -w 2025-08-01 --end 2026-02-07 --interval 7 --top 50 --hold 10  # LOO analysis
docker exec bluehorseshoe pytest src/tests/ -v      # Run tests
docker top bluehorseshoe                            # Check for zombies
cd docker && docker compose up -d                   # Start containers
cd docker && docker compose restart                 # Restart containers
```

---

**Last Updated:** February 18, 2026
**Next Action:** 1) Re-launch LOO run if killed by reboot. 2) Design and implement split-exit backtester (Plan A: 2% fixed, Plan B: ATR-tiered). 3) Commit all pending changes.
