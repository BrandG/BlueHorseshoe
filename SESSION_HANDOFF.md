# Session Handoff

**Date:** March 9, 2026
**Status:** Pluggable strategy interface complete. All strategies (Baseline, MR) are self-contained classes behind `TradingStrategy` ABC. Adding a third strategy requires zero downstream changes.

---

## What Was Done This Session (March 9)

### Pluggable Strategy Interface (8-Phase Refactor)
Replaced 40+ `if strategy == "baseline"` branches across 7 files with a generic strategy loop pattern.

**New files:**
- `strategy_interface.py` — `TradingStrategy` ABC, `StrategyResult` dataclass, `BaselineStrategy`, `MeanReversionStrategy` (stateless, picklable for ProcessPoolExecutor)
- `strategy_registry.py` — `get_strategy()`, `get_all_strategies()`, `get_strategy_keys()` central registry

**Migrated consumers:**
- `backtest.py` — 13 ternary branches → `get_strategy_keys()` calls
- `technical_analyzer.py` — added `calculate_score_for_strategy()`, old `calculate_technical_score()` delegates via registry
- `html_reporter.py` — strategy filtering uses `get_all_strategies()` loop
- `journal.py` — `_build_signal_docs()` single loop over strategies (was two duplicate loops)
- `strategy.py` — `SwingTrader` accepts `strategies` param; `process_symbol()`, `_score_symbol_worker()`, `_prepare_scores_for_save()`, `swing_predict()` all use generic strategy loops

**Removed deprecated code:**
- `_process_baseline()`, `_process_mr()` from `SwingTrader`
- `_worker_process_baseline()`, `_worker_process_mr()` module-level functions

**Test updates:**
- 4 new test files/updates (37 new tests)
- Updated mocks in `test_connors_section.py`, `test_swing_trading.py`, `test_strategy_bearish.py` to use `StrategyResult`/strategy objects
- 408 tests passing, lint clean

### Verified
- All 408 tests passing
- Lint clean
- Result dict shape unchanged — backward compatible with MongoDB schema and all downstream consumers

---

## Previous Sessions Summary

- **March 8:** MongoDB OHLCV dual-write removed, DuckDB thread-safety fix (RLock), new indicators (RVOL, Engulfing, Hammer)
- **March 7 (Session 2):** DuckDB migration complete — all 4 phases, schema optimization (4.0 GB → 484 MB)
- **March 7 (Session 1):** Market-cap universe (~3,591 symbols), multi-provider pool (Tiingo/AV/Yahoo), volume gates removed
- **March 6:** Vectorized backtesting — 13x speedup single-date, 7.4x range
- **March 5:** Score-once backtest refactor — 22 min → 2-3 sec; connors_flag BSON fix
- **March 4:** Regime-adaptive weight selection tested and rejected; research droplet destroyed
- **March 3:** V3 weights deployed to production

---

## Next Steps

- **Add a third strategy (e.g. Shorts)** — Now trivial: subclass `TradingStrategy`, register in `strategy_registry.py`, done
- **Event-driven backtest** — Model trades as orders fed through daily bars (handles split exits, trailing stops, shorts as order types)
- **Backfill overviews** — ~2,000 symbols still missing overviews. Run `-u --refresh-overviews --ov-limit 500` in batches.
- **Full historical backfill** — Many of the 3,500 newly-tracked symbols only have ~6 months of data
- **DuckDB backup strategy** — No backup exists for `data/ohlcv.duckdb` (484 MB). Add periodic snapshots.
- See `TO-DO.md` for full backlog

---

## Key Decisions

- **Strategy objects are stateless and picklable** — They receive `trader` as a parameter to `process()`, not stored state. Critical for `ProcessPoolExecutor` workers.
- **Result dict shape preserved** — `process_symbol()` still returns `{baseline_score, mr_score, ...}` — all downstream code sees no change.
- **MongoDB schema unchanged** — `strategy` field stores `"baseline"` or `"mean_reversion"` — the strategy's `.name` property returns these exact strings.
- **Connors stays as a flag, not a strategy** — Piggybacks on setup data from other strategies. Can become a third strategy later.
- **`calculate_technical_score()` kept as backward-compat wrapper** — Widely used (tests, scripts, `historical_data.py`). Internally delegates via registry.
- **No primary key index** — DuckDB's ART index for PK on 28M rows cost 1.66 GB (77% of file). Dropped it. Zone maps handle our `WHERE symbol = ?` queries efficiently; uniqueness enforced by DELETE-before-INSERT in `save_symbol()`.
- **OHLCV-only storage** — 25 indicator columns dropped from DuckDB. Always recomputed from raw OHLCV.
- **MongoDB OHLCV dual-write removed** — DuckDB is the sole OHLCV store. MongoDB retains scores, journal, overviews, checkpoints, symbols.
- **RLock for DuckDB thread safety** — All connection access serialized. Reentrant lock avoids deadlocks from nested method calls.
- **$300M market cap floor** — ~3,591 symbols. Configurable via `MIN_MARKET_CAP` constant.
- **V3 weights remain production** — No changes to scoring weights

