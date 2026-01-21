# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Critical Execution Requirements

**ALL Python execution and testing MUST be performed through Docker containers:**

```bash
# Execute main CLI
docker exec bluehorseshoe python src/main.py [args]

# Run tests
docker exec bluehorseshoe pytest [path]

# Run specific test
docker exec bluehorseshoe pytest src/tests/test_name.py::test_function

# Lint code
docker exec bluehorseshoe ./lint.sh

# Container management
cd docker && docker compose up -d    # Start containers
cd docker && docker compose down     # Stop containers
cd docker && docker compose restart  # Restart after .env changes
```

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
- **Database:** MongoDB 7 (stores historical data and scores)
- **Task Queue:** Celery + Redis (async background jobs for API)
- **API:** FastAPI + Uvicorn
- **Analysis:** TA-Lib, pandas_ta, NumPy, Pandas, Scikit-learn
- **Containerization:** Docker + Docker Compose (4 containers: bluehorseshoe, mongo, redis, worker, beat)

## Architecture Overview

### Core Components

**`src/main.py`** - CLI entry point with flag-based commands:
- `-u`: Update recent historical data (last 100 datapoints)
- `-b`: Backfill full historical data (use `--resume`, `--limit N`, `--symbols SPY,QQQ`)
- `-p [DATE]`: Predict trading candidates for target date (defaults to latest market date)
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
- `config.py`: Settings via Pydantic (loads from env vars and `weights.json`)
- `scores.py`: `ScoreManager` persists daily scores to MongoDB
- `symbols.py`: Symbol list management (NASDAQ stocks)
- `container.py`: Dependency injection container for API/CLI contexts
- `service.py`: Shared utilities (market date calculations, data loading)

**`src/bluehorseshoe/data/`** - Data ingestion:
- `historical_data.py`: Fetches OHLCV data from Alpha Vantage with rate limiting (respects `ALPHAVANTAGE_CPS`)

**`src/bluehorseshoe/api/`** - FastAPI server:
- `main.py`: FastAPI app with lifespan management (DI container)
- `routes.py`: Endpoints for predictions, backtests, scores
- `tasks.py`: Celery tasks for async processing
- `celery_app.py`: Celery configuration

**`src/bluehorseshoe/reporting/`** - Report generation:
- `html_reporter.py`: `HTMLReporter` generates interactive HTML reports with charts
- `report_generator.py`: `ReportWriter` handles console/file logging

### Data Flow

1. **Data Ingestion** (`-u` or `-b`): `historical_data.py` fetches OHLCV from Alpha Vantage → stores in MongoDB (`daily_data` collection)
2. **Prediction** (`-p`): `SwingTrader.swing_predict()` →
   - Loads historical data for all symbols
   - Checks market regime (advisory)
   - For each symbol: `TechnicalAnalyzer` calculates baseline/mean reversion scores
   - Filters by price ($5-$500), volume (>100k avg), risk/reward ratio (>1.0)
   - ML models predict win probability and stop-loss
   - Saves scores to MongoDB (`scores` collection)
   - Generates HTML report with top 50 candidates
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

**Environment Variables** (set in `docker/.env`):
- `ALPHAVANTAGE_KEY`: API key for market data
- `ALPHAVANTAGE_CPS`: Rate limit (calls per second) - use 2 to avoid rate limit errors
- `MONGO_URI`: MongoDB connection string (default: `mongodb://mongo:27017`)
- `MONGO_DB`: Database name (default: `bluehorseshoe`)
- Email settings for notifications (SMTP_SERVER, SMTP_USER, SMTP_PASSWORD, EMAIL_RECIPIENT)

**After modifying `.env`:** Restart containers with `cd docker && docker compose up -d`

## Important Constants

**From `src/bluehorseshoe/analysis/constants.py`:**
- `MIN_STOCK_PRICE = 5.0`, `MAX_STOCK_PRICE = 500.0`: Price filters
- `MIN_RR_RATIO_BASELINE = 1.0`, `MIN_RR_RATIO_MEAN_REVERSION = 1.0`: Minimum risk/reward ratio
- `MAX_RISK_PERCENT = 0.05`: Maximum risk per trade (5% from entry to stop)
- `REQUIRE_WEEKLY_UPTREND = False`: Disabled to increase candidate volume
- `ATR_WINDOW = 14`: ATR calculation window for stop-loss

## Testing

**Run all tests:** `docker exec bluehorseshoe pytest`
**Run specific test:** `docker exec bluehorseshoe pytest src/tests/test_swing_trading.py -v`
**Coverage:** `docker exec bluehorseshoe pytest --cov=bluehorseshoe --cov-report=html`

Test fixtures in `test_*.py` files include:
- `base_data`: Sample OHLCV DataFrame with sufficient volatility to bypass "Dead Stock" filter
- Mocked MongoDB connections for unit tests
- Integration tests for full prediction pipeline

## API Usage

**Start API:** `docker compose up -d` (runs on port 8001)
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
5. **Dependency Injection:** New code should use injected `database`, `config`, `report_writer` instead of global singletons. CLI context manager (`create_cli_context()`) handles cleanup.

## Development Workflow

1. Make code changes locally (host volume mounted to `/workspaces/BlueHorseshoe`)
2. Test: `docker exec bluehorseshoe pytest src/tests/test_file.py`
3. Lint: `docker exec bluehorseshoe ./lint.sh`
4. Run prediction: `docker exec bluehorseshoe python src/main.py -p`
5. Check logs: `src/logs/blueHorseshoe.log`, `src/logs/report.txt`, `src/logs/backtest_log.csv`
6. View reports: `src/graphs/report_YYYY-MM-DD.html`

## Key Files

- **Main Entry:** `src/main.py`
- **Strategy Core:** `src/bluehorseshoe/analysis/strategy.py`
- **Indicator Config:** `src/weights.json`
- **Environment:** `docker/.env` (copy from `.env.example`)
- **Logs:** `src/logs/` directory
- **Reports:** `src/graphs/` directory
- **Docker Config:** `docker/docker-compose.yml`, `docker/Dockerfile.bluehorseshoe`
