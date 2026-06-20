# BlueHorseshoe Subsystems Guide

> **Naming note (2026-05-27):** the subsystems are now organized as two named
> products — **GORDON** (US equities: Engine = §1, Manager = §4) and **BUD**
> (forex/FTMO: Lab + Auto = §3, Briefing, Envelope). See
> [`PROJECTS.md`](PROJECTS.md) for the canonical map. This guide is the detailed
> *runbook*. Two known-stale spots below: **§2 `bh_lite` is retired** — its
> engine is dormant (see [`planning/BH_LITE_SUNDOWN.md`](planning/BH_LITE_SUNDOWN.md))
> and the live human-in-loop channel is now **`bh_briefing.py` / `bh_briefing_ftmo.py`**
> (Bud · Briefing); only `bh_lite_*.json` survives as the shared FTMO config
> envelope. The flag/output references in each section remain accurate.

This guide explains what each subsystem does, how it works, and how to run it.

| Sub-project | Asset class | Automation | Status |
|---|---|---|---|
| Original BH equity predictor | US equities | Research / signal generation | Production |
| bh_lite | Forex (50 pairs) | Human-in-the-loop briefing | Production (FTMO planning) |
| BH FTMO autonomous | Forex (OANDA H4) | Fully automated paper trading | Live on OANDA demo |
| BH Swing automation | US equities (IBKR) | Fully automated paper trading | Phase 1a (active dev) |

### How they relate

The original **equity predictor** is the research engine. Its scoring logic was forked into **bh_lite** to bring the same indicator framework to forex (sized for an FTMO challenge, human reads the brief and places trades manually). The **BH FTMO autonomous** trader is the long-term, fully automated descendant of bh_lite on OANDA. The **BH Swing automation** project is the equities-side analog: it takes the predictor's signals and submits/manages bracket orders through IBKR autonomously. Until BH Swing reaches live-account readiness, bh_lite remains the human-driven briefing tool.

---

## 1. Original BH Equity Predictor

### What it does

The original CLI in `src/main.py` is the research and signal-generation backbone of BlueHorseshoe. It:

- Ingests OHLCV from Alpha Vantage into DuckDB (`data/ohlcv.duckdb`)
- Calculates 40+ technical indicators across momentum, trend, volume, moving averages, candlestick patterns, and pivots
- Scores ~11,000 NASDAQ stocks against two strategies — **Baseline (trend-following)** and **Mean Reversion**
- Adds ML overlays for win-probability and dynamic stop-loss
- Generates an HTML report with the top trading candidates
- Backtests strategies and optimizes indicator weights

### How it works

1. **Data ingestion** (`-u`, `-b`) — fetches OHLCV from Alpha Vantage, rate-limited by `ALPHAVANTAGE_CPS`, stored in DuckDB.
2. **Prediction** (`-p`) — for each symbol: filters by price ($5–$500) and volume (>100k avg), scores against both strategies, applies ML models, filters by risk/reward, saves scores to MongoDB.
3. **Reporting** — generates `src/logs/full_report_YYYY-MM-DD.html` with top 50 candidates.
4. **Optional paper trading** — if `PAPER_TRADING_ENABLED=true`, submits bracket orders to IBKR for the top N candidates (this hook is what BH Swing automation extends).

### How to use it

All commands go through the venv wrapper:

```bash
./run.sh python src/main.py [flags]
```

#### Primary modes (one per run)

| Flag | Argument | Description |
|---|---|---|
| `-u` | — | Update recent OHLCV (last ~100 datapoints) |
| `-b` | — | Backfill full historical OHLCV |
| `-p` | `[DATE]` | Predict candidates for `DATE` (default: latest market date) |
| `-r` | `[DATE]` | Regenerate HTML report from saved scores |
| `-t` | `DATE` | Run backtest starting on `DATE` |
| `-w` | `DATE` | Leave-one-out weight analysis |
| `-f` | `DATE` | Forward-selection weight analysis |
| `-g` | `DATE` | Indicator impact analysis |
| `-o` | — | Optimize indicator weights (grid search) |
| `-q` / `--ibkr-quote` | `SYMBOL [SYMBOL ...]` | Real-time IBKR quotes |
| `-m` / `--monitor` | — | IBKR watchlist polling loop |
| `-i` / `--intraday` | `SYMBOL ENTRY STOP TARGET` | Intraday trade status check |
| `-d` | — | Debug routines |

