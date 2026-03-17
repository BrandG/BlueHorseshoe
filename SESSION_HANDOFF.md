# Session Handoff

**Date:** March 15, 2026
**Status:** StockTwits sentiment integration complete and deployed. Three sentiment sources now active: AlphaVantage, Tiingo, StockTwits.

---

## What Was Done This Session (March 15)

### StockTwits Sentiment Integration
Added StockTwits as a third sentiment source. Fetches 30 most recent messages per symbol from free public API, scores using user-provided Bullish/Bearish tags (ratio-based, no NLP), stores in MongoDB, displays in all report types.

**New files:**
- `src/bluehorseshoe/data/stocktwits.py` — 4 functions: `fetch_stocktwits_messages()`, `score_stocktwits_messages()`, `upsert_stocktwits_to_mongo()`, `get_stocktwits_sentiment_score_with_count()`
- `src/tests/test_stocktwits.py` — 12 tests (scoring edge cases, MongoDB ops, API fetch with mocks)

**Modified files:**
- `src/bluehorseshoe/analysis/strategy.py` — Pipeline wiring: after Tiingo block, fetches StockTwits for candidate symbols, scores, stores in `symbol_news_stocktwits`, saves snapshots with `source: "stocktwits"`. `sentiment_stocktwits` added to candidate dicts and `_prepare_scores_for_save()`.
- `src/bluehorseshoe/reporting/html_reporter.py` — All 3 report types show ST column. Arcade: grid columns, CSS, JS, JSON serialization all updated.
- `src/main.py` — `-r` regeneration path loads `sentiment_stocktwits` from saved metadata with fallback to `get_stocktwits_sentiment_score_with_count()`.
- `backup.conf` — Added `symbol_news_stocktwits` to `MONGO_COLLECTIONS` array.

### Cloudflare 403 Fix
StockTwits API returned 403 Forbidden from inside Docker (Cloudflare bot protection). Fixed by adding browser-like `User-Agent` header to requests. Works from both host and container after fix.

### Live Verification
- Ran full predict pipeline (5,417 symbols, ~73 min)
- Fetched StockTwits data for 62 symbols — real scores ranging from -1.0 to +1.0
- Reports regenerated with real data (e.g., ADM: ▲+1.00, AAPL: ▼-0.17, CTVA: ▼-1.00)
- All 445 tests pass, lint clean

---

## Previous Sessions Summary

- **March 15 (earlier):** Tiingo News sentiment integration with VADER scoring (`0e0fe88`)
- **March 10:** Automated daily backup to Google Drive via rclone (`backup.sh`, `backup.conf`)
- **March 9:** Pluggable strategy interface — `TradingStrategy` ABC, `BaselineStrategy`, `MeanReversionStrategy`, central registry
- **March 8:** MongoDB OHLCV dual-write removed, DuckDB thread-safety fix (RLock), new indicators (RVOL, Engulfing, Hammer)
- **March 7:** DuckDB migration complete — all 4 phases, schema optimization (4.0 GB → 484 MB)
- **March 6:** Vectorized backtesting — 13x speedup single-date, 7.4x range
- **March 5:** Score-once backtest refactor — 22 min → 2-3 sec; connors_flag BSON fix

---

## Next Steps

- **Accumulate sentiment data** — Need ~1 month of daily snapshots from all 3 sources before analyzing sentiment-price divergence signals
- **Add sentiment to ML features** — Once history exists, add `SentimentScore_Tiingo` and `SentimentScore_StockTwits` as features to `build_ml_features()`
- **Mark StockTwits done in TO-DO.md** — The StockTwits line item is still unchecked
- **Add a third strategy (e.g. Shorts)** — Trivial: subclass `TradingStrategy`, register in `strategy_registry.py`
- **Event-driven backtest** — Model trades as orders fed through daily bars
- **Additional sentiment sources** — Finviz, VIX, AAII, CNN Fear & Greed (see TO-DO.md)
- See `TO-DO.md` for full backlog

