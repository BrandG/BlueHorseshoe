# Session Handoff

**Date:** February 20, 2026 (Thursday)
**Status:** RR ratio fix implemented + infrastructure hardening. Needs reboot then clean prediction run.

---

## What Was Done This Session

### RR Ratio Fix (strategy.py + constants.py)

**Problem:** Prediction pipeline produced candidates with dangerously low RR ratios (e.g., 0.2x — risking 7.1% for only 1.11% reward). Two root causes:
1. **Resistance cap crushed reward targets** — `resistance_cap = swing_high_20 * 0.98` capped take-profit at 2% below the 20-day high. For stocks in tight ranges, this sits just above entry.
2. **MIN_RR_RATIO filter was missing from the production pipeline** — existed in `loo_analyzer.py` but never added to `strategy.py`.

**Changes made:**

1. **Replaced resistance cap with delta-based haircut** in both `calculate_baseline_setup()` and `calculate_mean_reversion_setup()`:
   - Before: `take_profit = min(atr_target, swing_high_20 * 0.98)` (caps absolute price)
   - After: `take_profit = entry_price + (atr_target - entry_price) * 0.98` (2% haircut on reward delta only)
   - Removed: `swing_high_20`, `resistance_cap`, `ema20`, `partial_reversion`, `recent_high_20` variables
   - Removed: floor check (`if take_profit <= entry_price`) — unreachable with new formula

2. **Added MIN_RR_RATIO filter** in 4 locations:
   - `_process_baseline()` (class method — CLI single-threaded path)
   - `_process_mr()` (class method)
   - `_worker_process_baseline()` (standalone function — **ProcessPoolExecutor production path**)
   - `_worker_process_mr()` (standalone function — **ProcessPoolExecutor production path**)
   - **IMPORTANT:** The worker functions are separate from the class methods. The first prediction run missed the worker functions, resulting in unfiltered results.

3. **Lowered RR thresholds** in `constants.py`:
   - `MIN_RR_RATIO_BASELINE`: 1.0 → **0.5** (1.0 filtered 99.5% of candidates because stop_mult=2.0 requires target_mult > 2.04 for RR > 1.0)
   - `MIN_RR_RATIO_MEAN_REVERSION`: 0.8 → **0.5**

**Verification:**
- 197/197 tests pass
- Lint clean
- First prediction run (delta-based haircut only, no worker filters): completed, report sent. RR ratios improved from 0.2x to 0.4-0.7x range.
- Second prediction run (with all filters at threshold 1.0): killed at 87% — confirmed 99.5% of baseline candidates filtered (too aggressive)
- Third prediction run (threshold 0.5): healthy distribution (17% zeroes vs 99.5%), killed at 52.8% by OOM
- **Still needs a clean full prediction run** to generate a report with the complete fix.

### Infrastructure Hardening (Thread 2 — crash recovery & resource limits)

**Context:** System crashed overnight — LOO + split-exit comparison saturated CPU/memory, then the daily cron pipeline pushed it over. MongoDB and Python processes were OOM-killed.

**Bug fixes:**
- **`logger` → `logging` in strategy.py:1134** — Sentiment refresh after scoring used undefined `logger` variable, crashing the prediction before report generation. Changed to `logging.info()`/`logging.warning()` to match rest of file.
- **`find_report()` excluded `_email` but not `_arcade`** in `send_report_email.py` — Was picking the 1.5MB arcade report as the "main" report, causing email body to use wrong file and `_email.html` lookup to fail. Added `_arcade` exclusion.
- **SMTP timeout 30s → 120s** in `email_service.py` — 30s was too tight when sending arcade attachment.

**Resource management changes:**
- **`BacktestOptions.max_workers`** (backtest.py) — New optional field to cap ThreadPoolExecutor in `_generate_predictions`. `None` = auto (existing behavior).
- **`--workers N` flag** added to `compare_split_exit.py` (default: 1) and `main.py -t` backtest.
- **Chunked `_generate_predictions`** (backtest.py) — Was submitting all 6,425 symbols at once to ThreadPool. Now processes 500 symbols per chunk with `gc.collect()` between chunks, matching the prediction pipeline's pattern.
- **MongoDB WiredTiger cache capped at 1GB** (docker-compose.yml) — Default was ~3.5GB (50% of 8GB RAM), leaving too little for Python.
- **Docker resource limits** (docker-compose.yml) — `cpus: 1.5`, `mem_limit: 4g` on bluehorseshoe container. **Note:** 4GB may be too low for full 6,425-symbol scoring; may need tuning up after reboot.
- **`run_split_comparison.sh`** — Runner script that processes each date individually (not all 10 at once), stopping on failure and writing per-date CSVs + combined log.

**Daily pipeline completed (pre-RR-fix):**
- Data update: 10,442 symbols through Feb 19
- Prediction: 3,615 candidates from 6,261 valid symbols
- Reports generated (all 3 formats) and email sent successfully
- Pipeline status tracker updated (`pipeline_status.json`)

