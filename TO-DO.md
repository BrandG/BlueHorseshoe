# TO-DO

## Near Term

### Split-Exit Strategy — DONE
- ~~Run split-exit vs single-exit comparison across a date range~~ ✅
- ~~Compare Plan A (`fixed_pct`) and Plan B (`atr_tiered`) against baseline single-exit~~ ✅ Plan A (2% T1) won: +6.72% total P&L vs -26.0% single-exit
- ~~Integrate T1 target into prediction pipeline, reports, and paper trading~~ ✅ (`41b4df3`)
- Future: Monitor T2 stop-to-breakeven after T1 fill (requires real-time order monitoring via IBKR)

### Weight Optimization — DONE
- ~~LOO analysis across 30 stratified dates~~ ✅
- ~~Leave-one-in analysis to identify indicators worth restoring~~ ✅
- ~~Three-way backtest comparison (V2 vs V3 vs V3.1)~~ ✅
- ~~Deploy V3 data-driven weights to production~~ ✅ (`568b4ae`)
- V3 results: +84.0% total P&L, 61.4% WR, 1.40 PF across 30 dates (vs V2: +71.3%, 59.9%, 1.19)
- Zeroed underperforming baseline trend indicators (Donchian, SuperTrend, TTM Squeeze, Aroon, Keltner, VWAP)
- V3.1 (restored ADX + AD_LINE) tested but did not improve over V3 — discarded
- Reference weights preserved: `src/weights_v2.json`, `src/weights_v3.json`

### Speed optimization and refactoring
- Split scoring from backtesting. This is the biggest pain point. Right now, a backtest re-scores all 6,000+ symbols from scratch every time. I'd score once and persist the results, then backtest by replaying against stored scores. That single-date test we're waiting on right now? It should take seconds, not an hour. You'd have a scores table and a separate backtest engine that just reads scores and simulates exits against OHLCV data.

- Vectorized backtesting. Instead of looping through symbols one at a time in Python, process all trades as a DataFrame. Entry prices, stop levels, targets — they're all just columns. Each day's OHLCV gets compared against all open positions at once with numpy operations. What currently takes an hour could take seconds.

- Better data provider. Alpha Vantage rate limiting is a constant bottleneck. I'd abstract the data layer so you could swap providers. Polygon.io, Tiingo, or even Yahoo Finance for backtesting purposes — any of them would give you bulk historical data without the 2-calls-per-second constraint.

- Swap MongoDB for something columnar for OHLCV data. Mongo is fine for scores and metadata, but time-series OHLCV data is a natural fit for Parquet files or DuckDB. Reads would be 10-50x faster, no server needed, and you can do vectorized queries. Keep Mongo for the document-shaped stuff (scores, trade journal, config).

- Strategy as a pluggable interface. Something like:

  class Strategy(ABC):
      def score(self, data: pd.DataFrame) -> float: ...
      def entry_price(self, data: pd.DataFrame) -> float: ...
      def stop_loss(self, data: pd.DataFrame) -> float: ...
      def take_profit(self, data: pd.DataFrame) -> float: ...
      def direction(self) -> Literal['long', 'short']: ...

  Baseline, MR, and Shorts would all implement the same interface. The backtest engine wouldn't care which strategy generated the trade — it just processes entries, stops, and targets. Adding shorts becomes trivial because the engine already handles direction.

- Event-driven backtest with an order book. Instead of the current "check high/low against levels" approach, model it as: generate orders → feed daily bars → match orders → update positions. That naturally handles split exits, trailing stops, breakeven stops, shorts — all as different order types rather than special-case code paths.

## Medium Term

### IBKR Integration
- ~~Real-time quote skeleton (`-q`) — fetch bid/ask/last/volume snapshots via ib_async~~ ✅
- ~~Watchlist monitor (`-m`) — poll quotes on a loop, live terminal dashboard, CSV logging~~ ✅
- ~~Market hours awareness — skip IBKR calls when market is closed (Mon-Fri 9:30-16:00 ET)~~ ✅
- ~~Holiday calendar — skip polling on market holidays~~ ✅ (`9a58e60`)
- Paper trading mode — bracket order submission code written (`f3ed895`) but not yet tested with live IBKR connection
- ~~Split-exit as native order strategy (bracket orders with two profit targets)~~ ✅ (`41b4df3`) — each position split into T1 (entry×1.02) + T2 (original target) halves
- Move T2 stop to breakeven after T1 fills — requires real-time order monitoring loop
- Position sizing based on account equity and per-trade risk (`MAX_RISK_PERCENT`)
- Real-time P&L tracking and stop-loss/take-profit order management

### Sentiment Analysis
- ~~Phase 1: Use AlphaVantage News & Sentiments endpoint for top candidates (post-scoring)~~ ✅
  - ~~Pull `ticker_sentiment_score` and `relevance_score` per article~~ ✅
  - ~~Display as advisory column in HTML/email/arcade reports~~ ✅
- Phase 2: Evaluate whether sentiment signal correlates with outcomes over several weeks
  - Log sentiment scores alongside backtest results for comparison
  - Consider weighting sentiment more heavily for baseline/trend-following than mean reversion (oversold names often have bad news by definition)
