# Session Handoff - Indicator Numpy Optimizations

**Date:** February 17, 2026 (Monday)
**Status:** All tests passing, three indicator optimization commits pushed

---

## What Was Done This Session

### Replaced ta library Williams %R and CCI with numpy (momentum_indicators.py)

- **Williams %R:** Replaced `WilliamsRIndicator` with 4-line numpy calc (slice last 14 bars, `high.max()`/`low.min()`, formula). Added `highest_high == lowest_low` guard.
- **CCI:** Replaced `CCIIndicator` with numpy Typical Price calc (slice last `window` bars, mean deviation, formula). Added `mean_dev == 0` guard.
- Removed `from ta.momentum import WilliamsRIndicator` and `from ta.trend import CCIIndicator`
- **Commit:** `1073405`

### Replaced rolling WMA/VWMA with single-value numpy (moving_average_indicators.py)

- **WMA:** Replaced `rolling(20).apply(wma_function)` with `np.dot(close[-20:], weights) / weights.sum()` — single dot product instead of rolling apply over entire series.
- **VWMA:** Replaced `rolling(20).sum()` pair with direct numpy sum on last 20 bars.
- Both methods now return `float` instead of `pd.Series` (only last value was ever used). `calculate_ma_score()` simplified accordingly.
- Added `window` parameter, insufficient-data guards, zero-volume guard.
- **Commit:** `1faa7cf`

### Strategy ATR cleanup (strategy.py)

- `_calculate_atr()`: Changed `df.iloc[-1]['ATR']` → `df['ATR'].values[-1]` and `df.iloc[-1]['close']` → `df['close'].values[-1]`
- `calculate_mean_reversion_setup()`: Replaced duplicated 8-line ATR block with `self._calculate_atr(df)` call
- **Commit:** `ab12537`

---

## Prior Session Work (still relevant)

### Parallelized Prediction Pipeline (strategy.py)

3-phase architecture with true CPU parallelism:

**Phase 1 (I/O):** `ThreadPoolExecutor` (4 threads) pre-loads symbol data from MongoDB
**Phase 2 (CPU):** `ProcessPoolExecutor` (3 workers, `fork` context) scores symbols in parallel
**Phase 3:** Main process collects results

**Key design decisions:**
- **`fork` context** (not `spawn`) -- copy-on-write memory sharing, critical on 7.8GB host
- **350-symbol chunks** -- limits peak memory during preload
- **Pool refresh every 3 chunks** -- prevents worker memory accumulation (`max_tasks_per_child` incompatible with `fork`)
- **`gc.collect()` between chunks** -- reclaims freed memory
- Workers use `SwingTrader.__new__()` to bypass `__init__` (no DB connections)
- ML models loaded once per worker via `initializer` parameter
- Shared context (benchmark data, market health) passed via initializer

### Numpy-Optimized Indicators (trend_indicators.py)

| Indicator | Change | Speedup |
|-----------|--------|---------|
| SuperTrend | Replaced `AverageTrueRange` + `.iloc[]` with numpy arrays, `np.int8` trend | ~40x |
| PSAR | Complete rewrite from scratch, pure numpy (removed `PSARIndicator`) | Major |
| Aroon | `sliding_window_view` + vectorized `np.argmax`/`np.argmin` (removed `AroonIndicator`) | ~19.5x |
| TTM Squeeze | `sliding_window_view` for BB, `ewm().mean()` for KC (removed `BollingerBands`, `KeltnerChannel`) | ~1.6x |
| Keltner | Manual EMA + numpy True Range (removed `KeltnerChannel`) | ~1.6x |

**Remaining `ta` imports:** `DonchianChannel` (volatility) and `AverageTrueRange` (used in strategy.py `_calculate_atr`). Neither is a bottleneck.

---

## OOM Debugging History (for future reference)

Multiple OOM kills (exit code 137) on 7.8GB host before finding working config:

1. **Pre-loading all 10k symbols at once** -- OOM. Fix: chunked processing
2. **`spawn` context with 4 workers** -- OOM (each spawns fresh Python interpreter). Fix: reduce to 2
3. **`spawn` context with 2 workers** -- still OOM at chunk 2. Fix: switch to `fork`
4. **`fork` with persistent pool** -- OOM at chunk 4 (worker memory accumulation). Fix: pool refresh every 3 chunks
5. **`fork` + `max_tasks_per_child`** -- incompatible error. Fix: manual pool recreation

**Root cause of early failures:** Zombie processes from previous runs were consuming ~3GB, leaving insufficient memory for new runs. Always check `docker top bluehorseshoe` before running predictions.

---

## Git Status

**Branch:** master
**Latest commit:** `ab12537` - perf: Use numpy ATR access and deduplicate mean reversion ATR calc

**Recent commits:**
- `ab12537` - perf: Use numpy ATR access and deduplicate mean reversion ATR calc
- `1faa7cf` - perf: Replace rolling WMA/VWMA with single-value numpy calculations
- `1073405` - perf: Replace ta library Williams %R and CCI with numpy calculations
- `91c49d6` - perf: Increase CPU workers to 3 with smaller chunk size for ~22% speedup
- `d2c98e5` - fix: Update dynamic entry tests to match current signal strength thresholds

---

## Production System Status

- **19 indicators** deployed and running
- **Automated daily pipeline:** FastAPI BackgroundTasks (triggered via API)
- **Email notifications:** Brevo on port 2525 to brandg@gmail.com
- **Reports:** `src/logs/report_YYYY-MM-DD.html` + email-friendly version
- **Tests:** 53/53 passing

---

## Quick Commands

```bash
# Run prediction
docker exec bluehorseshoe python src/main.py -p

# Run tests
docker exec bluehorseshoe pytest src/tests/ -v

# Check for zombie processes before running
docker top bluehorseshoe

# Kill stale processes (use HOST PIDs from docker top)
sudo kill -9 <PID>

# Container management
cd docker && docker compose up -d
cd docker && docker compose restart
```

---

## Open Tasks

1. **Monitor parallel pipeline** -- observe 3-worker config over several daily runs for memory stability
2. **Confirmation indicator testing** -- see `FUTURE_TESTING_CONFIRMATION_INDICATORS.md`
3. **Score normalization** -- currently raw sums (range ~-40 to +60), bell curve to 0-20 discussed but not prioritized

---

**Last Updated:** February 17, 2026
**Next Action:** Monitor daily pipeline stability; consider further numpy optimizations if bottlenecks remain
