# Session Handoff

**Date:** March 22, 2026
**Status:** Curve/motif analysis fully operational. Full catalog (11,501 symbols, 34,890 motifs, 6,114 passing threshold) live in production. Weights: baseline 10x, MR 25x.

---

## What Was Done This Session (March 19-22)

### Curve/Motif Analysis — Implementation (`88a3a62`)
Full 4-phase implementation of pattern-based trading signals using price-curve segmentation and motif forward-outcome scoring. See TO-DO.md for phase details.

### Catalog Build & OOM Fixes (`99549bc`)
- Initial 200-symbol validation run: 15,386 keys, 929 significant positive, 867 significant negative
- Full universe (11,501 symbols) OOM'd on first attempt — fixed with chunked loading (200 symbols/batch) and streaming stats (replaced per-observation returns lists with running `sum_returns`)
- Stability metric changed from rolling-window approach to z-score confidence proxy (cross-symbol returns aren't chronological)

### Resumable Builds (`e9bda6b`)
- Checkpoints to MongoDB `motif_build_progress` collection every 200 symbols
- `--resume` flag continues from last checkpoint — safe to interrupt and restart
- Checkpoint cleared on successful completion

### Research Droplet for Full Build
- Full 11,501-symbol catalog build took ~35 hours — too long to run on production (blocks DuckDB for `-u`/`-p`)
- Spun up `bh-research` droplet (s-2vcpu-4gb, nyc3, same VPC), SCP'd `ohlcv.duckdb`, connected to production MongoDB over private network
- Orphaned spawn processes from motif build blocked DuckDB for tonight's cron pipeline — had to manually kill and re-trigger. Container restart clears orphans.
- Research droplet destroyed after build completed

### Full Catalog Results
- **34,890** unique motif keys from **56.2M** observations
- **6,114** passing inclusion threshold (composite > 0.02 AND z > 1.96)
- **16,824** positive edge / **18,066** negative edge (balanced — real signal)
- Top motif `D2S:D1S:D4M_40` (staircase decline): **80% win rate** vs 37% baseline, avg +4.5% 5-day return
- Top patterns dominated by capitulation/selloff shapes — "sharp drop → bounce" thesis

### Weight Tuning (`05c7813`)
- Capitulation motifs naturally align with MR (50% of MR candidates get curve scores) but fight against baseline trend indicators
- Differentiated weights: **baseline 10x**, **MR 25x** — motifs are complementary with MR, contradictory with baseline
- At 25x, strong MR motifs contribute 2-6 points (meaningful vs total scores of 10-20)
- 10-bar window tested and rejected — 70% degenerate to 1-2 segments, only 1,018 unique keys, top 10 cover 38%

### CNN Fear & Greed Index Integration (earlier, same day as implementation)
Added CNN Fear & Greed as the 3rd market-wide indicator alongside VIX and AAII. Contrarian logic.

---

## Previous Session (March 17-19)

### AAII Bull/Bear Sentiment Survey Integration (`ebecd6d`)
Added AAII weekly sentiment survey as the 2nd market-wide indicator alongside VIX. Uses contrarian logic — extreme bearishness is a bullish signal and vice versa.

**New files:**
- `src/bluehorseshoe/data/aaii.py` — `fetch_aaii_history()` (Nasdaq Data Link API primary, Excel fallback from aaii.com), `get_aaii_snapshot()` (spread normalization, 8-week avg, 52-week percentile, 5-level signal classification)
- `src/tests/test_aaii.py` — 16 tests (API fetch, Excel fallback, both-fail, percentage auto-detection, snapshot exact/fallback date, all 5 signal classifications, spread normalization + clamping, 8-week average, percentile calculation)

**Modified files:**
- `docker/requirements.txt` — Added `nasdaq-data-link>=1.0.4`, `openpyxl>=3.1.0`
- `src/bluehorseshoe/core/config.py` — Added `nasdaq_data_link_api_key` setting
- `docker/.env` — Added `NASDAQ_DATA_LINK_API_KEY=`
- `src/bluehorseshoe/analysis/market_regime.py` — Contrarian scoring: spread ≤ -20 → +2, ≤ -10 → +1, ≥ 30 → -1
- `src/bluehorseshoe/analysis/strategy.py` — AAII snapshot added to `sentiment_snapshots` as `$AAII` source
- `src/main.py` — AAII flattening in both `-p` and `-r` paths (`aaii_spread`, `aaii_signal`)
- `src/bluehorseshoe/reporting/html_reporter.py` — AAII column in standard + email regime tables; arcade: 5-column grid, AAII SENTIMENT panel, JS rendering with contrarian coloring, data serialization
- `CLAUDE.md` — Added `NASDAQ_DATA_LINK_API_KEY` to Environment Variables

### Composite Sentiment Fix (`a38721c`)
Changed composite sentiment from z-score normalization to simple raw score averaging. The z-score approach compared each symbol's sentiment against the global market mean, causing positive raw sentiments to produce negative composites. Simple averaging preserves the intuitive direction of the signal.

**Modified files:**
- `src/bluehorseshoe/analysis/sentiment_normalizer.py` — `composite()` now averages raw scores directly instead of calling `normalize()` (z-score + tanh)
- `src/tests/test_sentiment_normalizer.py` — Updated composite tests to verify raw averaging

---

## Previous Sessions Summary

- **March 15:** Finviz sentiment, z-score normalizer, and arcade report refactor (`1754fa7`)
- **March 15:** VIX integration into market regime scoring and reports (`ad9d0e7`)
- **March 15:** StockTwits sentiment integration with bull/bear ratio scoring (`6586ba2`)
- **March 15 (earlier):** Tiingo News sentiment integration with VADER scoring (`0e0fe88`)
- **March 10:** Automated daily backup to Google Drive via rclone (`backup.sh`, `backup.conf`)
- **March 9:** Pluggable strategy interface — `TradingStrategy` ABC, `BaselineStrategy`, `MeanReversionStrategy`, central registry
- **March 8:** MongoDB OHLCV dual-write removed, DuckDB thread-safety fix (RLock), new indicators (RVOL, Engulfing, Hammer)
- **March 7:** DuckDB migration complete — all 4 phases, schema optimization (4.0 GB → 484 MB)
- **March 6:** Vectorized backtesting — 13x speedup single-date, 7.4x range
- **March 5:** Score-once backtest refactor — 22 min → 2-3 sec; connors_flag BSON fix

---

## Next Steps

- **Monitor curve impact** — Watch daily predictions for curve score contributions. In bearish markets, MR candidates should show meaningful curve boosts. Track whether curve-boosted picks outperform over coming weeks.
- **Rebuild catalog periodically** — As more data accumulates, rebuild on research droplet quarterly to capture new patterns. Use `--motifs --full --resume` for safety.
- **Accumulate sentiment data** — Need ~1 month of daily snapshots from all sources before analyzing sentiment-price divergence signals
- **Add sentiment to ML features** — Once history exists, add sentiment features to `build_ml_features()`
- **Add a third strategy (e.g. Shorts)** — Trivial: subclass `TradingStrategy`, register in `strategy_registry.py`
- **Event-driven backtest** — Model trades as orders fed through daily bars
- See `TO-DO.md` for full backlog

---

## Key Decisions

- **Raw averaging for composite sentiment** — Z-score normalization against global means was unintuitive (positive raw values → negative composite). Switched to simple average of raw scores. The `normalize()` method still exists if needed for other purposes.
- **AAII as contrarian indicator** — Extreme bearishness in the survey historically precedes rallies; extreme bullishness precedes pullbacks. Scoring reflects this inversion.
- **CNN F&G as contrarian indicator** — Same inversion: extreme fear (≤25) → +2 bullish points, fear (≤40) → +1, extreme greed (≥80) → -1 bearish. CNN's API requires a full browser User-Agent header (rejects short UAs with 418).
- **Nasdaq Data Link API with Excel fallback** — AAII data fetched via API when `NASDAQ_DATA_LINK_API_KEY` is set; otherwise falls back to direct Excel download from aaii.com. Both paths handle decimal vs percentage format auto-detection.
- **User-Agent header required for StockTwits** — Cloudflare blocks default `python-requests` UA from Docker.
- **Ratio scoring for StockTwits** — `(bull - bear) / (bull + bear)`, range [-1, +1]. No NLP needed.
- **Data collection phase first** — All sentiment sources displayed in reports but NOT used as ML features or in scoring. Need history first.
- **VADER for Tiingo/Finviz scoring** — Lightweight, stateless, thread-safe NLP for news headlines.
- **Source field on sentiment_snapshots** — Unique index `(symbol, date, source)` supports multiple providers.
- **Curve weights differentiated by strategy** — Baseline 10x, MR 25x. Capitulation motifs are complementary with mean reversion (both reward oversold conditions) but contradictory with baseline trend-following. Higher MR weight lets motifs meaningfully influence MR rankings.
- **DuckDB lock contention** — The motif catalog build holds a DuckDB connection for hours. Must not overlap with `-u`/`-p`. Run on research droplet or schedule outside cron window. Orphaned spawn processes from ProcessPoolExecutor can persist after kill — restart container to clear.
- **10-bar motif windows not viable** — Only 1,018 unique keys (vs 34,890 for 20/40), 70% degenerate to 1-2 segments. The 20/40-bar combination covers short and medium term effectively.
- **Strategy objects are stateless and picklable** — Critical for `ProcessPoolExecutor` workers.
- **DuckDB is sole OHLCV store** — MongoDB retains scores, journal, overviews, checkpoints, symbols, news.

---

## Key Files

| File | Role |
|------|------|
| `src/bluehorseshoe/data/cnn_fear_greed.py` | CNN Fear & Greed fetch, snapshot metrics |
| `src/bluehorseshoe/data/aaii.py` | AAII survey fetch (Nasdaq Data Link + Excel fallback), snapshot metrics |
| `src/bluehorseshoe/data/vix.py` | VIX fetch from CBOE, snapshot metrics |
| `src/bluehorseshoe/data/finviz_news.py` | Finviz news fetch, VADER scoring, MongoDB storage |
| `src/bluehorseshoe/data/stocktwits.py` | StockTwits fetch, bull/bear ratio scoring, MongoDB storage |
| `src/bluehorseshoe/data/tiingo_news.py` | Tiingo news fetch, VADER scoring, MongoDB storage |
| `src/bluehorseshoe/analysis/curves/segmenter.py` | RDP curve segmentation on ATR-normalized prices |
| `src/bluehorseshoe/analysis/curves/signature.py` | 17-dim signature extraction + motif key generation |
| `src/bluehorseshoe/analysis/curves/motif_catalog.py` | Catalog builder, forward outcomes, scoring |
| `src/bluehorseshoe/analysis/curves/motif_lookup.py` | In-memory catalog lookup for workers |
| `src/bluehorseshoe/analysis/indicators/curve_indicators.py` | CurveIndicator class (pipeline integration) |
| `src/bluehorseshoe/analysis/sentiment_normalizer.py` | Composite sentiment (raw score averaging) |
| `src/bluehorseshoe/reporting/html_reporter.py` | All 3 report types with 4 sentiment columns + VIX/AAII regime panels |
| `src/bluehorseshoe/analysis/strategy.py` | Pipeline wiring for all sentiment sources |
| `src/bluehorseshoe/analysis/market_regime.py` | Market health scoring (SPY, QQQ, breadth, VIX, AAII, CNN F&G) |
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
| `symbol_news_finviz` | Finviz news headlines with VADER scores per symbol |
| `sentiment_snapshots` | Daily snapshots, keyed by `(symbol, date, source)` where source is `"alphavantage"`, `"tiingo"`, `"stocktwits"`, `"finviz"`, `"vix"`, `"aaii"`, or `"cnn_fear_greed"` |
| `motif_catalog` | Curve motif patterns with forward-outcome statistics (edge, stability, composite score) |

---

## Pipeline Timing

| Pipeline | Symbols | Time |
|----------|---------|------|
| `-u` (data update) | 3,590 | ~30 min |
| `-p` (prediction) | 5,417 | ~72 min |
| `-r` (report regen) | — | ~30 sec |

---

## Infrastructure

### Research Droplet
- **Status:** DESTROYED (March 21, 2026) — used for full motif catalog build (~35 hrs)
- **Note:** When re-creating, must SCP `data/ohlcv.duckdb` to the droplet. Fix CPU limit in `docker-compose.research.yml` if using s-2vcpu size (set cpus to "2").
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
docker exec bluehorseshoe python src/main.py -p                          # Prediction (~72 min)
docker exec bluehorseshoe python src/main.py -u                          # Data update (~30 min)
docker exec bluehorseshoe python src/main.py -r YYYY-MM-DD               # Regenerate report (~30 sec)
docker exec bluehorseshoe pytest -v                                      # Tests (519 passing)
docker exec bluehorseshoe ./lint.sh                                      # Lint
```

**Cron pipeline:** Runs at 02:00 UTC (Mon-Sat)
**Cron backup:** Runs at 05:00 UTC daily → Google Drive via rclone

---

## Git Status

**Branch:** master
**Latest commit:** `05c7813` — chore: Differentiate curve weights by strategy (baseline 10x, MR 25x)
**Pushed:** Yes, up to date with origin
**Tests:** 519 passing

---

**Last Updated:** March 22, 2026
