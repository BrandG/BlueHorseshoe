# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Critical Execution Requirements

**Python runs directly on the host via a venv (not in a Docker container):**

```bash
# Execute main CLI
./run.sh python src/main.py [args]

# Run tests
./run.sh pytest [path]

# Run specific test
./run.sh pytest src/tests/test_name.py::test_function

# Lint code
./run.sh ./lint.sh

# Or activate the venv manually:
source .venv/bin/activate && PYTHONPATH=src python src/main.py [args]

# Infrastructure containers (MongoDB, IBKR Gateway)
cd docker && docker compose up -d    # Start infra containers
cd docker && docker compose down     # Stop infra containers
```

## Process Safety

**NEVER interrupt, kill, or run concurrent heavy processes alongside the daily update (`-u`) or prediction (`-p`) pipeline.** These are critical production workflows that can take 30-60+ minutes. Running memory-intensive scripts (analysis, backtests, etc.) concurrently will OOM-kill the process and corrupt the run. Always wait for `-u` and `-p` to finish before starting other work. Check with `pgrep -f "main.py"` if unsure.

## Git Operations Policy

**CRITICAL:** Never perform Git operations (`add`, `commit`, `push`) without explicit user confirmation for each step. If asked "what time it is, do not start building a clock" - do not execute large-scale changes or start complex implementations without user approval.

## Project Overview

BlueHorseshoe is a quantitative swing trading system that:
1. Fetches and stores historical stock data from Alpha Vantage API
2. Calculates 40+ technical indicators across 6 categories (momentum, trend, volume, moving averages, candlestick patterns, pivots)
3. Generates trading signals using two strategies: **Baseline (Trend-Following)** and **Mean Reversion**
4. Provides ML-enhanced win probability predictions and dynamic stop-loss recommendations
5. Backtests strategies against historical data
6. Generates HTML reports with top trading candidates

## Technology Stack

- **Language:** Python 3.12
- **Database:** DuckDB (OHLCV time-series storage), MongoDB 7 (scores, journal, overviews, symbols, news)
- **API:** FastAPI + Uvicorn (systemd service on port 8001)
- **Analysis:** TA-Lib, pandas_ta, NumPy, Pandas, Scikit-learn
- **Infrastructure:** MongoDB and IBKR Gateway run in Docker containers; Python runs natively on the host via venv

## Architecture Overview

### Core Components

**`src/main.py`** - CLI entry point with flag-based commands:
- `-u`: Update recent historical data (last 100 datapoints)
- `-b`: Backfill full historical data (use `--resume`, `--limit N`, `--symbols SPY,QQQ`)
- `-p [DATE]`: Predict trading candidates for target date (defaults to latest market date). If `PAPER_TRADING_ENABLED=true`, also submits bracket orders to IBKR paper account.
- `-r [DATE]`: Regenerate report from saved scores
- `-t DATE`: Run backtest (use `--end DATE --interval 7` for range, `--strategy baseline|mean_reversion`)
- `-o`: Optimize indicator weights using historical performance
- `-i SYMBOL ENTRY STOP TARGET`: Check intraday trade status (requires yfinance)
- `-d`: Run debug routines

**`src/bluehorseshoe/analysis/`** - Trading strategy logic:
- `strategy.py`: `SwingTrader` class orchestrates prediction pipeline
- `technical_analyzer.py`: `TechnicalAnalyzer` calculates scores for both strategies
- `backtest.py`: `Backtester` simulates trades with configurable params (target profit, stop loss, hold days, trailing stops)
- `optimizer.py`: `WeightOptimizer` tunes indicator weights via grid search
- `market_regime.py`: `MarketRegime` analyzes SPY/QQQ health (EMAs, breadth) - now advisory only
- `ml_overlay.py`: `MLInference` predicts win probability using XGBoost
- `ml_stop_loss.py`: `StopLossInference` recommends dynamic stop-loss levels
- `indicators/`: 40+ indicators organized by category (momentum, trend, volume, moving averages, candlestick, limits)

**`src/bluehorseshoe/core/`** - Infrastructure:
- `database.py`: MongoDB connection management
- `config.py`: Settings via Pydantic (loads from env vars and `weights.json`). Exports `REPO_ROOT` for path derivation.
- `scores.py`: `ScoreManager` persists daily scores to MongoDB
- `symbols.py`: Symbol list management (NASDAQ stocks)
- `container.py`: Dependency injection container for API/CLI contexts
- `service.py`: Shared utilities (market date calculations, data loading)

