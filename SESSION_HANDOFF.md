# Session Handoff

**Date:** April 12, 2026
**Status:** Holiday warning banner shipped and verified. Trade history CSV importer shipped with era tags. System stable, 735 tests passing on master.

---

## What Was Done This Session (April 12)

### 1. Holiday Warning Banner — Implemented, Reviewed, Merged
- Rewrote `/tmp/nextaction.md` for Codex (prior session's handoff was lost)
- Codex implemented on `codex/holiday-warning` branch; reviewed in three rounds:
  1. **Initial implementation** (`8b9a703`) — new `market_calendar.py` module, banners in all three HTML report types, 9 tests. Approved with minor cleanup needed.
  2. **Dead code cleanup** (`d61d752`) — removed unused `.holiday-warning-arcade` CSS class, `@keyframes holiday-blink`, and `_nyse_holidays_for_year` backward-compat alias. Also updated `test_watchlist_monitor.py` to import from the new shared module.
  3. **Report-date fix** (`362879c`) — banner helpers were using `date.today()` instead of the report's target date, so banners never appeared on regenerated reports or weekend runs. Fixed by threading `report_date: str` through the three `_holiday_banner_*` methods.
- Eyeball-verified: `./run.sh python src/main.py -r 2026-04-02` shows Good Friday banner in all three report files.

### 2. Trade History CSV Importer — Designed, Implemented, Reviewed, Merged
- User provided `data/trade_history.csv` with 365 raw broker fills (Dec 2024 – Apr 2026, zero-commission "lite" account)
- Analyzed data: 95 unique symbols, 1 orphan sell (KEX, pre-BH), IAU as DCA position
- Designed and handed off `import-trade-history` nextaction to Codex:
  - `src/import_trade_history.py` — standalone CLI with `--dry-run`, `--force`, `--csv` flags
  - Phase 1: CSV parsing → `trade_fills` documents
  - Phase 2: FIFO position synthesis (handles split fills, re-entries, DCA, orphan sells)
  - Phase 3: `trade_reviews` generation with outcome classification
  - Phase 4: Dry-run summary with position table and win/loss/breakeven stats
- Codex implemented (`572cd7d`), 10/10 tests passing
- **Era tags** added in follow-up (`62ed7c7`): `"pre_bh"` for pre-2026 trades, `"bh_v2"` for 2026+ trades. Applied to both `trade_positions` and `trade_reviews` documents.
- Import results:
  - **Full dataset:** 101 positions, 59.4% win rate, $5.35 total P&L
  - **2026 only (BH-informed):** 77 positions, 64.9% win rate, $133.29 total P&L
- Added `data/trade_history.csv` to `.gitignore` (personal trade data)

### 3. Merge Conflict in SESSION_HANDOFF.md
- The `codex/holiday-warning` branch had an older copy of SESSION_HANDOFF.md that conflicted with master. Resolved by rewriting the file cleanly this session.

---

## Previous Sessions Summary

- **April 7–10:** Holiday warning banner designed and handed off to Codex (not yet implemented)
- **April 4–5:** Report cleanup (Yesterday's Results removed), DuckDB read-only mode (Phase 1 of Parquet migration), code quality sweep (utcnow → datetime.now(timezone.utc), 4 pylint runtime bugs fixed), test fix
- **April 2–4:** Hypothesis engine (Layer B) shipped, MongoDB auth enabled, docker-compose cleanup, codex-refactor cherry-picks
- **March 29 – April 2:** MR weight tuning (cap_8 deployed), Baseline tuning (no changes), email fix, Docker cleanup, research droplet destroyed
- **March 27:** Assumption tester, regime-aware stop/target multipliers, Docker→host migration
- **March 23:** Trade journal system (5-phase lifecycle)
- **March 19-22:** Curve/motif analysis, CNN Fear & Greed, AAII sentiment
- **March 15:** Finviz sentiment, z-score normalizer, arcade report, VIX, StockTwits, Tiingo News
- **March 9:** Pluggable strategy interface
- **March 7-8:** DuckDB migration, new indicators (RVOL, Engulfing, Hammer)

---

## In Progress

- Nothing actively in progress. All items from this session are merged.

## Next Steps

1. **Monitor hypothesis engine** — confirm `--evaluate` step works in cron context. Batches keep maturing.
2. **Analyze hypothesis results** — once 5-10 batches accumulate, query `journal_hypothetical_trades` for insights
3. **Analyze imported trade history** — query `trade_positions` / `trade_reviews` for deeper insights (P&L by hold period, monthly returns, strategy breakdown once strategies are known)
4. **Signal Track Record report section** — replace Yesterday's Results with real N-day outcomes (blocked until enough hypothesis batches mature)
5. **Event-driven backtest** — order-book model replacing check-levels approach
6. **Refactor Backtester to use `trade_evaluator.py`** — Phase 2: dedup `_check_entry()` / `_check_active_trade()`
7. **Regime-aware remaining items** — Paper trader position sizing, backtester hold_days, HTML report regime display
8. **Unused imports cleanup** — 102 unused imports flagged by pylint (low priority, mechanical)
9. See `TODO.md` for full backlog

## Blockers / Open Questions

- **SMTP from Claude Code sandbox is blocked** — user must run `send_report_email.py` manually. Daily cron works fine.
- **Hypothesis engine batches still maturing** — need more data before meaningful analysis.
- **Codex-refactor branch** is no longer in active use by Codex (Codex moved to `codex/holiday-warning`). Confirm with user before deleting.
- **`codex/holiday-warning` branch** can be deleted — all work merged to master.

---

## Key Decisions

- **No new pip dependency for holiday detection** — reuse existing `pandas.tseries.holiday` infrastructure from `watchlist_monitor.py` rather than adding `pandas_market_calendars`.
- **Holiday banner uses report date, not system clock** — ensures banners render correctly on regenerated reports and weekend runs.
- **Trade history import uses FIFO matching** — oldest buys matched to sells first. Re-entries create separate positions. IAU DCA naturally handled.
- **Era tags on imported trades** — `"pre_bh"` for pre-2026, `"bh_v2"` for 2026+. Enables filtering BH-informed trades from pre-BH baseline.
- **KEX orphan sell skipped** — no prior buy in dataset, pre-BH trade.
- **Codex stays off master** — gets a dedicated `codex/<feature>` branch per task.
- **DuckDB read-only by default** — `create_cli_context()` defaults to `read_only_store=True`. Only `-u` and `-b` use read-write.
- **Human action scripts** — When Claude needs the user to run git/shell commands, write to `/tmp/humanaction.sh` for tmux execution.
- Prior decisions (MongoDB auth, hypothesis engine design, MR cap_8, Brevo email) remain in effect.

---

## Key Files

| File | Role |
|------|------|
| `src/bluehorseshoe/core/market_calendar.py` | NYSE holiday calendar + `get_holiday_warning()` |
| `src/tests/test_market_calendar.py` | 9 holiday warning tests |
| `src/bluehorseshoe/reporting/html_reporter.py` | Three banner insertion points + helper methods |
| `src/bluehorseshoe/data/watchlist_monitor.py` | Refactored to import from `market_calendar` |
| `src/import_trade_history.py` | Trade history CSV importer (standalone CLI) |
| `src/tests/test_import_trade_history.py` | 10 importer tests |
| `data/trade_history.csv` | Raw broker fills (gitignored) |
| `src/bluehorseshoe/data/duckdb_store.py` | DuckDB store with `read_only` parameter |
| `src/bluehorseshoe/cli/context.py` | CLI context — `read_only_store=True` default |
| `.claude/CLAUDE_PROTOCOLS.md` | `/tmp/humanaction.sh` protocol |

---

### Production Commands (Host)
```bash
./run.sh python src/main.py -p                          # Prediction (~60 min)
./run.sh python src/main.py -u                          # Data update (~30 min)
./run.sh python src/main.py --evaluate                  # Evaluate matured hypotheses (~20 sec)
./run.sh python src/main.py --evaluate 2026-04-01       # Evaluate as-of specific date
./run.sh python src/main.py -r YYYY-MM-DD               # Regenerate report (~30 sec)
./run.sh python src/send_report_email.py                # Send latest report email
./run.sh python src/import_trade_history.py --dry-run   # Preview trade history import
./run.sh python src/import_trade_history.py             # Import trade history to MongoDB
./run.sh pytest -v                                      # Tests
./run.sh ./lint.sh                                      # Lint
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
**Working tree:** `.gitignore` modified (added `data/trade_history.csv`)
**Active feature branch:** `codex/holiday-warning` — fully merged, safe to delete
**Codex-refactor branch:** No longer in active use. Confirm with user before deleting.
**Tests:** 735 passing, 2 skipped

---

**Last Updated:** April 12, 2026
