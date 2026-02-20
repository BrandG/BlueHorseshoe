# TO-DO

## Near Term

### Split-Exit Strategy Validation — IN PROGRESS
- ~~Run split-exit vs single-exit comparison across a date range~~ (running: Oct 1 → Feb 6, biweekly, hold 10, top 20)
- ~~Compare Plan A (`fixed_pct`) and Plan B (`atr_tiered`) against baseline single-exit~~ (Plan B chosen as default)
- Tune T1 target (try 1.5%, 2%, 2.5%, 3%) and measure impact on blended P&L and win rate
- Decide whether split-exit should become the default backtest mode

### LOO Weight Tuning — IN PROGRESS
- ~~Kick off broad LOO run~~ (running: 28 dates, Aug 1 → Feb 7, weekly, top 50, hold 10, split)
- Review LOO analysis results once the broad run completes
- Single-date hints: `penalty_rsi` may be hurting, `penalty_ema_overextension` valuable — needs multi-date validation
- Apply suggested weight changes to `src/weights.json` for indicators with strong P&L deltas
- Re-run backtest to validate improvements before/after weight changes

## Medium Term

### IBKR Integration
- ~~Real-time quote skeleton (`-q`) — fetch bid/ask/last/volume snapshots via ib_async~~ ✅
- ~~Watchlist monitor (`-m`) — poll quotes on a loop, live terminal dashboard, CSV logging~~ ✅
- ~~Market hours awareness — skip IBKR calls when market is closed (Mon-Fri 9:30-16:00 ET)~~ ✅
- ~~Holiday calendar — skip polling on market holidays~~ ✅ (`9a58e60`)
- Paper trading mode — bracket order submission code written (`f3ed895`) but not yet tested with live IBKR connection
- Position sizing based on account equity and per-trade risk (`MAX_RISK_PERCENT`)
- Real-time P&L tracking and stop-loss/take-profit order management
- Consider split-exit as native order strategy (bracket orders with two profit targets)

### Sentiment Analysis
- Phase 1: Use AlphaVantage News & Sentiments endpoint for top 10 candidates (post-scoring)
  - Pull `ticker_sentiment_score` and `relevance_score` per article
  - Display as advisory column in HTML report (green/yellow/red flag per candidate)
  - Not used in scoring — purely a visual aid for manual decision-making
- Phase 2: Evaluate whether sentiment signal correlates with outcomes over several weeks
  - Log sentiment scores alongside backtest results for comparison
  - Consider weighting sentiment more heavily for baseline/trend-following than mean reversion (oversold names often have bad news by definition)
- Phase 3 (only if Phase 2 shows value): Explore LLM-based enrichment for nuanced reads
  - High cost/latency per call — only justified if structured sentiment proves insufficient
  - Non-deterministic output makes backtesting difficult; would need caching/snapshotting

### Backtest Realism
- Add commission modeling to `BacktestConfig` (e.g. `commission_pct` applied on entry and exit)
- Add spread/slippage modeling beyond current gap logic (configurable `avg_spread_bps`)
- Portfolio-level backtesting — simulate running top N picks simultaneously with fixed capital allocation
- Track max drawdown, Sharpe ratio, and other portfolio-level metrics

### Data & Infrastructure
- Add post-prediction step to track symbols with stale/insufficient data and update an invalid symbols list, so they can be excluded from future runs or flagged for re-backfill
- Reduce Alpha Vantage dependency — evaluate alternative data sources (Polygon, Tiingo, Yahoo Finance bulk)
- Add Redis or in-memory caching for repeated indicator calculations during LOO/optimization runs
- Distributed backtesting — allow running date ranges in parallel across multiple workers

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
- Use split-exit outcome data as additional training signal

### Monitoring & Ops
- Dashboard for live system health (API rate limits, data freshness, model staleness)
- Alert on prediction pipeline failures or anomalous outputs
- Backtest regression suite — auto-run on weight or code changes to catch performance degradation