**`src/bluehorseshoe/data/`** - Data ingestion:
- `historical_data.py`: Fetches OHLCV data from Alpha Vantage with rate limiting (respects `ALPHAVANTAGE_CPS`)
- `duckdb_store.py`: `DuckDBStore` — embedded columnar storage for OHLCV time-series data (replaces MongoDB for reads)

**`src/bluehorseshoe/api/`** - FastAPI server:
- `main.py`: FastAPI app with lifespan management (DI container)
- `routes.py`: Endpoints for predictions, backtests, scores
- `tasks.py`: Background task functions for async processing

**`src/bluehorseshoe/reporting/`** - Report generation:
- `html_reporter.py`: `HTMLReporter` generates interactive HTML reports with charts
- `report_generator.py`: `ReportWriter` handles console/file logging

**`src/bluehorseshoe/trading/`** - Order execution:
- `paper_trader.py`: `PaperTrader` submits bracket orders (entry + take-profit + stop-loss) to IBKR paper account after prediction. `max_positions` is "have at most N on the book," not "submit N per run" — pre-flight broker occupancy check before sizing, fails closed on unreachable gateway.

**`src/bh_swing/`** - Post-trade management for BH Equity bracket orders (parallel to `bluehorseshoe/`, deliberately not co-mingled):
- `bh_swing_monitor.py` (entrypoint): runs every 5 min from cron during US market hours. Snapshots broker state, reconciles fills into journal, optionally manages stops. Flags: `--manage-dry-run` (Phase 1a, journals `would_*` events without mutating) and `--manage` (Phase 1b, live `modify_order_stop` calls). Uses dedicated `client_id=7` to avoid colliding with PaperTrader's `client_id=1`.
- `analysis/position_state.py`: merges broker truth (`get_positions()` + `get_open_trades()`) with Mongo `trade_orders` metadata. Synthesizes a `Filled` `BrokerOrderView` for entry orders that are missing from `reqAllOpenOrders()` but where the broker still holds the position — inference is "if Mongo said we submitted X, X is gone from open orders, and we hold the position, X filled" (cancellation would leave qty=0).
- `analysis/stop_rules.py`: pure-logic stop advancement. Current rule: `BREAKEVEN` (move T2 stop to entry once T1 has fully filled). Early-exit hook stubbed (Phase 1c, disabled by default).
- `trading/safety.py`: gates composed before any broker-mutating call — `stop_move_is_tightening` (strongest invariant; widening is structurally refused), `actions_under_rate_limit` (default 15 mutations/tick), `position_count_under_cap` (diagnostic-only for this orchestrator's risk-reducing actions; entry-side flows still halt on it), `kill_switch_inactive` (sentinel file at `.bh_swing_pause_management`).
- `trading/manager.py`: orchestrator — pulls broker state, asks `stop_rules` what to do, runs proposals through `safety` gates, mutates (live) or emits `would_*` events (dry-run). Every decision lands in `src/logs/bh_swing_journal.csv`.
- `trading/reconciler.py`: snapshot the broker, append `fill_detected` rows. `is_broker_reachable(account)` is the cheap signal for "gateway actually answered" vs "got a stub of zeros."
- Operator tools: `src/bh_swing_status.py` (read-only dashboard), `src/bh_swing_flatten.py` (`--execute` flattens positions when something needs manual intervention).
- Watchdog: `run_ibgw_watchdog.sh` cronned at `1-59/5 * * * *` — probes Java's listener inside the container via `docker exec` (host-side `nc -z 4004` is misleading because socat keeps accepting after Java dies). Force-recreates the gateway on a confirmed wedge, with a 15-min cooldown.

### Data Flow

1. **Data Ingestion** (`-u` or `-b`): `historical_data.py` fetches OHLCV from providers → stores in DuckDB (`data/ohlcv.duckdb`)
2. **Prediction** (`-p`): `SwingTrader.swing_predict()` →
   - Loads historical data for all symbols from DuckDB (primary) with file/net fallback
   - Checks market regime (advisory)
   - For each symbol: `TechnicalAnalyzer` calculates baseline/mean reversion scores
   - Filters by price ($5-$500), volume (>100k avg), risk/reward ratio (>1.0)
   - ML models predict win probability and stop-loss
   - Saves scores to MongoDB (`scores` collection)
   - Generates HTML report with top 50 candidates
   - If `PAPER_TRADING_ENABLED=true`: `PaperTrader` submits bracket orders for top N candidates to IBKR paper account
3. **Backtest** (`-t`): `Backtester.run_backtest()` →
   - Loads saved scores for target date
   - Simulates trades using next-day OHLCV data
   - Tracks outcomes (win/loss/timeout) and calculates P&L
   - Logs results to `src/logs/backtest_log.csv`

### Strategy Philosophies

**Baseline (Trend-Following):**
- Rewards: Strong trends (ADX), momentum (RSI 40-70, MACD bullish), breakouts (Donchian, SuperTrend), bullish candles
- Penalizes: Overextension (RSI >70, BB >85%), weak volume, death cross
- Target: Catch established uptrends with confirmation

**Mean Reversion:**
- Rewards: Oversold conditions (RSI <30, Williams %R <-80, CCI <-200), price below BB lower band, distance from MA, reversal candles
- Penalizes: Continued downtrends, low volume
- Target: Dip buying on quality names showing exhaustion

### Indicator Weights

Weights are stored in `src/weights.json` and loaded via `config.py`. Categories: `trend`, `momentum`, `volume`, `candlestick`, `mean_reversion`. Each indicator has a multiplier (default 1.0) that scales its score contribution. Use `-o` to optimize weights based on backtest performance.

## Configuration

**Environment Variables** (set in `.env` at repo root, and `docker/.env` for container overrides):
- `ALPHAVANTAGE_KEY`: API key for market data
- `ALPHAVANTAGE_CPS`: Rate limit (calls per second) - use 2 to avoid rate limit errors
- `MONGO_URI`: MongoDB connection string (default: `mongodb://127.0.0.1:27017`)
- `MONGO_DB`: Database name (default: `bluehorseshoe`)
- `DUCKDB_PATH`: Path to DuckDB file for OHLCV storage (auto-derived from `REPO_ROOT`)
- `NASDAQ_DATA_LINK_API_KEY`: API key for AAII sentiment data from Nasdaq Data Link (optional, falls back to Excel download)
- Email settings for notifications (SMTP_SERVER, SMTP_USER, SMTP_PASSWORD, EMAIL_RECIPIENT)
- `PAPER_TRADING_ENABLED`: Enable automatic bracket order submission after prediction (default: `false`)
- `PAPER_TOTAL_INVESTMENT`: Total capital to deploy across positions (default: `10000`)
- `PAPER_MAX_POSITIONS`: Maximum simultaneous positions / top N candidates (default: `10`)
- `IBKR_READ_ONLY`: Controls IB Gateway read-only mode (set to `not` to enable order placement, default: `yes`)

**Path auto-detection:** All file paths are derived from `REPO_ROOT` in `config.py` (computed from the file's location). No hardcoded paths — works identically on any host.

## Important Constants

**From `src/bluehorseshoe/analysis/constants.py`:**
- `MIN_STOCK_PRICE = 5.0`, `MAX_STOCK_PRICE = 500.0`: Price filters
- `MIN_RR_RATIO_BASELINE = 1.0`, `MIN_RR_RATIO_MEAN_REVERSION = 1.0`: Minimum risk/reward ratio
- `MAX_RISK_PERCENT = 0.05`: Maximum risk per trade (5% from entry to stop)
- `REQUIRE_WEEKLY_UPTREND = False`: Disabled to increase candidate volume
- `ATR_WINDOW = 14`: ATR calculation window for stop-loss

## Testing

**Run all tests:** `./run.sh pytest`
**Run specific test:** `./run.sh pytest src/tests/test_swing_trading.py -v`
**Coverage:** `./run.sh pytest --cov=bluehorseshoe --cov-report=html`

Test fixtures in `test_*.py` files include:
- `base_data`: Sample OHLCV DataFrame with sufficient volatility to bypass "Dead Stock" filter
- Mocked MongoDB connections for unit tests
- Integration tests for full prediction pipeline

## API Usage

**Managed by systemd:** `systemctl start|stop|restart bluehorseshoe-api` (runs on port 8001)
**Endpoints:**
- `POST /api/v1/predict`: Trigger async prediction (returns task_id)
- `GET /api/v1/tasks/{task_id}`: Check task progress
- `GET /api/v1/scores/{date}`: Fetch saved scores
- `POST /api/v1/backtest`: Run async backtest

## Common Pitfalls

1. **Rate Limiting:** AlphaVantage enforces minute-level limits. Use `ALPHAVANTAGE_CPS=2` and ThreadPoolExecutor (NOT ProcessPoolExecutor) to share rate limiter state.
2. **Market Regime Data:** Index ETFs (SPY, QQQ) need full backfill (`-b --symbols SPY,QQQ`) to ensure 200+ days for EMA calculations. Standard `-u` only fetches 100 days.
3. **Test Data:** Ensure fixtures have price volatility (high-low range >1%) to avoid "Dead Stock" filter false positives.
4. **Column Checks:** When adding indicators, use `Series.index` for column presence checks to avoid value-based subsetting errors.
5. **Dependency Injection:** New code should use injected `database`, `config`, `report_writer`, `store` instead of global singletons. CLI context manager (`create_cli_context()`) handles cleanup. Use `ctx.store` for OHLCV reads.
6. **DuckDB is the sole OHLCV store.** MongoDB `historical_prices` and `historical_prices_recent` collections are no longer read from or written to. All OHLCV operations use `DuckDBStore` via `ctx.store`.
7. **IB Gateway wedge probe.** Host-side `nc -z 127.0.0.1 4004` is misleading after a daily-disconnect wedge — socat inside the container keeps accepting TCP even after the Java listener dies. To detect a wedge, `docker exec` into the container and probe `127.0.0.1:4002` with a timeout. Watchdog in `run_ibgw_watchdog.sh` does this correctly; don't reinvent host-side TCP probes.
8. **`reqAllOpenOrders()` drops filled orders.** Once an entry fills, IBKR no longer returns it. `BracketLeg.entry_filled` infers fill from "entry order_id is gone from open_trades AND broker_position_qty != 0" — see `_assign_legs_to_views` in `bh_swing/analysis/position_state.py`. Don't add code that assumes a filled order will still appear in the open-orders snapshot.

## Development Workflow

1. Make code changes (code is at `/root/BlueHorseshoe`)
2. Test: `./run.sh pytest src/tests/test_file.py`
3. Lint: `./run.sh ./lint.sh`
4. Run prediction: `./run.sh python src/main.py -p`
5. Check logs: `src/logs/blueHorseshoe.log`, `src/logs/report.txt`, `src/logs/backtest_log.csv`
6. View reports: `src/graphs/report_YYYY-MM-DD.html`

## Key Files

- **Main Entry:** `src/main.py`
- **Strategy Core:** `src/bluehorseshoe/analysis/strategy.py`
- **OHLCV Store:** `src/bluehorseshoe/data/duckdb_store.py` (DuckDB backend)
- **OHLCV Data:** `data/ohlcv.duckdb` (not checked into git)
- **Indicator Config:** `src/weights.json`
- **Host Environment:** `.env` (repo root)
- **Docker Environment:** `docker/.env` (container overrides for MongoDB/IBKR DNS)
- **Python Wrapper:** `run.sh` (activates venv, sets PYTHONPATH)
- **Logs:** `src/logs/` directory
- **Reports:** `src/graphs/` directory
- **Docker Config:** `docker/docker-compose.yml` (MongoDB, paper IBKR Gateway on 4004, live read-only IBKR Gateway on 4011)
- **BH Swing journal:** `src/logs/bh_swing_journal.csv` (per-tick events from `bh_swing_monitor`)
- **BH Swing tracker:** `src/graphs/swing_tracker.html` (rendered each tick)
- **Watchdog log:** `src/logs/ibgw_watchdog.log` (silent on healthy days)

## gstack
Use /browse from gstack for all web browsing.
Available skills: /office-hours, /plan-ceo-review, /plan-eng-review, /plan-design-review,
/design-consultation, /review, /ship, /browse, /qa, /qa-only, /design-review,
/setup-browser-cookies, /retro, /investigate, /document-release, /codex, /careful,
/freeze, /guard, /unfreeze, /gstack-upgrade.
