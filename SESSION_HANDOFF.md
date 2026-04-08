# Session Handoff

**Date:** April 5, 2026
**Status:** DuckDB read-only mode shipped. Code quality sweep complete (deprecated calls, lint bugs). Report cleanup done. System stable, 717 tests passing.

---

## What Was Done This Session (April 4–5)

### 1. Report Cleanup
- Removed "Yesterday's Results" / "Previous Day Performance" from all three report types (standard, email, arcade)
- Removed `get_previous_performance()`, `_get_previous_trading_date()` from strategy.py
- Removed `previous_performance` parameter from all reporter methods and callers
- Removed associated CSS (`.prev-perf-*` classes) from arcade report

### 2. DuckDB Read-Only Mode (Phase 1 of Parquet migration)
- **Phase 1:** Added `read_only` parameter to `DuckDBStore.__init__` — opens lock-free DuckDB connections when `read_only=True`, skips schema init, guards `save_symbol()` with RuntimeError
- **Phase 2:** Wired through `AppContainer.get_historical_store()` and `create_cli_context()` — default is `read_only=True`, only `-u` and `-b` pass `read_only_store=False`
- 3 new tests: read-only reads, write rejection, concurrent readers

### 3. Code Quality Fixes
- Replaced all 13 `datetime.utcnow()` calls with `datetime.now(timezone.utc)` across 8 files — eliminates Python 3.12 deprecation warnings
- Fixed 4 pylint-reported runtime bugs:
  - `main.py` — missing `HTMLReporter` import (would crash on `-r`)
  - `symbols.py` — missing `BulkWriteResult` import (would crash on sentiment save)
  - `routes.py` — added `from e` exception chaining
  - `ibkr_client.py` — added `from exc` exception chaining

### 4. Test Fix
- Fixed `test_load_historical_data_from_net` — updated mock from `requests.get` to `_get_provider_pool` to match provider pool refactor

### 5. Housekeeping
- Added `/tmp/humanaction.sh` protocol to CLAUDE_PROTOCOLS.md for tmux-friendly human action requests
- Deleted stale branches: local `claude`, `Tweak_indicators`, remote numbered claude branches (17-21)
- Removed `/root/bh-claude` worktree (was on fully-merged `claude` branch)

---

## Previous Sessions Summary

- **April 2–4:** Hypothesis engine (Layer B) shipped, MongoDB auth enabled, docker-compose cleanup, codex branch cherry-picks
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

1. **Monitor hypothesis engine** — Confirm `evaluate` step works in cron context. More batches will mature over the coming days.
2. **Analyze hypothesis results** — Once 5-10 batches accumulate, query `journal_hypothetical_trades` for insights: win rate by strategy, score threshold discovery, regime-based performance
3. **Signal Track Record report section** — Replace Yesterday's Results with real N-day outcomes (blocked until enough batches mature)
4. **Event-driven backtest** — Order-book model replacing check-levels approach (TODO near-term)
5. **Refactor Backtester to use trade_evaluator.py** — Phase 2: dedup `_check_entry()` / `_check_active_trade()`
6. **Regime-aware remaining items** — Paper trader position sizing, backtester hold_days, HTML report regime display
7. **Unused imports cleanup** — 102 unused imports flagged by pylint (low priority, mechanical)
8. See `TODO.md` for full backlog

## Blockers / Open Questions

- **SMTP from Claude Code sandbox is blocked** — user must run `send_report_email.py` manually from their shell. Daily cron works fine.
- **Hypothesis engine batches still maturing** — Need more data to draw meaningful conclusions. Remaining batches will auto-evaluate as they mature.
- **Codex-refactor branch** still in use by Codex (worktree at `/root/bh-codex`). Do not delete.

---

## Key Decisions

- **DuckDB read-only by default** — `create_cli_context()` defaults to `read_only_store=True`. Only `-u` and `-b` use read-write. Eliminates lock contention for concurrent readers.
- **Yesterday's Results removed** — one-day price action is noise; hypothesis engine provides real N-day outcomes via `journal_hypothetical_trades`.
- **Human action scripts** — When Claude needs the user to run git/shell commands, write to `/tmp/humanaction.sh` for easy tmux execution (added to CLAUDE_PROTOCOLS.md).
- **journal.py cell-var-from-loop is a false positive** — pylint flags `strat` captured in lambda at line 135, but `items.sort()` executes immediately so it's safe. Do not "fix" it.
- Prior decisions (MongoDB auth, hypothesis engine design, MR cap_8, Brevo email) remain in effect — see previous handoffs.

---

## Key Files

| File | Role |
|------|------|
| `src/bluehorseshoe/data/duckdb_store.py` | DuckDB store — added `read_only` parameter |
| `src/bluehorseshoe/cli/context.py` | CLI context — `read_only_store=True` default |
| `src/bluehorseshoe/core/container.py` | App container — `read_only` passthrough |
| `src/bluehorseshoe/reporting/html_reporter.py` | Reports — Yesterday's Results removed |
| `src/bluehorseshoe/analysis/strategy.py` | Strategy — `get_previous_performance()` removed |
| `.claude/CLAUDE_PROTOCOLS.md` | Added `/tmp/humanaction.sh` protocol |

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
**Codex branch:** `origin/codex-refactor` — active, used by Codex (worktree at `/root/bh-codex`)
**Stale branches:** All cleaned up (claude, Tweak_indicators, numbered claude branches deleted)
**Tests:** 717 passing (all green, 2 skipped)

---

**Last Updated:** April 5, 2026