---

## Key Files

| File | Role |
|------|------|
| `src/bluehorseshoe/data/duckdb_store.py` | DuckDB storage backend (thread-safe via RLock) |
| `src/bluehorseshoe/data/historical_data.py` | Write path (DuckDB-only), read path (DuckDB → file → net) |
| `src/bluehorseshoe/core/container.py` | `get_historical_store()` |
| `src/bluehorseshoe/core/config.py` | `duckdb_path` setting |
| `src/bluehorseshoe/analysis/strategy_interface.py` | `TradingStrategy` ABC, `BaselineStrategy`, `MeanReversionStrategy` |
| `src/bluehorseshoe/analysis/strategy_registry.py` | `get_strategy()`, `get_all_strategies()`, `get_strategy_keys()` |
| `src/bluehorseshoe/analysis/strategy.py` | `SwingTrader` — uses strategy loop via `self.strategies` |
| `src/bluehorseshoe/analysis/backtest.py` | Uses `get_strategy_keys()` for all key resolution |
| `src/bluehorseshoe/core/service.py` | `load_universe_data()`, `get_latest_market_date()` |
| `src/main.py` | Passes `ctx.store` to all consumers |
| `data/ohlcv.duckdb` | The database file (484 MB, 28.5M rows, 11,291 symbols) |

---

## Pipeline Timing (March 8)

| Pipeline | Symbols | Time |
|----------|---------|------|
| `-u` (data update) | 3,590 | 3 min 23 sec |
| `-p` (prediction) | 5,414 | 79 min |

---

## Infrastructure

### Research Droplet
- **Status:** DESTROYED (March 4, 2026)
- **Note:** When re-creating, must SCP `data/ohlcv.duckdb` to the droplet — DuckDB is now the sole OHLCV store (no MongoDB fallback)
*************** DO NOT EDIT THE FOLLOWING SECTION WHEN UPDATING SESSION_HANDOFF.md
**IMPORTANT:** All SSH commands to the research droplet MUST `cd /root/BlueHorseshoe` first.
The default login directory is `/root`, NOT the repo directory.

**Workaround for Claude Code:** Write remote commands to `/tmp/remote_cmd.sh` and pipe via `ssh root@10.132.0.4 bash < /tmp/remote_cmd.sh` — this reliably includes the `cd`.

```bash
ssh root@10.132.0.4
# All commands must run from /root/BlueHorseshoe
# Direct SSH (for humans):
ssh root@10.132.0.4 "cd /root/BlueHorseshoe && docker exec bh-research python src/run_clean_backtest.py --version v3"
# Copy results:
scp root@10.132.0.4:/root/BlueHorseshoe/src/logs/clean_backtest_v3.csv src/logs/
# Destroy when done:
doctl compute droplet delete bh-research --force
```
*************** END OF IMMUTABLE SECTION

### Production
```bash
docker exec bluehorseshoe python src/main.py -p                          # Prediction (~79 min)
docker exec bluehorseshoe python src/main.py -u                          # Data update (~3.5 min)
docker exec bluehorseshoe python src/main.py -u --all                    # Data update (all 11k symbols)
docker exec bluehorseshoe python src/main.py -u --refresh-overviews      # Update + backfill missing overviews
docker exec bluehorseshoe pytest -v                                      # Tests (408 passing)
docker exec bluehorseshoe ./lint.sh                                      # Lint
```

**Cron pipeline:** Runs at 02:00 UTC (Mon-Sat)

---

## Weight Optimization — COMPLETE

**V2 (original hand-tuned):** `src/weights_v2.json` — reference only
**V2-full (V2 baseline + prod MR):** `src/weights_v2_full.json` — research only
**V3 (data-driven, DEPLOYED):** `src/weights_v3.json` — also in `src/weights.json`

---

## Git Status

**Branch:** master
**Latest commit:** `e26d5be` — feat: Add Engulfing, Hammer candlestick patterns and RVOL volume indicator
**Uncommitted:** Pluggable strategy interface refactor (8 phases)

---

**Last Updated:** March 9, 2026