- Phase 3 (only if Phase 2 shows value): Explore LLM-based enrichment for nuanced reads
  - High cost/latency per call — only justified if structured sentiment proves insufficient
  - Non-deterministic output makes backtesting difficult; would need caching/snapshotting

### Track Record / Signal Journal
- ~~Layer A: Immutable signal freeze — capture all signals with full context at prediction time~~ ✅
  - ~~`journal_batches` collection: date, git commit, algorithm version, market regime, config snapshot~~
  - ~~`journal_signals` collection: entry/stop/T1/T2, ML prob, components, sentiment, rank~~
  - ~~Insert-only with unique indexes, non-blocking, auto-triggered on every `-p` run~~
- Layer B: Hypothetical trade engine — auto-evaluate signal outcomes after hold period
  - Run automatically N days after each batch (e.g. cron or post-prediction check for mature batches)
  - For each signal: was entry hit? Stop hit first? Target hit? Time exit?
  - Track max adverse excursion (MAE), max favorable excursion (MFE), holding days
  - Store in `journal_hypothetical_trades` collection
  - Compute: win rate, avg win/loss, expectancy, profit factor, Sharpe, Sortino, max drawdown
  - Include SPY benchmark comparison for the same period
- Layer C: Real execution journal — immutable record of what you did with real money
  - **`journal_capital_snapshots`** — daily equity state (one record per trading day)
    - `date`, `total_equity`, `cash_available`, `positions_value`, `margin_used`
    - `open_position_count`, `max_positions_allowed`
    - `daily_pnl`, `daily_pnl_pct`, `cumulative_pnl`, `cumulative_pnl_pct`
    - `spy_close` (benchmark reference for same day)
    - `notes` (manual annotation: "added $5k capital", "withdrew $2k", etc.)
    - Unique index on `date` — one snapshot per day, append-only
  - **`journal_executed_trades`** — one record per real trade, linked to signal
    - `batch_date`, `symbol`, `strategy` — FK to signal (or null if discretionary)
    - `signal_rank` — what rank was this signal when BH recommended it?
    - `decision`: "followed" | "skipped" | "partial" | "discretionary"
    - `skip_reason`: null | "low conviction" | "sector concentration" | "capital limit" | "emotional" | custom
    - Entry: `actual_entry_price`, `entry_date`, `entry_time`, `shares`, `capital_allocated`
    - Exit: `actual_exit_price`, `exit_date`, `exit_time`, `exit_type` ("t1" | "t2" | "stop" | "time" | "manual")
    - Split-exit tracking: `t1_filled` (bool), `t1_fill_price`, `t1_fill_date`, `t2_exit_type`, `t2_exit_price`
    - Costs: `commission`, `fees`, `slippage_vs_signal_entry` (actual - recommended, in bps)
    - Returns: `gross_return_pct`, `net_return_pct` (after fees), `dollar_pnl`
    - Excursions: `max_adverse_excursion_pct`, `max_favorable_excursion_pct`
    - `holding_days`, `risk_at_entry_pct` (distance to stop as % of entry)
    - Unique index on `(batch_date, symbol, strategy)` — append-only
  - **`journal_skipped_signals`** — signals BH recommended but you chose not to trade
    - `batch_date`, `symbol`, `strategy`, `signal_rank`, `composite_score`, `ml_win_probability`
    - `skip_reason`, `skip_date`
    - Enables "what did I leave on the table?" analysis — compare skipped signal outcomes vs taken
  - **Behavioral analytics** (derived from the above)
    - Signal adherence rate: % of top-N signals actually traded
    - Override impact: P&L of skipped signals vs traded signals
    - Slippage profile: avg entry slippage by signal strength tier
    - Position sizing discipline: actual allocation vs recommended
    - Holding discipline: avg actual hold vs recommended hold period
    - Emotional override frequency and cost — the "discipline tax"
  - **Monthly capital statement** (auto-generated, investor-facing)
    - Opening equity, deposits/withdrawals, closing equity
    - Gross return, net return (after all costs), benchmark return (SPY)
    - Number of trades, win rate, avg win, avg loss, profit factor
    - Max drawdown during month, longest losing streak
    - Top 3 winners and top 3 losers with brief context
    - Model adherence score: how closely you followed BH's signals
- Portfolio-level metrics dashboard (auto-computed weekly)
  - CAGR, monthly returns, win rate, expectancy, profit factor
  - Sharpe, Sortino, Ulcer index, max drawdown (absolute + rolling 30-day)
  - Capital utilization, avg liquidity of picks, slippage sensitivity
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
- Full historical backfill — backfill all ~6,000 symbols going back 20 years (full Alpha Vantage history). Currently only recent data is loaded for most symbols. Deep history improves ML training, long-range backtesting, and indicator calculations that depend on long lookback periods (200-day EMA, etc.). Will need to run in batches respecting API rate limits (`-b --resume --limit N`). SPY + QQQ already backfilled to 2000.
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
