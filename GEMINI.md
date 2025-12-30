# BlueHorseshoe - Project Guidelines

## Overview
BlueHorseshoe is a quantitative trading and analysis system built in Python. It focuses on swing-trading strategies using technical indicators, backtesting historical data, and generating predictive reports.

## Core Operational Mandate
**CRITICAL:** All Python execution and testing MUST be performed through the project's Docker container.
- **Main Command:** `docker exec bluehorseshoe python src/main.py [args]`
- **Testing Command:** `docker exec bluehorseshoe pytest [path_to_test]`
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
- **Baseline Strategy:** Includes momentum and breakout logic, but has been enhanced to also reward **oversold entry signals** (e.g., RSI < 30) when a trend is establishing.
- **Data Integrity:** Strategy scoring requires at least 2 days of historical data to compare "current" vs "previous" states (prevents `KeyError`). Symbols with very short histories (e.g., < 14 days) may still cause index errors in indicators like RSI.
- **Backtesting Performance:** A 6-month weekly backtest (approx. 30 dates) takes ~75 minutes to complete.
- **Data Requirements:** Symbols with < 30 days of history may trigger `IndexError` during indicator calculation (specifically RSI/ATR). Future runs should filter these out during the batch loading phase.

## Developer Notes
- Adhere to the scoring constants defined in `src/bluehorseshoe/analysis/constants.py`.
- New indicators should be modularized within `src/bluehorseshoe/analysis/indicators/`.
- Always verify changes using `src/tests/test_technical_scenarios.py` to ensure strategy logic remains consistent.
- **Workflow:** For a fresh report, typically run `src/main.py -u` followed by `src/main.py -p`.