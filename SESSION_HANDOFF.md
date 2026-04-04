# Session Handoff

**Date:** April 4, 2026
**Status:** Hypothetical Trade Engine (Layer B) shipped and validated. MongoDB authentication enabled. Docker-compose cleanup merged. System stable.

---

## What Was Done This Session (April 2–4)

### 1. Codex Branch Cleanup
- Merged `codex-refactor` docker-compose change (removed BH Python container) via cherry-pick, excluding stale SESSION_HANDOFF.md each time
- Codex-refactor branch is now effectively dead — all useful commits cherry-picked to master

### 2. MongoDB Authentication
- Created `bhapp` user with `readWrite` on `bluehorseshoe` database
- Enabled `--auth` in docker-compose.yml
- Updated `MONGO_URI` in both `.env` (127.0.0.1) and `docker/.env` (mongo hostname)
- Restarted MongoDB and API service
- Verified: unauthenticated access denied, API health OK, reports serve correctly
- Fixed `backup.sh` to use `--uri` flag instead of `--host`/`--port`/`--db`
- Fixed `backup.conf` to source root `.env` (not `docker/.env`) for host-accessible MONGO_URI

### 3. Hypothetical Trade Engine (Layer B) — 4 commits
Built and shipped the full hypothesis evaluation system:

1. **`trade_evaluator.py`** — Pure walk-forward evaluation functions (entry buffer, gap-down slippage, MAE/MFE tracking, 4 outcomes: WIN/LOSS/TIMEOUT/NOT_ENTERED)
2. **`hypothesis_engine.py`** — Batch discovery, bulk OHLCV loading, per-signal evaluation, SPY benchmark, idempotent MongoDB storage in `journal_hypothetical_trades`
3. **20 unit tests** — Full coverage of evaluator functions and engine class with mocked dependencies
4. **CLI + pipeline integration** — `--evaluate` flag in main.py, step in `run_daily_pipeline.sh` (runs last, after email), `pipeline_status.py` updated

**Validated with real data:**
- 2026-02-20 batch: 3,355 signals evaluated (WIN: 995, LOSS: 1,147, TIMEOUT: 1,034, NOT_ENTERED: 179)
- 2026-02-24 batch: 1,323 signals evaluated (WIN: 237, LOSS: 714, TIMEOUT: 309, NOT_ENTERED: 63)
- Idempotency confirmed (re-run skips duplicates)
- Remaining 11 batches will auto-evaluate as they mature

### 4. API Service
- Already running on port 8001 via systemd (was started before this session)
- Health check passes, reports endpoint serves data
- Restart counter was high (37,794) from pre-fix crash looping — stable now

### 5. Report Cleanup & Test Fix
- Removed "Yesterday's Results" / "Previous Day Performance" from all three report types (standard, email, arcade)
- Removed `get_previous_performance()` and `_get_previous_trading_date()` from strategy.py
- Removed `previous_performance` parameter from all reporter methods and callers (services.py, main.py)
- Removed associated CSS (`.prev-perf-*` classes) from arcade report
- Fixed pre-existing test failure: `test_load_historical_data_from_net` — updated mock from `requests.get` to `_get_provider_pool` to match provider pool refactor
- Added `/tmp/humanaction.sh` protocol to CLAUDE_PROTOCOLS.md for tmux-friendly human action requests

---

## Previous Sessions Summary

- **March 29 – April 2:** MR weight tuning (cap_8 deployed), Baseline tuning (no changes), email fix, Docker cleanup, research droplet destroyed
- **March 27:** Assumption tester, regime-aware stop/target multipliers, Docker→host migration
- **March 23:** Trade journal system (5-phase lifecycle)
- **March 19-22:** Curve/motif analysis, CNN Fear & Greed, AAII sentiment
- **March 15:** Finviz sentiment, z-score normalizer, arcade report, VIX, StockTwits, Tiingo News
- **March 9:** Pluggable strategy interface
- **March 7-8:** DuckDB migration, new indicators (RVOL, Engulfing, Hammer)
- **March 5-6:** Vectorized backtesting, score-once backtest refactor

---

## In Progress

- **Nothing actively in progress** — all tasks completed and validated

## Next Steps

1. **Monitor hypothesis engine** — Watch tomorrow's pipeline run (02:00 UTC) to confirm `evaluate` step works in cron context. More batches will mature over the coming days.
2. **Analyze hypothesis results** — Once enough batches accumulate, query `journal_hypothetical_trades` for insights: win rate by strategy, score threshold discovery, regime-based performance
3. **Event-driven backtest** — Order-book model replacing check-levels approach (TODO near-term)
4. **DuckDB read-only mode** — Phase 1 of Parquet migration, eliminates lock contention
5. **Regime-aware remaining items** — Paper trader position sizing, backtester hold_days, HTML report regime display
6. See `TODO.md` for full backlog

