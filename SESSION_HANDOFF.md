# Session Handoff

**Date:** March 7, 2026
**Status:** DuckDB migration complete. OHLCV storage moved from MongoDB to DuckDB. File optimized from 4.0 GB to 484 MB.

---

## What Was Done This Session (March 7, Session 2)

### DuckDB Migration — All 4 Phases Complete

1. **Phase 1: Foundation**
   - Added `duckdb>=1.2.0` to `docker/requirements.txt`
   - Created `src/bluehorseshoe/data/duckdb_store.py` — `DuckDBStore` class with save/load/bulk/snapshot methods
   - Added `duckdb_path` to `config.py` Settings, `get_historical_store()` to `container.py`, `store` property to `context.py`
   - Created `src/tests/test_duckdb_store.py` (23 tests)

2. **Phase 2: Migration + dual-write**
   - Created `src/migrate_to_duckdb.py` — migrated 11,291 symbols, 28.5M rows
   - Added `store=None` param to `save_historical_data_to_mongo()`, `process_symbol()`, `build_all_symbols_history()`, `load_historical_data()`
   - DuckDB dual-write wired through `-u` and `-b` handlers in `main.py`

3. **Phase 3: Switch reads to DuckDB**
   - `SwingTrader.__init__()` — accepts `store`, passes through to all data loads
   - `strategy.py` — `_preload_symbol_data()`, `_load_benchmark_data()`, `_get_previous_trading_date()`, `get_previous_performance()` all use DuckDB when available
   - `backtest.py` — `Backtester` and `_bulk_load_price_data()` use `store.load_symbols_bulk()`
   - `service.py` — `load_universe_data()` and `get_latest_market_date()` use DuckDB
   - `main.py` — passes `ctx.store` to all consumers

4. **Phase 4: Cleanup**
   - Removed MongoDB from `load_historical_data()` read chain (now: DuckDB → file → net)
   - Updated standalone scripts (`build_test_dates.py`, `compare_v2_v3.py`, `compare_backtest.py`, `analyze_indicator_impact.py`)
   - Added DuckDB dual-write to `upsert_historical_to_mongo()` in `symbols.py`

5. **Schema optimization (this context window)**
   - Slimmed to OHLCV-only (7 columns, dropped 25 redundant indicator columns)
   - Removed primary key index — ART index cost 1.66 GB (3x the data), zone maps are faster for our query patterns
   - **Final file size: 484 MB** (down from 4.0 GB original — 88% reduction)

### Verified
- Dual-write: ran `-u --symbols SPY,QQQ`, confirmed rows increased and latest date updated
- DuckDB reads: ran `-p --symbols SPY,QQQ,AAPL`, confirmed log output "Loaded SPY from DuckDB (6626 days)"
- Data parity: 20/20 random symbol spot-checks match MongoDB
- Benchmarks: no-index is faster (single load 18ms→13ms, bulk50 579ms→134ms)
- All 340 tests passing, lint passing

---

## Previous Sessions Summary

- **March 7 (Session 1):** Market-cap universe (~3,591 symbols), multi-provider pool (Tiingo/AV/Yahoo), volume gates removed
- **March 6:** Vectorized backtesting — 13x speedup single-date, 7.4x range
- **March 5:** Score-once backtest refactor — 22 min → 2-3 sec; connors_flag BSON fix
- **March 4:** Regime-adaptive weight selection tested and rejected; research droplet destroyed
- **March 3:** V3 weights deployed to production

---

## Next Steps

- **Run full prediction pipeline** to measure end-to-end timing improvement with DuckDB (previously ~51 min for 5.3k symbols — Phase 1 preload should be much faster)
- **Consider dropping MongoDB OHLCV collections** (`historical_prices`, `historical_prices_recent`) — DuckDB is now the sole read source; MongoDB still receives dual-writes as a safety net. Dropping would free significant MongoDB storage.
- **Backfill overviews for remaining symbols** — ~2,000 NASDAQ/NYSE symbols still missing overviews. Run `-u --refresh-overviews --ov-limit 500` in batches.
- **Full historical backfill** — Many of the 3,500 newly-tracked symbols only have ~6 months of data
- See `TO-DO.md` for full backlog

---

## Key Decisions

- **No primary key index** — DuckDB's ART index for PK on 28M rows cost 1.66 GB (77% of file). Dropped it. Zone maps handle our `WHERE symbol = ?` queries efficiently; uniqueness enforced by DELETE-before-INSERT in `save_symbol()`. Benchmarks confirmed faster without it.
- **OHLCV-only storage** — 25 indicator columns (RSI, MACD, ADX, etc.) dropped from DuckDB. They're always recomputed from raw OHLCV by `get_technical_indicators()` during every ingestion.
- **MongoDB dual-write retained** — Both write paths still active as a safety net. Can be removed once confidence is established.
- **$300M market cap floor** — ~3,591 symbols. Configurable via `MIN_MARKET_CAP` constant.
- **V3 weights remain production** — No changes to scoring weights

---

## Key Files (DuckDB Migration)

| File | Role |
|------|------|
| `src/bluehorseshoe/data/duckdb_store.py` | DuckDB storage backend |
| `src/bluehorseshoe/data/historical_data.py` | Write path (dual-write), read path (DuckDB-first) |
| `src/bluehorseshoe/core/container.py` | `get_historical_store()` |
| `src/bluehorseshoe/core/config.py` | `duckdb_path` setting |
| `src/bluehorseshoe/analysis/strategy.py` | `store` wired through prediction pipeline |
| `src/bluehorseshoe/analysis/backtest.py` | `store` wired through backtester |
| `src/bluehorseshoe/core/service.py` | `load_universe_data()`, `get_latest_market_date()` |
| `src/main.py` | Passes `ctx.store` to all consumers |
| `src/migrate_to_duckdb.py` | One-time migration script |
| `src/tests/test_duckdb_store.py` | 23 unit tests |
| `data/ohlcv.duckdb` | The database file (484 MB, 28.5M rows, 11,291 symbols) |

---

## Infrastructure

### Research Droplet
- **Status:** DESTROYED (March 4, 2026)
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
docker exec bluehorseshoe python src/main.py -p                          # Prediction
docker exec bluehorseshoe python src/main.py -u                          # Data update (active-only)
docker exec bluehorseshoe python src/main.py -u --all                    # Data update (all 11k symbols)
docker exec bluehorseshoe python src/main.py -u --refresh-overviews      # Update + backfill missing overviews
docker exec bluehorseshoe pytest -v                                      # Tests (340 passing)
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
**Latest pushed commit:** `a50a09f` — docs: Update TO-DO with multi-provider pool and market-cap universe completion
**Unpushed:** All DuckDB migration work (Phases 1-4 + schema optimization)

---

**Last Updated:** March 7, 2026
