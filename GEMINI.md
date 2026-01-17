# BlueHorseshoe - Project Guidelines

## Overview
BlueHorseshoe is a quantitative trading and analysis system built in Python. It focuses on swing-trading strategies using technical indicators, backtesting historical data, and generating predictive reports.

## Core Operational Mandate
**CRITICAL:** All Python execution and testing MUST be performed through the project's Docker container.
- **Main Command:** `docker exec bluehorseshoe python src/main.py [args]`
- **Testing Command:** `docker exec bluehorseshoe pytest [path_to_test]`
- **Linting Command:** `docker exec bluehorseshoe ./lint.sh`
- **Temporary Files:** Use `/root/.gemini/tmp/` or the project's `src/logs/` directory for output logs.

## Technology Stack
- **Language:** Python 3.12
- **Database:** MongoDB 7 (Container: `mongo`)
- **Analysis:** TA-Lib, NumPy, Pandas, Scikit-learn
- **Server/API:** Uvicorn/FastAPI
- **Containerization:** Docker & Docker Compose

## CLI Interface (`src/main.py`)
| Flag | Description |
|------|-------------|
| `-u` | Update recent historical data (recent symbols). |
| `-b` | Build/Backfill full historical data for all symbols. |
| `-p` | Predict potential entry/exit points for the next trading day. |
| `-r` | Regenerate a report from a specific date's saved scores. |
| `-t` | Run backtest (requires date: `-t 2025-12-01`). |
| `-o` | Optimize indicator weights based on historical performance. |
| `-i` | Check intraday status of a trade (requires yfinance): `-i SYMBOL ENTRY STOP TARGET`. |
| `-d` | Run internal debug routines (`debug_test` function). |

## Analysis Philosophies
The system implements two primary scoring strategies in `TechnicalAnalyzer`:
1. **Baseline (Trend-Following):** Rewards momentum, strength, and confirmed breakouts. Penalizes overextension.
2. **Mean Reversion (Dip Buying):** Rewards oversold conditions (RSI < 30, Price < BB Lower) and potential exhaustion reversals.

## Project Structure
- `src/bluehorseshoe/analysis/`: Strategy logic, indicators, backtesting, and weight optimization.
- `src/bluehorseshoe/core/`: Database connections, global state, and configuration.
- `src/bluehorseshoe/data/`: Market API integrations and historical data management.
- `src/bluehorseshoe/reporting/`: Generation of performance reports and trading candidates.
- `src/tests/`: Comprehensive test suite for technical scenarios and indicators.

## Concurrency & Rate Limiting
- **API Calls:** Market data API calls (AlphaVantage) are rate-limited via decorators. To ensure the rate limiter state is shared across workers, **`ThreadPoolExecutor` MUST be used** instead of `ProcessPoolExecutor`.
- **Performance:** CPU-bound tasks (like indicator calculations) can still benefit from multiprocessing, but IO-bound API loops require threading to stay within CPS limits.

## API Configuration
- **CPS (Calls Per Second):** Controlled by `ALPHAVANTAGE_CPS` in `docker/.env`.
- **Stable Rate:** A rate of 2 CPS is currently standard to avoid "Minute-level rate limit" errors from AlphaVantage.
- **Applying Changes:** After modifying `.env`, containers must be restarted: `cd docker && docker compose up -d`.

## Analysis & Scoring Notes

- **Market Regime Filter (Jan 2026):** Implemented a robust market health check (`MarketRegime`) using SPY/QQQ price action against key EMAs (20, 50, 200) and market breadth.
    - **Update (Jan 16):** The regime filter is now advisory. Baseline (Trend) signals are generated even in Bearish regimes (if they meet strict trend criteria) to capture potential reversals or outliers.
- **Mean Reversion:**
    - **Status:** Validated (Jan 2026).
    - **Performance:** 53% Win Rate, +6.5% PnL in Bear/Chop markets.
    - **Scoring:** Rewards extreme oversold conditions (RSI < 30) with significant mean reversion potential. Effective on volatile names.

- **Async Architecture (Jan 2026):** Transitioned heavy analysis workloads to Celery/Redis background tasks. The API now returns a `task_id` for long-running predictions, and a `/tasks/{task_id}` endpoint provides real-time progress updates.

## Developer Notes

- **Data Integrity:** Index ETFs (SPY, QQQ) require a full backfill (`-b --symbols SPY`) to ensure enough data (>200 days) for market regime analysis. The standard update (`-u`) only fetches the most recent 100 data points.
- **Testing:** Ensure `base_data` fixtures in tests include price volatility to bypass the "Dead Stock" filter.
- **Reporting:** `ReportSingleton` now prints to console and writes to `src/logs/report.txt`.
- **Validation:** When adding new technical scoring logic, ensure column presence checks use `Series.index` to avoid value-based subsetting errors.
- **Logging:** Always update `actions.txt` with key decisions and validation results.

- **Next Task:** Refactor `ReportSingleton` to output structured JSON data for the API and Dashboard.