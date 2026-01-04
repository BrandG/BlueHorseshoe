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

- **Indicator Testing Infrastructure:** A new script `src/run_indicator_analysis.py` allows for 6-month backtests of individual or combined indicators using the `--indicators` flag (e.g., `momentum:macd,momentum:rsi`).

- **Aggregation Models:** Added support for both `sum` (additive) and `product` (convergence) scoring in `TechnicalAnalyzer`. Convergence currently requires very precise timing and may need further threshold relaxation.

- **Baseline Strategy:** Currently undergoing single-factor analysis to optimize weights.

- **MACD Performance:** MACD alone showed a ~61% win rate and ~34% cumulative PnL over the H2 2025 period.

- **RSI Tweak:** RSI scoring was moved from neutral (45-65) to oversold (<50) to better capture "buying the dip" in established trends.



## Developer Notes

- **Granular Indicators:** All indicator groups now support sub-indicator filtering in their `get_score` methods.

- **Reporting:** `ReportSingleton` now prints to console and writes to `src/logs/report.txt`.

- **Validation:** When adding new technical scoring logic, ensure column presence checks use `Series.index` to avoid value-based subsetting errors.

- **Logging:** When decisions are made, like a new indicator, strategy, or revision, always append an entry to the file `actions.txt` that is a line or two, so that it will be easy when we start a new session, to pick up where the previous session left off. When a session begins, tail the last ten lines from `actions.txt` so that we can begin with a known history of actions taken.

- **ML Win Prediction:** Strategy-specific models (Baseline vs. Mean Reversion) improved accuracy significantly. MR accuracy reached 78% with Beta and Sentiment as key features.

- **Next Task:** Implement a weekly automated retraining job for ML models using newly graded trades to ensure the system adapts to changing market regimes.