## Blockers / Open Questions

- **SMTP from Claude Code sandbox is blocked** — user must run `send_report_email.py` manually from their shell. Daily cron works fine.
- **Hypothesis engine only has 2 evaluated batches so far** — Need more data to draw meaningful conclusions. Remaining batches will auto-evaluate as they mature.
- **Codex-refactor branch** is stale (all changes cherry-picked) — can be deleted with `git push origin --delete codex-refactor` when convenient.

---

## Key Decisions

- **MongoDB authentication enabled** — defense-in-depth: ufw + localhost bind + auth. User `bhapp` with `readWrite` on `bluehorseshoe` database.
- **Entry buffer 0.1%** — Hypothesis engine requires price to cross 0.1% below entry to account for execution delay. Gap-down slippage uses open price.
- **Hold period is regime-aware** — Bearish=7d, Bullish/Neutral=5d from REGIME_PROFILES in constants.py.
- **Evaluate all signals (score > 0)** — Collect maximum data, discover the real edge later via analysis.
- **Evaluation runs last in pipeline** — After report and email, so it never delays delivery.
- **Maturity = hold_days + 5 trading days** — Checked via SPY bar count in DuckDB, avoids holiday calendar complexity.
- **MR cap_8 is the production solution** — caps mr_mean_reversion_specific contribution at 8.0 points.
- **Run both strategies in all regimes** — scores naturally surface best picks.
- **Email via Brevo on port 2525** — Gmail blocked by DigitalOcean, SendGrid key is stale.

---

## Key Files

| File | Role |
|------|------|
| `src/bluehorseshoe/analysis/trade_evaluator.py` | Pure walk-forward trade evaluation functions (NEW) |
| `src/bluehorseshoe/analysis/hypothesis_engine.py` | Hypothesis engine — batch discovery, evaluation, MongoDB storage (NEW) |
| `src/tests/test_hypothesis_engine.py` | 20 unit tests for evaluator + engine (NEW) |
| `src/main.py` | CLI entry — added `--evaluate` flag |
| `run_daily_pipeline.sh` | Added evaluate step (runs last) |
| `src/pipeline_status.py` | Added "evaluate" to STEPS |
| `docker/docker-compose.yml` | `--auth` enabled for MongoDB |
| `backup.sh` | Uses `--uri` for authenticated mongodump |
| `backup.conf` | Sources root `.env` for MONGO_URI |
| `src/weights.json` | Indicator weights — production values with cap_8 |

---

### Production Commands (Host)
```bash
./run.sh python src/main.py -p                          # Prediction (~60 min)
./run.sh python src/main.py -u                          # Data update (~30 min)
./run.sh python src/main.py --evaluate                  # Evaluate matured hypotheses (~20 sec)
./run.sh python src/main.py --evaluate 2026-04-01       # Evaluate as-of specific date
./run.sh python src/main.py -r YYYY-MM-DD               # Regenerate report (~30 sec)
./run.sh python src/send_report_email.py                 # Send latest report email
./run.sh pytest -v                                       # Tests
./run.sh ./lint.sh                                       # Lint
```

*************** DO NOT EDIT THE FOLLOWING SECTION WHEN UPDATING SESSION_HANDOFF.md
**IMPORTANT:** All SSH commands to the research droplet MUST `cd /root/BlueHorseshoe` first.
The default login directory is `/root`, NOT the repo directory.

**Workaround for Claude Code:** Write remote commands to `/tmp/remote_cmd.sh` and pipe via `ssh root@10.132.0.4 bash < /tmp/remote_cmd.sh` — this reliably includes the `cd`.

```bash
ssh root@10.132.0.4
# All commands must run from /root/BlueHorseshoe
# Direct SSH (for humans):
ssh root@10.132.0.4 "cd /root/BlueHorseshoe && docker exec bh-research python src/run_clean_backtest.py --version v3"
# Copy results:
scp root@10.132.0.4:/root/BlueHorseshoe/src/logs/clean_backtest_v3.csv src/logs/
# Destroy when done:
doctl compute droplet delete bh-research --force
```
*************** END OF IMMUTABLE SECTION

**Cron pipeline:** Runs at 02:00 UTC (Mon-Sat) — via host venv + .env sourcing
**Cron backup:** Runs at 05:00 UTC daily → Google Drive via rclone

---

## Git Status

**Branch:** master
**Working tree:** Clean (after this handoff commit)
**Codex branch:** `origin/codex-refactor` — stale, all changes cherry-picked. Safe to delete.
**Tests:** 714 passing (all green)

---

**Last Updated:** April 4, 2026