#### Common secondary flags

| Flag | Used with | Description |
|---|---|---|
| `--symbols SPY,QQQ,...` | `-u`, `-b`, `-p`, `-r`, `-t`, `-w`, `-f`, `-g` | Restrict to specific symbols |
| `--all` | `-u` | Include inactive symbols |
| `--refresh-overviews` | `-u` | Backfill missing overviews |
| `--ov-limit N` | `-u` w/ `--refresh-overviews` | Cap overview refresh count |
| `--resume` | `-b` | Resume interrupted backfill |
| `--limit N` | `-b` | Cap symbols processed |
| `--deep` | `-b` | Deep historical backfill |
| `--indicators X,Y` | `-p`, `-t` | Restrict to listed indicators |
| `--aggregation METHOD` | `-p`, `-t` | Aggregation method (default: `sum`) |
| `--target 1.01` | `-t` | Take-profit factor |
| `--stop 0.98` | `-t` | Stop-loss factor |
| `--hold N` | `-t`, `-w`, `-f`, `-g` | Hold days (defaults: 3/10/10/10) |
| `--workers N` | `-t`, `--motifs` | Parallel worker count |
| `--rescore` | `-t` | Recalculate scores instead of loading saved |
| `--split MODE` | `-t`, `-w` | Split-exit (`fixed_pct` or `atr_tiered`) |
| `--t1-pct`, `--t1-atr`, `--t2-atr` | `-t` | Split-exit tuning |
| `--end DATE` | `-t`, `-w`, `-f`, `-g` | End of date range |
| `--interval N` | `-t`, `-w`, `-f`, `-g` | Step (defaults: 7/7/7/14 days) |
| `--trailing` / `--trailing-mult 2.0` | `-t` | Trailing stop |
| `--strategy baseline\|mean_reversion` | `-t` | Strategy under test |
| `--top N` | `-w`, `-f` | Top-N candidates considered |
| `--min-improvement 0.1` | `-f` | Forward-selection threshold |

#### Journal / hypothesis modes

| Flag | Description |
|---|---|
| `--journal-review [DATE]` | Daily trade review |
| `--journal-weekly DATE` | Weekly summary |
| `--journal-reconcile [DATE]` | Reconcile with IBKR fills |
| `--journal-import-ibkr` | Import executions from IBKR |
| `--journal-import-csv PATH [--legacy]` | Import fills from a CSV |
| `--journal-log-ideas [DATE]` | Retroactively log trade ideas |
| `--evaluate [DATE]` | Evaluate matured signal hypotheses |
| `--motifs [--full] [--symbols ...] [--resume]` | Build motif catalog |

#### Worked examples

```bash
# Daily refresh
./run.sh python src/main.py -u

# Predict for today (latest market date)
./run.sh python src/main.py -p

# Predict for a specific date
./run.sh python src/main.py -p 2026-05-13

# Backfill SPY and QQQ from scratch (need 200+ days for regime EMAs)
./run.sh python src/main.py -b --symbols SPY,QQQ

# Backtest Mean Reversion over a date range
./run.sh python src/main.py -t 2025-01-01 --end 2025-12-31 --interval 7 --strategy mean_reversion

# Real-time quote
./run.sh python src/main.py -q AAPL MSFT
```

### Outputs

- `src/logs/full_report_YYYY-MM-DD.html` — top candidates report (also `email_report_`, `arcade_report_`)
- `src/logs/blueHorseshoe.log` — main pipeline log
- `src/logs/report.txt` — console summary
- `src/logs/backtest_log.csv` — backtest history
- MongoDB `scores` collection — per-date saved scores

---

## 2. bh_lite — Morning Briefing for FTMO

### What it does

`bh_lite` is the manual-trading companion for Brand's FTMO forex challenge. It applies the BlueHorseshoe scoring framework to 50 forex pairs and produces a ranked daily brief — the human reads the brief and places the trades in MT5. It is the bridge between the equity research engine and the FTMO challenge while the autonomous forex track is still being validated.

