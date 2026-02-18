# TO-DO

## Near Term

### Split-Exit Strategy Validation
- Run split-exit vs single-exit comparison across a date range (e.g. 2025-08-01 to 2026-02-07)
- Compare Plan A (`fixed_pct`) and Plan B (`atr_tiered`) against baseline single-exit
- Tune T1 target (try 1.5%, 2%, 2.5%, 3%) and measure impact on blended P&L and win rate
- Decide whether split-exit should become the default backtest mode

### LOO Weight Tuning
- Review LOO analysis results once the large run completes (`src/logs/loo_analysis_2026-02-18.csv`)
- Apply suggested weight changes to `src/weights.json` for indicators with strong P&L deltas
- Re-run backtest to validate improvements before/after weight changes

### Fix Pre-Existing Test Failures
- `test_calculate_wma` / `test_calculate_vwma` — tests expect Series, implementation returns float
- `test_calculate_score` (volume) — expected Score(0,0) but VWAP/Force Index now contribute non-zero scores

## Medium Term

### IBKR Integration
- Research IBKR API (TWS API / ib_insync) for order placement and account data
- Paper trading mode first — submit orders from prediction output, track fills
- Position sizing based on account equity and per-trade risk (`MAX_RISK_PERCENT`)
- Real-time P&L tracking and stop-loss/take-profit order management
- Consider split-exit as native order strategy (bracket orders with two profit targets)

### Backtest Realism
- Add commission modeling to `BacktestConfig` (e.g. `commission_pct` applied on entry and exit)
- Add spread/slippage modeling beyond current gap logic (configurable `avg_spread_bps`)
- Portfolio-level backtesting — simulate running top N picks simultaneously with fixed capital allocation
- Track max drawdown, Sharpe ratio, and other portfolio-level metrics

### Data & Infrastructure
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
