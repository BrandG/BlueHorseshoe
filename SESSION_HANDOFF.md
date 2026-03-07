# Session Handoff

**Date:** March 7, 2026
**Status:** Market-cap universe and multi-provider pool shipped. Full 3.5k symbol pipeline verified end-to-end.

---

## What Was Done This Session (March 7)

1. **Market-cap-based symbol universe** (`72ee1a7`)
   - Rewrote `get_active_symbol_list()` to query `symbol_overviews` for MarketCapitalization >= $300M
   - Active universe expanded from **~156 to ~3,591 symbols** (pseudo Russell 3000)
   - Added `MIN_MARKET_CAP = 300_000_000` constant to `constants.py`
   - Added `backfill_overviews()` to `symbols.py` for fetching missing AV OVERVIEW data
   - Added `--refresh-overviews` / `--ov-limit N` flags to `-u` handler in `main.py`

2. **Removed volume gates from scoring**
   - Removed `avg_volume_20 < MIN_VOLUME_THRESHOLD` early-exit from `calculate_baseline_score()`, `calculate_mean_reversion_score()`, and `DetailedScorer.score_all_indicators()`
   - Dead/flat stock filter (`_is_dead_or_flat`) preserved
   - Volume data still computed and available via `vol_ratio` in candidate output

3. **Multi-provider data pool** (also in `72ee1a7`, pre-staged from prior work)
   - Tiingo (primary), Alpha Vantage, Yahoo Finance behind common `DataProvider` interface
   - CPS-proportional symbol partitioning with automatic fallback on failure
   - Concurrent ThreadPoolExecutors per provider, rate-limited independently

4. **Full pipeline verification**
   - Update: 3,590 completed, 0 failed (~40 min)
   - Prediction: 5,320 scored from 5,414 total, **1,238 candidates** produced (~51 min)
   - Reports generated and email sent successfully

### Key Files Modified
- `src/bluehorseshoe/analysis/constants.py` — `MIN_MARKET_CAP`
- `src/bluehorseshoe/analysis/technical_analyzer.py` — Volume gates removed (lines 259, 304)
- `src/bluehorseshoe/analysis/indicators/detailed_scoring.py` — Volume gate removed (line 158)
- `src/bluehorseshoe/data/historical_data.py` — `get_active_symbol_list()` rewrite + provider pool integration
- `src/bluehorseshoe/core/symbols.py` — `backfill_overviews()`
- `src/bluehorseshoe/data/provider_pool.py` — New: provider pool with partitioning
- `src/bluehorseshoe/data/providers/` — New: tiingo.py, alphavantage.py, yahoo.py, base.py
- `src/main.py` — `--refresh-overviews` / `--ov-limit` flags
- `docker/docker-compose.yml` — Yahoo/AV data env vars
- `src/bluehorseshoe/core/config.py` — Provider settings

---

## Previous Sessions Summary

- **March 6:** Vectorized backtesting (`fdcf1b9`) — 13x speedup single-date, 7.4x range
- **March 5:** Score-once backtest refactor (`bd27559`) — 22 min → 2-3 sec; connors_flag BSON fix (`2dc5ec1`)
- **March 4:** Regime-adaptive weight selection tested and rejected; research droplet destroyed
- **March 3:** V3 weights deployed to production (`568b4ae`)

---

## Next Steps

- **Monitor steady-state timing** — Tonight's cron run should show real update speed (most symbols already up-to-date, skip logic kicks in). Expect significantly faster than the 40-min first run.
- **Prediction pipeline timing** — ~51 min for 5.3k symbols may need optimization if it grows. CPU scoring is the bottleneck (2 processes on 3 CPUs). Consider increasing worker count or chunking strategy.
- **Backfill overviews for remaining symbols** — ~2,000 NASDAQ/NYSE symbols still missing overviews. Run `python src/main.py -u --refresh-overviews --ov-limit 500` in batches.
- **Full historical backfill** — Many of the 3,500 newly-tracked symbols only have ~6 months of data. Deep backfill (`-b`) would improve indicator calculations and ML training.
- See `TO-DO.md` for full backlog

---

## Key Decisions

- **$300M market cap floor** — Gives ~3,591 symbols, closely matching Russell 3000. Configurable via `MIN_MARKET_CAP` constant.
- **Volume gate removed from scoring, not from reports** — All symbols get scored; `vol_ratio` still available in candidate output for eyeballing liquidity. Downstream filters (price, R/R ratio) still apply.
- **`--ov-limit` (not `--limit`)** for overview backfill — Avoids ambiguity with `-b --limit` which caps symbol count during data backfill.
- **V3 weights remain production** — No changes to scoring weights this session
- **Container limits**: 6GB RAM / 3 CPUs. Full pipeline now ~91 min (40 update + 51 predict) for first run

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
docker exec bluehorseshoe python src/main.py -p                          # Prediction (~51 min with 5k symbols)
docker exec bluehorseshoe python src/main.py -u                          # Data update (active-only, ~40 min first run)
docker exec bluehorseshoe python src/main.py -u --all                    # Data update (all 11k symbols)
docker exec bluehorseshoe python src/main.py -u --refresh-overviews      # Update + backfill missing overviews
docker exec bluehorseshoe python src/main.py -u --refresh-overviews --ov-limit 500  # Backfill capped at 500
docker exec bluehorseshoe pytest -v                                      # Tests (273 passing)
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

---

**Last Updated:** March 7, 2026
