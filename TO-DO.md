# TO-DO

## Near Term

### New Indicators

- ~~**Relative Volume (RVOL)**~~ **Done** — Added `calculate_rvol()` to `VolumeIndicator` with tiered scoring: RVOL < 0.5 → -2.0, 0.5-0.8 → -1.0, 0.8-1.2 → 0.0, 1.2-1.5 → +0.5, 1.5-2.0 → +1.0, >2.0 → +2.0. Registered in `get_score()`, `detailed_scoring.py`, and `weights.json` (baseline: 1.5, MR: 0.0 — volume confirmation matters for breakouts but not for mean reversion dips).
- ~~**Engulfing & Hammer candlestick patterns**~~ **Done** — Added `find_engulfing()` (CDLENGULFING) and `find_hammer()` (CDLHAMMER) to `CandlestickIndicator` with weight multipliers in `weights.json` (baseline: engulfing 1.0, hammer 0.5; MR: engulfing 1.5, hammer 2.0).

### Curve/Motif Analysis

- [x] **Phase 1: Curve Segmentation** — **Done** (`88a3a62`). RDP algorithm on ATR-normalized prices detects turning points, produces typed `Segment` objects with direction, magnitude, duration, slope, curvature. `segment_price_series()` and `segment_multi_window()` in `src/bluehorseshoe/analysis/curves/segmenter.py`. 12 tests.
- [x] **Phase 2: Signature Extraction** — **Done** (`88a3a62`). Converts `Segmentation` → 17-dim numeric vector + compact motif key string (e.g. `"U3M:D1S:U2L"`). 5 bucketed descriptors per segment × 3 segments + 2 global features. `extract_signature()` in `src/bluehorseshoe/analysis/curves/signature.py`. 9 tests.
- [x] **Phase 3: Motif Catalog** — **Done** (`88a3a62`). Scans historical data, extracts signatures at every date, measures forward outcomes (+2%/-2% win/loss), computes edge/stability/support/composite scores. Parallel via `ProcessPoolExecutor`. Stores in MongoDB `motif_catalog` collection. CLI: `--motifs` (with `--full`, `--symbols`, `--workers`). `src/bluehorseshoe/analysis/curves/motif_catalog.py`. 10 tests.
- [x] **Phase 4: Pipeline Integration** — **Done** (`88a3a62`). `CurveIndicator` registered in `technical_analyzer.py`, `detailed_scoring.py`, `weights.json`. Motif scores loaded via `shared_ctx` → workers. ML features: `curve_motif_score_20/40`, `curve_net_direction_20/40`, `curve_total_range_20/40`. **Weights at 0.0** — features computed but no score contribution until catalog built and validated. 7 tests.
- [x] **Validation** — **Done**. Catalog built from 187 symbols (20 min). 15,386 unique motif keys, 929 with significant positive edge (z>1.96), 867 with significant negative edge. Top motifs show 50-57% win rate (vs ~39% baseline). Drop-then-bounce patterns (D*:U*) dominate positive edge. Overextended rallies (U0M:U0M:U3L) show 3.9% win rate — strongly bearish. 719 motifs pass inclusion threshold for pipeline use.
- [ ] **Enable weights** — Set `MOTIF_SCORE_MULTIPLIER` > 0 in `weights.json` and backtest to measure impact. Run `--motifs --full` for deeper catalog coverage.

### Architecture & Refactoring

- ~~**Strategy as a pluggable interface**~~ **Done** — Implemented `TradingStrategy` ABC in `strategy_interface.py` with `BaselineStrategy` and `MeanReversionStrategy`. Central registry in `strategy_registry.py` (`get_strategy()`, `get_all_strategies()`, `get_strategy_keys()`). All consumers (backtest, reporter, journal, SwingTrader, worker functions) now loop over strategy objects instead of hardcoded if/else branches. Adding a third strategy (e.g. shorts) requires only: subclass `TradingStrategy`, register in `strategy_registry.py` — zero changes to downstream code.

- Event-driven backtest with an order book. Instead of the current "check high/low against levels" approach, model it as: generate orders → feed daily bars → match orders → update positions. That naturally handles split exits, trailing stops, breakeven stops, shorts — all as different order types rather than special-case code paths.

## Medium Term

### IBKR Integration
- Paper trading mode — bracket order submission code written (`f3ed895`) but not yet tested with live IBKR connection
- Move T2 stop to breakeven after T1 fills — requires real-time order monitoring loop
- Position sizing based on account equity and per-trade risk (`MAX_RISK_PERCENT`)
- Real-time P&L tracking and stop-loss/take-profit order management

