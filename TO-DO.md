# TO-DO

## Near Term

### Architecture & Refactoring

- Event-driven backtest with an order book. Instead of the current "check high/low against levels" approach, model it as: generate orders → feed daily bars → match orders → update positions. That naturally handles split exits, trailing stops, breakeven stops, shorts — all as different order types rather than special-case code paths.

### Regime-Aware Strategy (partially done)
- ~~Add REGIME_PROFILES to constants.py~~ (done)
- ~~Wire regime-adjusted stop/target multipliers into BaselineStrategy~~ (done)
- Paper trader: apply `max_positions_pct` from regime profile (reduce positions in bullish market)
- Backtester: regime-aware hold_days (Bearish=7d, Neutral/Bullish=5d)
- HTML report: display active regime parameters ("Stop 2.5x / Target 3.5x / Hold 7d")
- MR stop/target: use regime multiplier as ML fallback instead of hardcoded 2.0
- Consider gating MR picks in bullish regime (negative EV per research)

## Medium Term

### IBKR Integration
- Paper trading mode — bracket order submission code written (`f3ed895`) but not yet tested with live IBKR connection
- Move T2 stop to breakeven after T1 fills — requires real-time order monitoring loop
- Position sizing based on account equity and per-trade risk (`MAX_RISK_PERCENT`)
- Real-time P&L tracking and stop-loss/take-profit order management

### Sentiment Analysis
- Consider weighting sentiment more heavily for baseline/trend-following than mean reversion (oversold names often have bad news by definition)
- After ~1 month of snapshot data, analyze rate-of-change and sentiment-price divergence signals
- **Future sentiment sources:**
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
- **Journal enhancements:**
  - `journal_capital_snapshots` — daily equity state (one record per trading day)
  - `journal_skipped_signals` — signals BH recommended but you chose not to trade
  - Monthly capital statement — auto-generated with returns, benchmark comparison, model adherence score
  - HTML journal report generation (alongside existing prediction reports)
- Portfolio-level metrics dashboard (auto-computed weekly)
  - CAGR, monthly returns, win rate, expectancy, profit factor
  - Sharpe, Sortino, Ulcer index, max drawdown (absolute + rolling 30-day)
  - Hypothetical vs actual comparison table
- Statistical validation
  - Confidence intervals on win rate and expectancy
  - Monte Carlo simulation for edge significance (p-values)
  - ~~Regime-tagged performance breakdown (bull/bear/choppy)~~ (done — assumption_tester v2)
  - ~~Rank decay analysis — does top-5 outperform top-10?~~ (done — no significant difference found)

### Backtest Realism
- Add commission modeling to `BacktestConfig` (e.g. `commission_pct` applied on entry and exit)
- Add spread/slippage modeling beyond current gap logic (configurable `avg_spread_bps`)
- Portfolio-level backtesting — simulate running top N picks simultaneously with fixed capital allocation
- Track max drawdown, Sharpe ratio, and other portfolio-level metrics

### Data & Infrastructure
- **Migrate OHLCV storage from DuckDB to Parquet files** — DuckDB's single-writer file lock causes contention when multiple processes/pipelines run concurrently (e.g. `-u` and `-p`, or orphaned ProcessPoolExecutor workers holding the lock after a kill). Two-phase approach:
  1. **Phase 1: DuckDB read-only mode** — worker processes and concurrent readers open with `read_only=True`. Eliminates lock contention for the common case (one writer, many readers). Quick win.
  2. **Phase 2: Parquet file backend** — replace `DuckDBStore` with a `ParquetStore` using the same interface. Writes become atomic file swaps (`to_parquet` + rename), reads never block. DuckDB can still query Parquet via `read_parquet()` for ad-hoc analysis. No server, no lock files, no orphaned connections. The 15 consumer files go through the store abstraction so downstream changes are minimal.
- Full historical backfill — backfill all ~6,000 active symbols going back 20 years. Deep history improves ML training, long-range backtesting, and indicator calculations that depend on long lookback periods (200-day EMA, etc.). Will need to run in batches respecting API rate limits (`-b --resume --limit N`). SPY + QQQ already backfilled to 2000.
- Backfill overviews — ~2,000 symbols still missing overviews. Run `-u --refresh-overviews --ov-limit 500` in batches.
- Add post-prediction step to track symbols with stale/insufficient data and update an invalid symbols list, so they can be excluded from future runs or flagged for re-backfill
- Add Redis or in-memory caching for repeated indicator calculations during LOO/optimization runs
- Distributed backtesting — allow running date ranges in parallel across multiple workers
- Remove BH Python container from docker-compose — Python now runs natively on host via venv, but the container is still defined in docker-compose.yml as a fallback. Remove it after confirming the host-based daily pipeline succeeds (next run: 02:00 UTC). Then start the systemd API service (`systemctl start bluehorseshoe-api`).
- Remove Docker dependency from research droplet setup (optional, low priority)

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
