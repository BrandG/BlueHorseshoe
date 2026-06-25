# TO-DO

> **Research reset 2026-06-25.** Research priorities/case-state (indicator teardown, BUD V2,
> sandbox, BH FTMO gate, weight optimization, hypothesis-engine, regime/ML/strategy expansion)
> were cleared with the `research/` purge. Full prior backlog recoverable via `git show HEAD:TODO.md`.
> Below = operational/engineering backlog only.

## Reporting
- ~~Holiday-aware exit warning banner~~ (done 2026-04-12) — Amber/neon banners on all three HTML report types when an NYSE holiday falls in the current week. Uses `pandas.tseries.holiday` via shared `market_calendar.py`. Banner uses the report's target date, not system clock.

## Architecture & Refactoring
- Event-driven backtest with an order book. Instead of "check high/low against levels," model it as: generate orders → feed daily bars → match orders → update positions. Naturally handles split exits, trailing stops, breakeven stops, shorts — all as order types rather than special-case code paths.
- **`src/bh_ftmo/main.py` Phase-0 stub refactor** — `main.py` is a Phase-0 copy of `bh_lite.py` that imports equity modules and references equity tickers, but is NOT pure dead code: three helpers are used by tests in `src/tests/test_bh_ftmo.py` (`_find_instrument_by_ftmo`, `check_position_health`, `_calculate_position_pnl`). Plan: extract `check_position_health` + `_calculate_position_pnl` to a clean module (`bh_ftmo/positions.py`), decide on `_find_instrument_by_ftmo`, drop the broken `main()`/equity imports/yfinance refs, update test imports, delete the stub. ~1 day, low priority.

## IBKR Integration
- Position sizing based on account equity and per-trade risk (`MAX_RISK_PERCENT`).
- Real-time P&L tracking and stop-loss/take-profit order management.

## Backtest Realism
- Add commission modeling to `BacktestConfig` (e.g. `commission_pct` applied on entry and exit).
- Add spread/slippage modeling beyond current gap logic (configurable `avg_spread_bps`).
- Portfolio-level backtesting — simulate running top N picks simultaneously with fixed capital allocation; track max drawdown, Sharpe, and other portfolio-level metrics.

## Security
- ~~Add MongoDB authentication~~ (done 2026-04-03) — User `bhapp` with readWrite on `bluehorseshoe`, `--auth` in docker-compose. Defense-in-depth alongside ufw + localhost bind.

## Data & Infrastructure
- **Migrate OHLCV storage from DuckDB to Parquet files** — DuckDB's single-writer file lock causes contention when multiple processes run concurrently (`-u` and `-p`, or orphaned ProcessPool workers). Two phases:
  1. **DuckDB read-only mode** — workers/readers open with `read_only=True`. Eliminates lock contention for one-writer-many-readers. Quick win.
  2. **Parquet file backend** — replace `DuckDBStore` with a `ParquetStore` on the same interface. Writes become atomic file swaps; reads never block. The 15 consumer files go through the store abstraction so downstream changes are minimal.
- Full historical backfill — backfill all ~6,000 active symbols going back 20 years (improves ML training, long-range backtesting, long-lookback indicators). Run in batches respecting API rate limits (`-b --resume --limit N`). SPY + QQQ already backfilled to 2000.
- Backfill overviews — ~2,000 symbols still missing overviews. Run `-u --refresh-overviews --ov-limit 500` in batches.
- Add post-prediction step to track symbols with stale/insufficient data → invalid symbols list, so they can be excluded or flagged for re-backfill.
- Upgrade yfinance from 0.2.25 to latest — Yahoo changed their API; old version can't parse responses. Raw API works; library is broken. Test upgrade impact on the Yahoo provider before deploying.
- Remove BH Python container from docker-compose — Python runs natively on host via venv; the container is still defined as a fallback. Remove after confirming host-based daily pipeline succeeds, then start the systemd API service (`systemctl start bluehorseshoe-api`).
- Suppress "Cannot write to a read-only DuckDBStore" warnings during `-p` — `save_historical_data()` in `historical_data.py:86` attempts opportunistic cache-writes that correctly fail in read-only mode. Check `store._read_only` before calling `save_symbol()`. Low priority — harmless.
- ~~Fix email delivery after Docker→host migration~~ (done) — Brevo SMTP credentials moved to root `.env`; `.env` sourcing added to `run.sh` and `run_daily_pipeline.sh`.

## Monitoring & Ops
- Dashboard for live system health (API rate limits, data freshness, model staleness).
- Alert on prediction pipeline failures or anomalous outputs.
- **BH FTMO cron outage monitoring** — email alert if the Friday NY-afternoon cron run is missing (open positions staying through weekend gaps is pure operational risk). Existing Brevo SMTP pipeline works for alerting.

## Tooling / Codex
- **Codex sandbox test-validation workaround** — Codex's command sandbox uses `--unshare-net`, blocking Docker network access, so MongoDB at `127.0.0.1:27017` is unreachable and any pytest hitting MongoDB fixtures fails with `Operation not permitted`. Options: (a) Brand runs pytest from his shell and supplies the count; (b) add `@pytest.mark.requires_mongo` markers so Codex runs `pytest -m "not requires_mongo"`; (c) reconfigure Codex's sandbox for Docker network access. Pick one before the next Next Action needing a test gate.
