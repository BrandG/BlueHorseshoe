# Session Handoff

**Date:** February 18, 2026 (Tuesday evening)
**Status:** Split-exit backtester implemented and tested. LOO run may still be in progress.

---

## What Was Done This Session

### Split-Exit (Two-Tranche) Backtester — COMPLETE
Implemented a two-tranche exit strategy for backtesting. Two modes:

- **Plan A (`fixed_pct`):** T1 exits at entry+2%, T2 rides to original take_profit
- **Plan B (`atr_tiered`):** T1 exits at entry+1xATR, T2 targets entry+2xATR

In both plans, once T1 exits, T2's stop moves up to T1's exit level (breakeven+).

**Files modified:**
- `src/bluehorseshoe/analysis/backtest.py` — Added `SplitExitConfig`, `SplitTradeState` dataclasses; `evaluate_prediction_split()` and helper methods; updated `_evaluate_candidates`, `run_backtest`, `run_range_backtest`, `_log_results_to_csv`, `_print_summary`, `_summarize_range_results` to pass through `split_config`
- `src/main.py` — Added `--split fixed_pct|atr_tiered`, `--t1-pct`, `--t1-atr`, `--t2-atr` CLI flags in `-t` block
- `src/bluehorseshoe/analysis/loo_analyzer.py` — Updated `_backtest_variant()` and `run()` to accept optional `split_config`; passes ATR from setup_data for Plan B

**New file:**
- `src/tests/test_split_exit.py` — 12 test cases covering both plans, edge cases, backward compat

**Test results:** 12/12 split-exit tests passing. 125/128 total (3 pre-existing failures in `test_moving_average_indicators.py` and `test_volume_indicators.py` unrelated to this change). Lint clean.

**CLI usage:**
```bash
# Plan A
docker exec bluehorseshoe python src/main.py -t 2026-01-15 --hold 10 --split fixed_pct
# Plan B
docker exec bluehorseshoe python src/main.py -t 2026-01-15 --hold 10 --split atr_tiered
# Custom Plan A target (3% instead of 2%)
docker exec bluehorseshoe python src/main.py -t 2026-01-15 --hold 10 --split fixed_pct --t1-pct 0.03
```

---

## In Progress / Background

### Large LOO Run (may still be running or killed)
Started at 15:39 UTC Feb 18. ~21 hrs estimated.
```bash
docker exec bluehorseshoe python src/main.py -w 2025-08-01 --end 2026-02-07 --interval 7 --top 50 --hold 10
```
Check: `tail -20 /tmp/claude-0/-root-BlueHorseshoe/tasks/b092420.output`
Re-launch if killed by reboot.

---

## Next Steps

1. **Commit all pending changes** — LOO analyzer, split-exit backtester, arcade report, and other uncommitted work from prior sessions
2. **Run split-exit comparison** — Run same date range with and without `--split fixed_pct` to compare single-exit vs split-exit performance
3. **Review LOO results** — Once the large LOO run completes, analyze `src/logs/loo_analysis_2026-02-18.csv` and consider weight adjustments
4. **Fix 3 pre-existing test failures** — `test_calculate_wma`, `test_calculate_vwma`, `test_calculate_score` (volume indicators)

---

## Key Decisions

- **Separate method (`evaluate_prediction_split`) rather than mode flag** on existing `evaluate_prediction()` — keeps backward compat clean, no risk of breaking existing callers
- **Synthetic `exit_price`** — the split result includes a synthetic exit_price computed so `((exit_price / entry) - 1) * 100 == blended_pnl_pct`, allowing existing P&L calculations in callers to work without changes
- **T2 stop moves to T1 level** after T1 exits — this is the "breakeven+" philosophy (playing with house money)

---

## Still-Pending Uncommitted Changes

### From this session
- Split-exit backtester (backtest.py, main.py, loo_analyzer.py, test_split_exit.py)

### From earlier today
- LOO analyzer system (loo_analyzer.py, loo_report.py, detailed_scoring.py, test_loo_analyzer.py)
- `src/main.py` — `-w` CLI flag

### From Feb 17 session
- Arcade report (html_reporter.py, main.py, routes.py, BlueHorseshoeBanner.png)
- `.gitignore` updates
- 20 report HTML files staged for removal

---

## Prior Work (still relevant)

### Parallelized Prediction Pipeline (strategy.py)
3-phase: I/O preload (ThreadPool) → CPU scoring (ProcessPool, fork) → collect. 350-symbol chunks, pool refresh every 3 chunks.

### Numpy-Optimized Indicators
SuperTrend (~40x), PSAR, Aroon (~19.5x), TTM Squeeze, Keltner, Williams %R, CCI, WMA/VWMA.

---

## Git Status

**Branch:** master
**Latest pushed commit:** `8da32c4` - feat: Add LOO (Leave-One-Out) weight analysis
**Uncommitted:** split-exit backtester, arcade report, various improvements

---

## Quick Commands

```bash
docker exec bluehorseshoe python src/main.py -p                    # Prediction
docker exec bluehorseshoe python src/main.py -t 2026-01-15 --hold 10 --split fixed_pct  # Split backtest
docker exec bluehorseshoe python src/main.py -w 2025-08-01 --end 2026-02-07 --interval 7 --top 50 --hold 10  # LOO
docker exec bluehorseshoe pytest -v                                # All tests
docker exec bluehorseshoe ./lint.sh                                # Lint
```

---

**Last Updated:** February 18, 2026
