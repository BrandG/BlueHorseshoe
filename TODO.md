# TO-DO

## Near Term

### Reporting
- ~~Holiday-aware exit warning banner~~ (done 2026-04-12) — Amber/neon banners on all three HTML report types (standard, email, arcade) when an NYSE holiday falls in the current week. Uses existing `pandas.tseries.holiday` via shared `market_calendar.py` module (no new dependency). Banner uses the report's target date, not system clock.

### Architecture & Refactoring

- Event-driven backtest with an order book. Instead of the current "check high/low against levels" approach, model it as: generate orders → feed daily bars → match orders → update positions. That naturally handles split exits, trailing stops, breakeven stops, shorts — all as different order types rather than special-case code paths.

### MR Weight Optimization (in progress)
- **Fix mr_mean_reversion_specific dominance** — at any multiplier above ~1.5, mr_specific drowns out all other indicator categories (up to 96 points at 6x). Options to explore:
  - **Option A: Cap** — hard-limit mr_specific contribution to 8-10 points regardless of how many sub-indicators fire
  - **Option B: Average** — change aggregation from sum to average across 5 sub-indicators (max ~6 instead of ~30)
  - **Option D: Gate** — only allow mr_specific to contribute if trend/momentum/volume also show positive signal (confirmation that bleeding is slowing)
  - Whichever approach is chosen, **validate with assumption tester AND eyeball prediction output before deploying**
- ~~Falling knife filter~~ (done) — -5.0 penalty for 2 consecutive red candles, MR only. Adequate with current weights, insufficient against inflated mr_specific.
- Baseline weight tuning complete — uniform 1.0 is optimal for bullish. No changes needed to production Baseline weights.
- ~~mr_curve saturation test~~ (done) — motif signal saturates between 3x and 5x for both MR and Baseline. Current production values (25x MR, 10x BL) are well above threshold.

### Hypothesis Engine Enhancements
- ~~Build hypothesis engine (Layer B)~~ (done 2026-04-04) — `trade_evaluator.py`, `hypothesis_engine.py`, CLI `--evaluate`, pipeline integration
- ~~Remove "Yesterday's Results" from reports~~ (done 2026-04-04) — one-day price action is noise
- **Add "Signal Track Record" report section** — replace Yesterday's Results with real N-day outcomes from `journal_hypothetical_trades`. Show win rate, avg P&L, alpha vs SPY, top winners/losers for recently matured batches. Wait until 5-10 batches accumulate before building.
- **Refactor Backtester to use trade_evaluator.py** — Phase 2: `_check_entry()` and `_check_active_trade()` in backtest.py delegate to shared `trade_evaluator` functions, eliminating duplication.

### Regime-Aware Strategy (partially done)
- ~~Add REGIME_PROFILES to constants.py~~ (done)
- ~~Wire regime-adjusted stop/target multipliers into BaselineStrategy~~ (done)
- Paper trader: apply `max_positions_pct` from regime profile (reduce positions in bullish market)
- Backtester: regime-aware hold_days (Bearish=7d, Neutral/Bullish=5d)
- HTML report: display active regime parameters ("Stop 2.5x / Target 3.5x / Hold 7d")
- MR stop/target: use regime multiplier as ML fallback instead of hardcoded 2.0
- ~~Consider gating MR picks in bullish regime~~ — decided against. Both strategies run in all regimes; scores naturally surface the best picks. MR bullish EV is mediocre but not terrible.

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
- ~~Layer B: Hypothetical trade engine~~ (done 2026-04-04) — `trade_evaluator.py`, `hypothesis_engine.py`, CLI `--evaluate`, pipeline integration. Auto-evaluates matured signals for entry/stop/target/time exit. Stores outcomes in `journal_hypothetical_trades` with MAE/MFE.
  - Remaining: win rate, expectancy, profit factor, Sharpe, Sortino, max drawdown computations (will come with Signal Track Record report section)
  - Remaining: SPY benchmark comparison for the same period
- ~~Trade history CSV import~~ (done 2026-04-12) — `src/import_trade_history.py` imports raw broker fills into `trade_fills`, synthesizes FIFO positions into `trade_positions`, generates `trade_reviews`. Era-tagged: `"pre_bh"` (pre-2026) vs `"bh_v2"` (2026+). 101 positions imported, 64.9% win rate on BH-era trades.
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

### Security
- ~~Add MongoDB authentication~~ (done 2026-04-03) — User `bhapp` with readWrite on `bluehorseshoe` database, `--auth` flag in docker-compose. Defense-in-depth alongside the ufw firewall and localhost bind (both done 2026-03-27 after ransomware incident).

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
- ~~Fix email delivery after Docker→host migration~~ (done) — Brevo SMTP credentials moved to root `.env`, `.env` sourcing added to `run.sh` and `run_daily_pipeline.sh`
- Remove Docker dependency from research droplet setup (optional, low priority)
- Upgrade yfinance from 0.2.25 to latest (1.2.2+) — Yahoo changed their API and the old version can't parse responses. Raw API works fine; the library is broken. Test upgrade impact on BH's existing Yahoo provider before deploying.
- Suppress "Cannot write to a read-only DuckDBStore" warnings during `-p` — `save_historical_data()` in `historical_data.py:86` attempts opportunistic cache-writes that correctly fail in read-only mode. Check `store._read_only` (or add a `store.is_read_only` property) before calling `save_symbol()` to avoid noisy warnings. Low priority — harmless, prediction still works.

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