### How it works

1. Pulls 6-month daily OHLCV + 1-day 5-min intraday from the **Yahoo Finance public API** for 50 forex pairs (no OANDA tier required at this stage).
2. Scores each pair on Baseline (trend) and Mean Reversion using the same indicator engine as the equity predictor.
3. Filters by cluster occupancy — one signal per correlated pair group (12 clusters, e.g. EUR-crosses, JPY-crosses).
4. Sizes positions against the configured account size, 1% max per trade, 4% daily risk budget, max 3 concurrent positions.
5. Renders a console brief with rank, entry/stop/targets, position size, and P&L on any already-open positions — plus a JSON order template you can paste into MT5.

### How to use it

**Cron schedule:** runs nightly at 22:30 UTC weekdays via `run_bh_lite.sh` (calls `python src/bh_lite.py --top 5`).

**Manual invocation:**

```bash
./run.sh python src/bh_lite.py [flags]
```

| Flag | Default | Description |
|---|---|---|
| `--config PATH` | `src/bh_lite_config.json` | Account/risk/instrument config |
| `--positions PATH` | `src/bh_lite_positions.json` | Currently open positions (read-only at startup) |
| `--top N` | `3` | Number of ranked signals to print |
| `--csv` | off | Also write ranked signals to `src/logs/bh_lite_YYYY-MM-DD.csv` |

#### Worked examples

```bash
# Standard morning brief
./run.sh python src/bh_lite.py

# Wider brief + CSV for spreadsheet review
./run.sh python src/bh_lite.py --top 10 --csv

# Test against a fork of the config
./run.sh python src/bh_lite.py --config /tmp/bh_lite_test.json
```

### Config files

- `src/bh_lite_config.json` — account size, 1%/4% risk caps, 3-position cap, T1/T2 50/50 split, 50 instruments × 12 clusters
- `src/bh_lite_positions.json` — currently open positions

### Outputs

- **Console table** — ranked signals + open-position P&L + health warnings
- `src/bh_lite_orders.json` — MT5-paste order template
- `src/logs/bh_lite_YYYY-MM-DD.csv` — only with `--csv`
- `src/logs/bh_lite.log` — append-mode cron log

---

## 3. BH FTMO Autonomous Forex Trader

### What it does

The autonomous successor to bh_lite. Runs two paper traders against OANDA demo on the H4 timeframe, fully closed-loop: detect signal → check safety gates → submit OANDA order → journal → close on TP/SL/age. This is the track that validates strategies for an eventual live FTMO funded account.

Two distinct traders share the codebase:

- **`rising_3bar` paper** — single-strategy, deployed 2026-04-30. Stochastic %K rising 3 bars from below 20. 1.0% risk, 1.5%/1.5% TP/SL, all 40 OANDA H4 pairs.
- **v2 multi-cell paper** — 33 cells across 9 strategies (macd, atr, ichimoku, stoch, bb, cci, ema, sma, rsi) covering 17 pairs. 0.5% risk, 1.0%/1.0% TP/SL. Limit-entry cells use GTD-to-next-bar; mid-entry cells use market orders.

### How it works

1. Cron fires 15–16 minutes after each H4 bar close (UTC 01, 05, 09, 13, 17, 21).
2. The trader pulls H4 bars from OANDA, detects signals per cell.
3. **Safety gates** (`src/bh_ftmo/trading/safety.py`) — fail-closed:
   - `margin_utilization` ≤ 40% (run-level)
   - `|n_long − n_short|` ≤ 12 (per-order direction imbalance)
4. Submits orders to OANDA demo via the v20 REST API.
5. Position-age cap closes stale positions per entry-mode config (limit: 5 days; mid: no cap by default).
6. Journals every event (signal, submit, fill, close) to per-trader CSV.

### How to use it

#### Paper trader entry points

```bash
# rising_3bar (single strategy)
./run.sh python src/bh_ftmo_paper.py [--dry-run]

# v2 multi-cell autonomous
./run.sh python src/bh_ftmo_v2_paper.py [--dry-run]
```

