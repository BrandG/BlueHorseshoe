# Session Handoff

**Date:** March 8, 2026
**Status:** MongoDB OHLCV fully removed. DuckDB is the sole OHLCV store with thread-safe access. Full pipeline verified.

---

## What Was Done This Session (March 8)

### MongoDB OHLCV Removal
- Removed all MongoDB dual-write code for OHLCV (`historical_prices`, `historical_prices_recent`)
- Deleted `load_historical_data_from_mongo()`, renamed `save_historical_data_to_mongo()` → `save_historical_data()` (DuckDB-only)
- Removed MongoDB read fallbacks from `strategy.py`, `backtest.py`, `service.py`
- Renamed `upsert_historical_to_mongo()` → `upsert_historical()`, `get_historical_from_mongo()` → `get_historical()` in `symbols.py`
- Updated all callers: `api.py`, `batch_loader.py`, `maintenance.py`, `dependencies.py`, `routes.py`, `tasks.py`
- Updated tests and standalone scripts
- MongoDB remains in use for non-OHLCV collections (scores, journal, overviews, checkpoints, symbols)

### DuckDB Thread-Safety Fix
- `-u` update hung at 86% after dual-write removal — root cause: `ThreadPoolExecutor` workers concurrently accessing `self._con` (not thread-safe)
- Added `threading.RLock()` to `DuckDBStore`, wrapped all `self._con.execute()` calls with `with self._lock:`
- Used `RLock` (reentrant) because `load_symbol_dict()` calls `load_symbol()` + `get_metadata()` — regular `Lock` would deadlock
- Fixed `close()` to use `getattr()` for safe cleanup when `__init__` fails partway

### Verified
- `-u` update: 3,590 symbols in 203 seconds, 0 failures
- `-p` prediction: 5,414 symbols in 79 minutes, reports generated successfully
- 339 tests passing, lint clean

### TO-DO Updates
- Added infrastructure items: research droplet DuckDB access, DuckDB periodic backups, non-git file backup strategy

---

## Previous Sessions Summary

- **March 7 (Session 2):** DuckDB migration complete — all 4 phases, schema optimization (4.0 GB → 484 MB)
- **March 7 (Session 1):** Market-cap universe (~3,591 symbols), multi-provider pool (Tiingo/AV/Yahoo), volume gates removed
- **March 6:** Vectorized backtesting — 13x speedup single-date, 7.4x range
- **March 5:** Score-once backtest refactor — 22 min → 2-3 sec; connors_flag BSON fix
- **March 4:** Regime-adaptive weight selection tested and rejected; research droplet destroyed
- **March 3:** V3 weights deployed to production

---

## Next Steps

- **Backfill overviews** — ~2,000 symbols still missing overviews. Run `-u --refresh-overviews --ov-limit 500` in batches.
- **Full historical backfill** — Many of the 3,500 newly-tracked symbols only have ~6 months of data
- **DuckDB backup strategy** — No backup exists for `data/ohlcv.duckdb` (484 MB). Add periodic snapshots.
- **Strategy as pluggable interface** — Refactor Baseline/MR behind `Strategy(ABC)` so adding shorts is trivial
- **Event-driven backtest** — Model trades as orders fed through daily bars (handles split exits, trailing stops, shorts as order types)
- See `TO-DO.md` for full backlog

---

## Key Decisions

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
| `src/bluehorseshoe/analysis/strategy.py` | `store` wired through prediction pipeline |
| `src/bluehorseshoe/analysis/backtest.py` | `store` wired through backtester |
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
docker exec bluehorseshoe pytest -v                                      # Tests (339 passing)
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
**Latest commit:** `4f095e4` — fix: Add thread-safety locks to DuckDBStore and update TO-DO

---

**Last Updated:** March 8, 2026
