# Session Handoff

**Date:** February 19, 2026 (Wednesday)
**Status:** Split-exit comparison complete. Plan B (ATR-tiered) chosen as default. All changes committed and pushed.

---

## What Was Done This Session

### Split-Exit Comparison — COMPLETE
Ran side-by-side comparison of Single Exit vs Plan A (fixed_pct) vs Plan B (atr_tiered) using saved scores from `trade_scores` collection. Results on two dates (Feb 13 top-30 hold-3, Feb 17 top-20 hold-3):

| Metric | Single Exit | Plan A (2% T1) | Plan B (ATR-tiered) |
|---|---|---|---|
| **Feb 13 Total PnL** | +31.77% | +28.42% | **+36.69%** |
| **Feb 13 Win Rate** | 62.1% | **65.5%** | 58.6% |
| **Feb 17 Total PnL** | +6.43% | +7.78% | **+8.46%** |
| **Feb 17 Win Rate** | 64.3% | 64.3% | 64.3% |

Plan B wins on total PnL consistently. Plan A edges on win rate but caps winners. Max loss identical across all modes.

### Changes Made & Committed (`446273d`)
- **`backtest.py`** — Mark-to-market for incomplete trades (both single-exit and split-exit). Fixes NoneType crash when forward data runs out before hold period expires.
- **`main.py`** — `--split` now defaults to `atr_tiered` when no mode specified. Added `--split` support to LOO analyzer (`-w`) block.
- **`loo_analyzer.py`**, **`strategy.py`**, **`symbols.py`** — `active_only=True` filtering, data preloading, parallelized LOO variants (from prior session, now committed).

---

## Next Steps

1. **Review LOO results** — Check `src/logs/loo_analysis_2026-02-18.csv` and `2026-02-19.csv` for weight adjustment insights. The large LOO run from Feb 18 may have completed or been killed.
2. **Run broader split-exit comparison** — Current comparison only covers 2 dates with limited forward data. Run a range backtest over a longer period once more scored dates accumulate.
3. **Fix 1 pre-existing test failure** — `test_ibkr_client.py::TestIBKRConfig::test_defaults` (port 4004 vs expected 4002). All other 152 tests pass.
4. **Still-uncommitted from prior sessions** — Arcade report (html_reporter.py, routes.py, BlueHorseshoeBanner.png), `.gitignore` updates, report HTML file removals. These were noted in prior handoffs but not yet committed.

---

## Key Decisions

- **Plan B (ATR-tiered) as default split mode** — Outperforms on total PnL while preserving identical downside protection. `--split` without a mode arg now uses `atr_tiered`.
- **Mark-to-market for incomplete trades** — Trades that run out of forward data now close at last available close price instead of returning None. This prevents crashes and gives honest P&L for short data windows.
- **Separate method (`evaluate_prediction_split`)** — Keeps backward compat clean vs mode flag on existing `evaluate_prediction()`.
- **Synthetic `exit_price`** — Split results include a synthetic exit_price so `((exit_price / entry) - 1) * 100 == blended_pnl_pct`, allowing existing P&L calculations to work unchanged.

---

## Prior Work (still relevant)

### Parallelized Prediction Pipeline (strategy.py)
3-phase: I/O preload (ThreadPool) → CPU scoring (ProcessPool, fork) → collect. 350-symbol chunks, pool refresh every 3 chunks.

### Numpy-Optimized Indicators
SuperTrend (~40x), PSAR, Aroon (~19.5x), TTM Squeeze, Keltner, Williams %R, CCI, WMA/VWMA.

### Split-Exit Backtester (Feb 18)
Two-tranche exit strategy. Plan A: T1 at entry+2%, T2 at original TP. Plan B: T1 at 1xATR, T2 at 2xATR. After T1 exits, T2 stop moves to T1 level (breakeven+). 12 dedicated tests in `test_split_exit.py`.

---

## Git Status

**Branch:** master
**Latest pushed commit:** `446273d` - feat: Default split-exit to ATR-tiered (Plan B) and fix incomplete trade handling
**Test results:** 152/153 passing (1 pre-existing IBKR port mismatch), lint clean

---

## Quick Commands

```bash
docker exec bluehorseshoe python src/main.py -p                              # Prediction
docker exec bluehorseshoe python src/main.py -t 2026-01-15 --hold 10 --split # Split backtest (Plan B default)
docker exec bluehorseshoe python src/main.py -t 2026-01-15 --hold 10 --split fixed_pct  # Plan A explicitly
docker exec bluehorseshoe python src/main.py -w 2025-08-01 --end 2026-02-07 --interval 7 --top 50 --hold 10 --split  # LOO with split
docker exec bluehorseshoe pytest -v                                          # All tests
docker exec bluehorseshoe ./lint.sh                                          # Lint
```

---

**Last Updated:** February 19, 2026