| Flag | Default | Description |
|---|---|---|
| `--dry-run` | off | Detect + journal signals, do NOT submit orders |

Both are cron-driven; manual invocation is for debugging or replaying a bar.

```cron
# Crontab (illustrative)
15 1,5,9,13,17,21 * * * cd /root/BlueHorseshoe && ./run.sh python src/bh_ftmo_paper.py
16 1,5,9,13,17,21 * * * /root/BlueHorseshoe/run_bh_ftmo_v2_paper.sh
```

#### Operator tools (shipped 2026-05-06)

**Flatten** — close positions until margin utilization drops below a target.

```bash
./run.sh python src/bh_ftmo_flatten.py [flags]
```

| Flag | Default | Description |
|---|---|---|
| `--target FRAC` | `0.25` | Target margin utilization (25%) |
| `--strategy worst\|best\|biggest` | `worst` | Close-order: worst losers first / best winners / largest margin |
| `--max-closes N` | `30` | Safety cap on positions closed per run |
| `--execute` | off | Actually submit closes (default is dry-run) |

**Status** — one-screen dashboard.

```bash
./run.sh python src/bh_ftmo_status.py [--hours 48]
```

| Flag | Default | Description |
|---|---|---|
| `--hours H` | `48` | Journal lookback window |

#### Worked examples

```bash
# Validate a bar without trading
./run.sh python src/bh_ftmo_v2_paper.py --dry-run

# Defensive flatten before a high-impact news event
./run.sh python src/bh_ftmo_flatten.py --target 0.20 --strategy worst --execute

# Quick health check
./run.sh python src/bh_ftmo_status.py --hours 24
```

### Config files

- `src/bh_ftmo_config.json` — challenge params, 40-pair universe, pip sizing, tiers, clusters, per-entry-mode position-age caps, OANDA account size

### Outputs

- `src/logs/bh_ftmo_paper_journal.csv` — rising_3bar trades
- `src/logs/bh_ftmo_v2_paper_journal.csv` — v2 multi-cell trades
- `src/logs/bh_ftmo_flatten_journal.csv` — flatten history

---

## 4. BH Swing Automation (IBKR Equities)

### What it does

The autonomous IBKR equity trader — the equities-side counterpart to BH FTMO. It picks up the bracket orders that `main.py -p` submits to IBKR and manages them through their lifecycle: reconciles fills, advances stops, journals every event. Currently in active development per the `synthetic-cooking-meerkat` plan; Phase 0 (read-only monitor) and Phase 1a (broker integration + flatten tool) are shipped.

### How it works

1. **Signal generation** — `main.py -p` runs (with `PAPER_TRADING_ENABLED=true`). `PaperTrader` submits 3-leg bracket orders (entry / T1 take-profit / T2 stop-loss) to IBKR and writes `trade_orders` metadata to MongoDB.
2. **Monitor loop** — cron fires `bh_swing_monitor.py` every 5 minutes. It reads IBKR truth, merges with the Mongo metadata, and walks each position through the management state machine.
3. **Reconciler** — fills detected on the broker side are recorded as `fill_detected` events in `src/logs/bh_swing_journal.csv`.
4. **Stop rules** (`bh_swing/analysis/stop_rules.py`) — the active rule is **breakeven on T1 fill**: when T1 take-profit fills, the T2 stop is advanced to the entry price. MIDPOINT and ATR_CLAMPED rules are stubbed; the early-exit hook is disabled.
5. **Safety gates** (`bh_swing/trading/safety.py`) — fail-closed:
   - `stop_move_is_tightening` — refuse any proposed stop move that loosens
   - `actions_under_rate_limit` — ≤ 3 mutations per tick
   - `position_count_under_cap`
   - `kill_switch_inactive` — `.bh_swing_pause_management` sentinel file pauses all mutation
6. **HTML tracker** — `src/graphs/swing_tracker.html` renders account, positions, orders, and recent events live.

### How to use it

#### Monitor (Phase 0 / 1a)

```bash
./run.sh python src/bh_swing_monitor.py [flags]
```