---

## Key Decisions

- **User-Agent header required for StockTwits** — Cloudflare blocks default `python-requests` UA from Docker. Browser-like UA string added to `_HEADERS` constant.
- **Ratio scoring for StockTwits** — `(bull - bear) / (bull + bear)`, range [-1, +1]. No NLP needed since sentiment comes from user tags.
- **Data collection phase first** — All 3 sentiment sources displayed in reports but NOT used as ML features or in scoring. Need history first.
- **VADER for Tiingo scoring** — Lightweight, stateless, thread-safe NLP for news headlines.
- **Source field on sentiment_snapshots** — Unique index `(symbol, date, source)` supports multiple providers.
- **Strategy objects are stateless and picklable** — Critical for `ProcessPoolExecutor` workers.
- **DuckDB is sole OHLCV store** — MongoDB retains scores, journal, overviews, checkpoints, symbols, news.
- **V3 weights remain production** — No changes to scoring weights.

---

## Key Files

| File | Role |
|------|------|
| `src/bluehorseshoe/data/stocktwits.py` | StockTwits fetch, bull/bear ratio scoring, MongoDB storage |
| `src/bluehorseshoe/data/tiingo_news.py` | Tiingo news fetch, VADER scoring, MongoDB storage |
| `src/bluehorseshoe/reporting/html_reporter.py` | All 3 report types with 3 sentiment columns (AV, Tiingo, ST) |
| `src/bluehorseshoe/analysis/strategy.py` | Pipeline wiring for all 3 sentiment sources |
| `src/main.py` | CLI entry, `-r` regeneration with all sentiment caches |
| `src/bluehorseshoe/data/duckdb_store.py` | DuckDB storage backend (thread-safe via RLock) |
| `src/bluehorseshoe/analysis/strategy_interface.py` | `TradingStrategy` ABC |
| `src/bluehorseshoe/analysis/strategy_registry.py` | Strategy registry |
| `backup.sh` / `backup.conf` | Daily backup to Google Drive |

---

## MongoDB Collections (Sentiment)

| Collection | Content |
|------------|---------|
| `symbol_news` | AlphaVantage news sentiment per symbol |
| `symbol_news_tiingo` | Raw Tiingo articles with VADER scores per symbol |
| `symbol_news_stocktwits` | StockTwits messages with bull/bear ratio per symbol |
| `sentiment_snapshots` | Daily snapshots, keyed by `(symbol, date, source)` where source is `"alphavantage"`, `"tiingo"`, or `"stocktwits"` |

---

## Pipeline Timing

| Pipeline | Symbols | Time |
|----------|---------|------|
| `-u` (data update) | 3,590 | ~3.5 min |
| `-p` (prediction) | 5,417 | ~73 min |
| `-r` (report regen) | — | ~30 sec |

---

## Infrastructure

### Research Droplet
- **Status:** DESTROYED (March 4, 2026)
- **Note:** When re-creating, must SCP `data/ohlcv.duckdb` to the droplet
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
docker exec bluehorseshoe python src/main.py -p                          # Prediction (~73 min)
docker exec bluehorseshoe python src/main.py -u                          # Data update (~3.5 min)
docker exec bluehorseshoe python src/main.py -r YYYY-MM-DD               # Regenerate report (~30 sec)
docker exec bluehorseshoe pytest -v                                      # Tests (445 passing)
docker exec bluehorseshoe ./lint.sh                                      # Lint
```

**Cron pipeline:** Runs at 02:00 UTC (Mon-Sat)
**Cron backup:** Runs at 05:00 UTC daily → Google Drive via rclone

---

## Git Status

**Branch:** master
**Latest commit:** `6586ba2` — feat: StockTwits sentiment integration with bull/bear ratio scoring
**Pushed:** Yes, up to date with origin

---

**Last Updated:** March 15, 2026
