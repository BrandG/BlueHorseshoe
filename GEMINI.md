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

- **Baseline Optimization (Jan 2026):**
    - **Entry Logic:** Switch to "Buy at Last Close" (Market Buy) for high-momentum setups (Green Candle, High Vol, RSI < 70) to ensure fills on runaway trends.
    - **Safety Filter:** Implemented `_is_dead_or_flat` (ATR < 0.5% or StdDev < 0.2%) to reject pinned stocks or buyouts.
    - **Performance:** Validated on historical data (YPF +11%, OXM +6% with new logic).

- **Mean Reversion:**
    - **Status:** Highly effective on volatile names (RDFN +23%).
    - **Scoring:** Rewards extreme oversold conditions (RSI < 30) with significant mean reversion potential.

## Developer Notes

- **Testing:** Ensure `base_data` fixtures in tests include price volatility to bypass the "Dead Stock" filter.
- **Reporting:** `ReportSingleton` now prints to console and writes to `src/logs/report.txt`.
- **Validation:** When adding new technical scoring logic, ensure column presence checks use `Series.index` to avoid value-based subsetting errors.
- **Logging:** Always update `actions.txt` with key decisions and validation results.

- **Next Task:** Re-run feature engineering on the full historical dataset using the new `ml_utils` and begin deep backtesting.
