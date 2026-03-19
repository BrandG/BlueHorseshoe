# Session Handoff

**Date:** March 19, 2026
**Status:** Curve/motif analysis feature complete (all 4 phases). Weights at 0.0 — features computed but no score contribution until catalog built and validated.

---

## What Was Done This Session (March 19)

### Curve/Motif Analysis (`88a3a62`)
Full 4-phase implementation of pattern-based trading signals using price-curve segmentation and motif forward-outcome scoring.

**Phase 1 — Curve Segmentation** (`segmenter.py`):
- Ramer-Douglas-Peucker algorithm on ATR-normalized prices
- Detects turning points → typed `Segment` objects (direction, magnitude, duration, slope, curvature)
- `segment_price_series()`, `segment_multi_window()` for 20/40-bar windows
- ATR normalization makes shapes comparable across $5 and $500 stocks

**Phase 2 — Signature Extraction** (`signature.py`):
- Last 3 segments → 17-dim numeric vector + compact motif key string (e.g. `"U3M:D1S:U2L"`)
- 5 bucketed descriptors per segment (direction, magnitude, duration, slope, curvature) + 2 global features (total_range, net_direction)
- ~27,000 possible keys — tractable lookup table
- `signatures_similar()` via Hamming distance for fuzzy matching

**Phase 3 — Motif Catalog** (`motif_catalog.py`):
- Scans full history per symbol, extracts signature at each date, checks +2%/-2% forward outcome
- Scoring: `edge × stability × support` with z-score significance test (p < 0.05)
- Parallel processing via `ProcessPoolExecutor`
- MongoDB `motif_catalog` collection for persistence
- CLI: `--motifs` (200 liquid), `--motifs --full` (all), `--motifs --symbols AAPL,MSFT`

**Phase 4 — Pipeline Integration**:
- `CurveIndicator` class following existing `Indicator` pattern
- Registered in `technical_analyzer._score_indicators()`, `detailed_scoring.py`, `weights.json`
- Motif scores loaded once in main process, passed to workers via `shared_ctx['motif_scores']`
- ML features: `curve_motif_score_20/40`, `curve_net_direction_20/40`, `curve_total_range_20/40`
- Weights start at 0.0 — features computed, no score contribution until validated
- Graceful degradation: empty catalog → all curve scores default to 0.0

**New files:**
- `src/bluehorseshoe/analysis/curves/__init__.py` — Package init
- `src/bluehorseshoe/analysis/curves/segmenter.py` — RDP segmentation, turning points, segments
- `src/bluehorseshoe/analysis/curves/signature.py` — Signature extraction, motif key generation
- `src/bluehorseshoe/analysis/curves/motif_catalog.py` — Catalog builder, forward outcomes, scoring
- `src/bluehorseshoe/analysis/curves/motif_lookup.py` — In-memory catalog lookup for workers
- `src/bluehorseshoe/analysis/indicators/curve_indicators.py` — CurveIndicator class
- `src/tests/test_curve_segmenter.py` — 12 tests
- `src/tests/test_curve_signature.py` — 9 tests
- `src/tests/test_motif_catalog.py` — 10 tests
- `src/tests/test_curve_indicator.py` — 7 tests

**Modified files:**
- `src/weights.json` — Added `curve` and `mr_curve` categories (MOTIF_SCORE_MULTIPLIER: 0.0)
- `src/bluehorseshoe/analysis/technical_analyzer.py` — Registered CurveIndicator, threaded `motif_scores` through all scoring paths
- `src/bluehorseshoe/analysis/indicators/detailed_scoring.py` — Registered CurveIndicator for LOO analysis
- `src/bluehorseshoe/analysis/strategy.py` — Loads motif_scores in `shared_ctx`, passes to `_init_worker()`
- `src/bluehorseshoe/analysis/strategy_interface.py` — Passes `motif_scores` from `worker_state` to scoring calls
- `src/main.py` — Added `--motifs` CLI flag with `--full`, `--symbols`, `--workers` options

### CNN Fear & Greed Index Integration (previous session, same day)
Added CNN Fear & Greed as the 3rd market-wide indicator alongside VIX and AAII. Uses contrarian logic — extreme fear is a bullish signal and vice versa.

**New files:**
- `src/bluehorseshoe/data/cnn_fear_greed.py` — `fetch_cnn_history()` (CNN undocumented API, requires browser User-Agent), `get_cnn_snapshot()` (score, 1-day change, SMA-20, 90-day percentile, 5-level rating classification)
- `src/tests/test_cnn_fear_greed.py` — 22 tests

**Modified files:**
- `src/bluehorseshoe/analysis/market_regime.py` — Contrarian scoring: score ≤ 25 → +2, ≤ 40 → +1, ≥ 80 → -1
- `src/bluehorseshoe/analysis/strategy.py` — CNN snapshot added to `sentiment_snapshots` as `$CNN_FG` source
- `src/main.py` — CNN flattening in both `-p` and `-r` paths (`cnn_score`, `cnn_rating`)
- `src/bluehorseshoe/reporting/html_reporter.py` — CNN F&G column in standard + email regime tables; arcade: 6-column grid, CNN FEAR/GREED panel, JS rendering with contrarian coloring

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

- **Build motif catalog** — Run `docker exec bluehorseshoe python src/main.py --motifs` on 200 liquid symbols. Inspect top 20 motifs for intuitive sense (V-bottoms should show positive edge). Verify negative-edge motifs also exist (confirming signal, not noise).
- **Validate curve integration** — Run prediction with catalog loaded, verify curve features appear in score documents and runtime impact is <10%
- **Enable curve weights** — After validation, set `MOTIF_SCORE_MULTIPLIER` > 0 in `weights.json`, backtest with/without to measure impact
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
- **Curve weights start at 0.0** — CurveIndicator computes features for ML training but contributes nothing to scores until the catalog is built and validated. This ensures zero impact on existing behavior during rollout.
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
**Latest commit:** `d0f4384` — docs: Add gstack skill references to CLAUDE.md
**Previous:** `88a3a62` — feat: Curve/motif analysis for pattern-based trading signals
**Pushed:** Yes, up to date with origin
**Tests:** 519 passing

---

**Last Updated:** March 19, 2026