### Memory Issues
- Multiple prediction runs consumed memory/swap. System hit OOM limits repeatedly (exit code 137).
- Even with MongoDB cache capped + chunked predictions + 1 worker, the backtester still OOM'd on 8GB RAM with full symbol set.
- Swap was flushed (`swapoff -a && swapon -a`) and containers fully recreated, but still hitting limits.
- **Recommendation:** Reboot the system before running prediction to start clean.

---

## Uncommitted Changes (Ready to Commit After Verification)

**Files modified:**
- `src/bluehorseshoe/analysis/strategy.py` — delta-based haircut + RR filters in 4 locations
- `src/bluehorseshoe/analysis/constants.py` — MIN_RR_RATIO thresholds lowered to 0.5

**Files modified (infrastructure — Thread 2):**
- `src/bluehorseshoe/analysis/strategy.py` — also: `logger` → `logging` fix at sentiment refresh
- `src/bluehorseshoe/analysis/backtest.py` — `BacktestOptions.max_workers` + chunked `_generate_predictions`
- `src/compare_split_exit.py` — `--workers` flag (default: 1)
- `src/main.py` — `--workers` flag for `-t` backtest
- `src/bluehorseshoe/core/email_service.py` — SMTP timeout 30s → 120s
- `src/send_report_email.py` — `find_report()` excludes `_arcade` variants
- `docker/docker-compose.yml` — MongoDB `wiredTigerCacheSizeGB: 1`, bluehorseshoe `cpus: 1.5` + `mem_limit: 4g`
- `run_split_comparison.sh` — new sequential runner script

---

## Next Steps (in order)

1. **Reboot system** — Clear accumulated memory pressure.

2. **Run prediction to verify RR fix:**
   ```bash
   docker exec bluehorseshoe python src/main.py -p
   ```
   Check report: baseline RR ratios should be >= 0.5, no more 0.2x candidates.

3. **Send report:**
   ```bash
   docker exec bluehorseshoe python src/send_report_email.py
   ```

4. **Commit changes** — After verifying the report looks good.

5. **Run split-exit comparison (one date at a time):**
   ```bash
   bash run_split_comparison.sh   # Runs 10 dates sequentially, --workers 1
   ```
   Or individual dates: `docker exec bluehorseshoe python src/compare_split_exit.py 2025-10-01 --hold 10 --top 20 --workers 1`

6. **Re-run broad LOO analysis:**
   ```bash
   docker exec bluehorseshoe python src/main.py -w 2025-08-01 --end 2026-02-07 --interval 7 --top 50 --hold 10 --split
   ```

---

## Key Technical Details

### Why threshold 1.0 was too aggressive
With `ml_stop_multiplier = 2.0` (fixed) and the 0.98 delta haircut, the RR formula simplifies to:
```
rr ≈ (ml_target_multiplier * 0.98) / ml_stop_multiplier
   = ml_target_multiplier * 0.98 / 2.0
```
For RR >= 1.0, you need `ml_target_multiplier >= 2.04`. Most ML predictions are 1.0-2.0, so nearly everything was filtered.

### Worker functions vs class methods
The ProcessPoolExecutor uses standalone functions (`_worker_process_baseline`, `_worker_process_mr`) that replicate the class methods (`_process_baseline`, `_process_mr`) without DB access. Any filter changes must be applied to **both** sets of functions.

---

## Prior Work (still relevant)

### Parallelized Prediction Pipeline (strategy.py)
3-phase: I/O preload (ThreadPool) → CPU scoring (ProcessPool, fork) → collect. 350-symbol chunks, pool refresh every 3 chunks.

### Split-Exit Backtester (Feb 18)
Two-tranche exit strategy. Plan B (ATR-tiered) as default. 12 dedicated tests.

### LOO Analyzer (Feb 19)
Leave-one-out analysis for indicator weight tuning. Sequential scoring, deparallelized I/O preload.

---

## Git Status

**Branch:** master
**Latest pushed commit:** `19c7b5d` - feat: Add sentiment advisory column to all report formats
**Uncommitted changes:** RR ratio fix + infrastructure hardening (see Uncommitted Changes section above)
**Test results:** 197/197 passing

---

## Quick Commands

```bash
docker exec bluehorseshoe python src/main.py -p                              # Prediction
docker exec bluehorseshoe python src/send_report_email.py                    # Send report
docker exec bluehorseshoe python src/main.py -t 2026-01-15 --hold 10 --split --workers 2  # Throttled backtest
bash run_split_comparison.sh                                                   # Split comparison (sequential, --workers 1)
docker exec bluehorseshoe pytest -v                                          # All tests
docker exec bluehorseshoe ./lint.sh                                          # Lint
```

---

**Last Updated:** February 20, 2026