### Sentiment Analysis
- Phase 2: ~~Evaluate whether sentiment signal correlates with outcomes over several weeks~~ **Done** (`analyze_sentiment_impact.py`)
  - ~~Log sentiment scores alongside backtest results for comparison~~ **Done** — sentiment now saved in `trade_scores` metadata and backtest CSV
  - Consider weighting sentiment more heavily for baseline/trend-following than mean reversion (oversold names often have bad news by definition)
- Phase 2b: Diversify sentiment sources beyond AlphaVantage NEWS_SENTIMENT
  - AV only returns current news (can't backfill historical sentiment) and the 7-day averaging window may wash out signal
  - Daily snapshots now stored in `sentiment_snapshots` collection during `-p` (score + article_count per symbol per date)
  - After ~1 month of data, analyze rate-of-change and sentiment-price divergence signals
  - **Sources to add (per-symbol):**
    - [x] **Tiingo News** — **Done** (`0e0fe88`). Fetch headlines via Tiingo News API, score with VADER, store in `symbol_news_tiingo` collection. Snapshots saved with `source: "tiingo"`. Both AV and Tiingo sentiment displayed side-by-side in all reports (standard, email, arcade).
    - [x] **StockTwits** — **Done** (`6586ba2`). Fetch 30 most recent messages per symbol from free public API, score using bull/bear tag ratio (no NLP), store in `symbol_news_stocktwits` collection. Snapshots saved with `source: "stocktwits"`. All 3 sentiment sources (AV, Tiingo, ST) displayed side-by-side in reports.
    - [x] **Finviz** — **Done**. Fetch per-symbol news headlines via `finvizfinance` library, score with VADER, store in `symbol_news_finviz` collection. Snapshots saved with `source: "finviz"`. All 4 sentiment sources (AV, Tiingo, ST, FV) displayed side-by-side in reports.
  - **Sources to add (market-wide, one score per day):**
    - [x] **VIX** — **Done** (`vix.py`). Fetch daily OHLC from CBOE free API, compute close/change/SMA-20/percentile/fear-level. Integrated into `MarketRegime.get_market_health()` (±2 score points), arcade status bar (4th panel), standard/email regime tables, and `sentiment_snapshots` collection.
    - [x] **AAII Bull/Bear Survey** — **Done** (`aaii.py`, `ebecd6d`). Fetch weekly survey from Nasdaq Data Link API (fallback: Excel from aaii.com). Bull-Bear Spread normalized to [-1,1], 8-week avg, 52-week percentile, 5-level signal classification. Contrarian scoring in `MarketRegime` (extreme bearishness → bullish points). AAII panel in arcade status bar (5th panel), standard/email regime tables, and `sentiment_snapshots` collection.
    - [x] **CNN Fear & Greed Index** — **Done** (`cnn_fear_greed.py`). Fetch composite score (0-100) from CNN's undocumented API, classify into 5 sentiment buckets (Extreme Fear/Fear/Neutral/Greed/Extreme Greed). Contrarian scoring in `MarketRegime` (extreme fear → bullish points). CNN F&G panel in arcade status bar (6th panel), standard/email regime tables, and `sentiment_snapshots` collection.
  - **Future / higher effort:**
    - **Options flow / put-call ratio** — institutional sentiment proxy, available via CBOE or broker APIs
    - **Earnings sentiment** — NLP on earnings call transcripts (e.g. via SEC EDGAR XBRL filings)
    - **FinBERT / custom NLP** — run our own sentiment model on headlines or SEC filings for higher accuracy than AV's generic scoring
  - Design as pluggable `SentimentProvider` interface so multiple sources can be aggregated with configurable weights
- Phase 3 (only if Phase 2 shows value): Explore LLM-based enrichment for nuanced reads
  - High cost/latency per call — only justified if structured sentiment proves insufficient
  - Non-deterministic output makes backtesting difficult; would need caching/snapshotting

### Track Record / Signal Journal
- Layer B: Hypothetical trade engine — auto-evaluate signal outcomes after hold period
  - Run automatically N days after each batch (e.g. cron or post-prediction check for mature batches)
  - For each signal: was entry hit? Stop hit first? Target hit? Time exit?
  - Track max adverse excursion (MAE), max favorable excursion (MFE), holding days
  - Store in `journal_hypothetical_trades` collection
  - Compute: win rate, avg win/loss, expectancy, profit factor, Sharpe, Sortino, max drawdown
  - Include SPY benchmark comparison for the same period
- Layer C: Real execution journal — immutable record of what you did with real money
  - **`journal_capital_snapshots`** — daily equity state (one record per trading day)
  - **`journal_executed_trades`** — one record per real trade, linked to signal
  - **`journal_skipped_signals`** — signals BH recommended but you chose not to trade
  - **Behavioral analytics** — signal adherence rate, override impact, slippage profile, discipline metrics
  - **Monthly capital statement** — auto-generated with returns, benchmark comparison, model adherence score
- Portfolio-level metrics dashboard (auto-computed weekly)
  - CAGR, monthly returns, win rate, expectancy, profit factor
  - Sharpe, Sortino, Ulcer index, max drawdown (absolute + rolling 30-day)
  - Hypothetical vs actual comparison table
- Statistical validation
  - Confidence intervals on win rate and expectancy
  - Monte Carlo simulation for edge significance (p-values)
  - Regime-tagged performance breakdown (bull/bear/choppy)
  - Rank decay analysis — does top-5 outperform top-10?

### Backtest Realism
- Add commission modeling to `BacktestConfig` (e.g. `commission_pct` applied on entry and exit)
- Add spread/slippage modeling beyond current gap logic (configurable `avg_spread_bps`)
- Portfolio-level backtesting — simulate running top N picks simultaneously with fixed capital allocation
- Track max drawdown, Sharpe ratio, and other portfolio-level metrics

### Data & Infrastructure
- Full historical backfill — backfill all ~6,000 active symbols going back 20 years. Deep history improves ML training, long-range backtesting, and indicator calculations that depend on long lookback periods (200-day EMA, etc.). Will need to run in batches respecting API rate limits (`-b --resume --limit N`). SPY + QQQ already backfilled to 2000.
- Backfill overviews — ~2,000 symbols still missing overviews. Run `-u --refresh-overviews --ov-limit 500` in batches.
- Add post-prediction step to track symbols with stale/insufficient data and update an invalid symbols list, so they can be excluded from future runs or flagged for re-backfill
- Add Redis or in-memory caching for repeated indicator calculations during LOO/optimization runs
- Distributed backtesting — allow running date ranges in parallel across multiple workers
- Research droplet DuckDB access — when spinning up `bh-research`, SCP `data/ohlcv.duckdb` as part of the setup process. Previously the droplet queried MongoDB over the network; now DuckDB is the sole OHLCV store so the file must be copied. Consider scripting this into the droplet provisioning workflow.
- ~~**DuckDB periodic backups**~~ **Done** — `backup.sh` runs daily at 05:00 UTC via cron. Flushes DuckDB WAL, compresses DuckDB + selective mongodump (7 collections) + ML models into a single `.tar` archive, uploads to Google Drive via rclone. Weekday backups go to `daily/` (keep 7), Sunday to `weekly/` (keep 4). ~215 MB per archive. Pipeline safety check prevents running during `-u`/`-p`. Failure alerts via email.
- ~~**Non-git file backup strategy**~~ **Done** — Covered by the same `backup.sh` script above. DuckDB, MongoDB (scores, journal, overviews, symbols, news, checkpoints), and ML models are all included. Config in `backup.conf`, creds sourced from `docker/.env` at runtime.

## Long Term

### Strategy Expansion
- Intraday/scalping strategy using shorter timeframes
- Sector rotation overlay — weight candidates by sector momentum
- Earnings avoidance filter — skip symbols with earnings within hold period
- Correlation filter — avoid picking multiple highly correlated symbols in the same batch

### ML Improvements
- Automated model retraining pipeline on a schedule (monthly or quarterly)
- Feature importance tracking over time — detect model drift
- Ensemble methods — combine XGBoost with other models (LightGBM, neural net)
- **Meta-score ranking** — fuse independent signals (technical score, sentiment, ML win probability, Connors flag) into a single composite rank for candidate sorting. Currently candidates are ranked by technical score alone; ML/sentiment are displayed but don't influence selection order.
  - Use logistic regression on journal_signals outcomes: `P(win) = sigmoid(w1*score + w2*sentiment + w3*ml_prob + w4*connors)` — learned coefficients become the weights
  - Validate with grid search over weight combinations, measuring top-N win rate / avg P&L
  - Normalize features to comparable scales before fitting (score is 0-30, sentiment -1 to +1, ML prob 0-1)
  - Use leave-one-date-out cross-validation to guard against overfitting (small sample size until more batch dates accumulate)
  - Prerequisite: accumulate several more weeks of journal_signals with sentiment data before fitting is meaningful
  - **Interim signal hierarchy** (until meta-score is built): ML Win% as gate (skip < ~55%), Score for ranking among survivors, Sentiment as tiebreaker only for baseline picks. Sentiment is weakest signal — AV can't backfill historical data so it was never validated against outcomes, and for MR picks negative sentiment is expected (oversold names have bad news by definition).
- Use split-exit outcome data as additional training signal

### Monitoring & Ops
- Dashboard for live system health (API rate limits, data freshness, model staleness)
- Alert on prediction pipeline failures or anomalous outputs
- Backtest regression suite — auto-run on weight or code changes to catch performance degradation