| Flag | Default | Description |
|---|---|---|
| *(none)* | Phase 0 | Read-only: reconcile + render, no management |
| `--manage-dry-run` | off | Phase 1a shadow: journal `would_*` events, zero mutations |
| `--manage` | off | Phase 1b live: actually advance stops |
| `--lookback-hours N` | `24` | Reconcile lookback window |
| `--verbose` / `-v` | off | Debug logging |

#### Flatten (emergency exit)

```bash
./run.sh python src/bh_swing_flatten.py [flags]
```

| Flag | Default | Description |
|---|---|---|
| `--execute` | off | Actually mutate (default is dry-run) |
| `--sort worst\|best\|biggest` | `biggest` | Close order |
| `--max-closes N` | unbounded | Cap closes |
| `--symbols SYM1,SYM2` | all | Symbol filter |

#### Status

```bash
./run.sh python src/bh_swing_status.py
```

Operator dashboard summarizing account, open positions, and recent journal events.

#### Worked examples

```bash
# Phase 0: just watch (cron default)
./run.sh python src/bh_swing_monitor.py

# Phase 1a: shadow management — journal what we WOULD do
./run.sh python src/bh_swing_monitor.py --manage-dry-run

# Phase 1b: live management (when promoted)
./run.sh python src/bh_swing_monitor.py --manage

# Trigger predictions + paper-trade submission (the upstream step)
PAPER_TRADING_ENABLED=true ./run.sh python src/main.py -p

# Emergency: flatten everything in AAPL
./run.sh python src/bh_swing_flatten.py --symbols AAPL --execute

# Pause all stop management without stopping the cron
touch /root/BlueHorseshoe/.bh_swing_pause_management
```

### Key modules

| File | Purpose |
|---|---|
| `src/bh_swing_monitor.py` | Monitor entry point (Phase 0 / 1a / 1b) |
| `src/bh_swing_flatten.py` | Operator flatten tool |
| `src/bh_swing_status.py` | Operator dashboard |
| `src/bh_swing/analysis/position_state.py` | Merges IBKR broker truth with Mongo metadata into `ManagedPosition` |
| `src/bh_swing/analysis/stop_rules.py` | Stop-advancement proposals (breakeven on T1 fill) |
| `src/bh_swing/trading/safety.py` | Four safety gates (tightening / rate / cap / kill-switch) |
| `src/bh_swing/trading/manager.py` | `manage_tick()` orchestrator (propose → gate → mutate) |
| `src/bh_swing/journal.py` | Append-only CSV audit trail |
| `src/bluehorseshoe/trading/paper_trader.py` | Upstream bracket submitter (run by `main.py -p`) |
| `src/bluehorseshoe/data/ibkr_client.py` | IBKR read + mutation methods |

### IBKR connection

| Setting | Value |
|---|---|
| Host | `127.0.0.1` |
| Port | `4004` (Gateway paper) |
| Client ID | `1` (main pipeline), `7` (bh_swing monitor) |

The IBKR Gateway runs in Docker (`docker/docker-compose.yml`). Lite-tier IBKR accounts block API access — Pro is required (see `reference_ibkr_account_types`).

### Outputs

- `src/logs/bh_swing_journal.csv` — append-only event log (signal, submit, fill_detected, stop_move, flatten, etc.)
- `src/graphs/swing_tracker.html` — live HTML dashboard

---

## Quick reference: which tool when?

| You want to… | Use |
|---|---|
| Refresh equity OHLCV | `main.py -u` |
| Get today's equity picks | `main.py -p` |
| Backtest an equity strategy | `main.py -t DATE` |
| Plan tonight's FTMO forex trades (manual) | `bh_lite.py` |
| Run autonomous FTMO forex paper trading | `bh_ftmo_v2_paper.py` (cron) |
| Stress-test a forex bar without trading | `bh_ftmo_v2_paper.py --dry-run` |
| Defensive flatten on forex | `bh_ftmo_flatten.py --execute` |
| Check forex paper status | `bh_ftmo_status.py` |
| Monitor IBKR equity bracket orders | `bh_swing_monitor.py` |
| Manage IBKR stops (live) | `bh_swing_monitor.py --manage` |
| Flatten IBKR positions | `bh_swing_flatten.py --execute` |
| Pause IBKR stop management | `touch .bh_swing_pause_management` |
