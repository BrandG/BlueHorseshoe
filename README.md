# BlueHorseshoe

BlueHorseshoe is a quantitative trading and analysis system built in Python. It focuses on swing-trading strategies using technical indicators, backtesting historical data, and generating predictive reports.

## Overview

The system implements two primary scoring strategies:
1.  **Baseline (Trend-Following):** Rewards momentum, strength, and confirmed breakouts while penalizing overextension.
2.  **Mean Reversion (Dip Buying):** Rewards oversold conditions (e.g., RSI < 30, Price < Bollinger Band Lower) and potential exhaustion reversals.

## Technology Stack

-   **Language:** Python 3.12
-   **Database:** MongoDB 7
-   **Task Queue:** Celery with Redis
-   **Analysis:** TA-Lib, NumPy, Pandas, Scikit-learn
-   **Server/API:** Uvicorn/FastAPI
-   **Containerization:** Docker & Docker Compose

## Quick Start

The entire system is containerized. Ensure you have Docker and Docker Compose installed.

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd BlueHorseshoe
    ```

2.  **Configure Environment:**
    Copy `.env.example` to `docker/.env` and populate it with your API keys (AlphaVantage) and configuration.
    ```bash
    cp .env.example docker/.env
    # Edit docker/.env
    ```

3.  **Start Services:**
    ```bash
    cd docker
    docker compose up -d
    ```

## Usage

All Python execution is performed through the `bluehorseshoe` container.

**Main Command Wrapper:**
```bash
docker exec bluehorseshoe python src/main.py [flags]
```

### CLI Commands

| Flag | Description | Example |
|------|-------------|---------|
| `-u` | **Update** recent historical data for tracked symbols. | `... -u` |
| `-b` | **Backfill** full historical data for all symbols. | `... -b` |
| `-p` | **Predict** potential entry/exit points for the next trading day. | `... -p` |
| `-r` | **Regenerate** a report from a specific date's saved scores. | `... -r 2026-01-20` |
| `-t` | **Backtest** strategies over a historical range. | `... -t 2025-12-01 --end 2026-01-01` |
| `-i` | **Intraday** check for a specific trade (requires yfinance). | `... -i SYMBOL ENTRY STOP TARGET` |
| `-d` | **Debug** run internal test routines. | `... -d` |

### Common Workflows

*   **Daily Update & Report:**
    ```bash
    docker exec bluehorseshoe python src/main.py -u
    docker exec bluehorseshoe python src/main.py -p
    ```

*   **Run Backtest:**
    ```bash
    docker exec bluehorseshoe python src/main.py -t 2025-06-01 --end 2025-12-31 --strategy baseline
    ```

## Project Structure

*   `src/bluehorseshoe/analysis/`: Strategy logic, indicators, backtesting, and weight optimization.
*   `src/bluehorseshoe/core/`: Database connections, global state, and configuration.
*   `src/bluehorseshoe/data/`: Market API integrations and historical data management.
*   `src/bluehorseshoe/reporting/`: Generation of performance reports and trading candidates.
*   `docker/`: Docker configuration and environment files.

## Developer Notes

*   **Testing:** Run tests using `docker exec bluehorseshoe pytest`.
*   **Linting:** Run `docker exec bluehorseshoe ./lint.sh` to enforce code quality.
*   **Logs:** Logs are written to `src/logs/`.