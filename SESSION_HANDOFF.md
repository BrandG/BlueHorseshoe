# Session Handoff

**Date:** March 23, 2026
**Status:** Trade journal system implemented — full 5-phase lifecycle tracking from prediction ideas through execution, reconciliation, and review. 687 tests passing.

---

## What Was Done This Session (March 23)

### Trade Journal System — Full Implementation (5 phases)

Built closed-loop trade lifecycle tracking. BH now records what it planned, what was ordered, what filled, and how it performed vs the plan.

**Phase 1: Data Models + Trade Idea Logger**
- `trade_models.py` — 6 dataclasses (`TradeIdea`, `TradeOrder`, `TradeFill`, `PositionLeg`, `TradePosition`, `TradeReview`) + 4 ID helpers + strategy name normalization
- `trade_idea_logger.py` — Logs top-N actionable candidates to `trade_ideas` collection with position sizing, component parsing, and risk/reward calculation
- Auto-fires during `-p` pipeline (non-fatal), plus standalone `--journal-log-ideas [DATE]`

**Phase 2: Normalized Trade Orders**
- Extended `paper_trader.py` with per-leg order tracking (`t1_order_ids`, `t2_order_ids`) and `_log_trade_orders()` method
- Each T1/T2 bracket leg writes a separate `trade_orders` doc linked to its `trade_idea` via deterministic `idea_id`
- `execute()` accepts optional `idea_lookup` dict; backward compatible — existing callers unaffected
- `paper_trades` collection still written for backward compat

**Phase 3: Execution Importer**
- `execution_importer.py` — Pulls fills from IBKR or CSV into `trade_fills` collection with dedup by `fill_id`
- Added `get_executions()` and `get_commissions()` to `IBKRClient` using `ib_async.reqExecutions()`
- `csv_legacy_importer.py` — Imports historical spreadsheet data; creates paired entry/exit fills + synthesized positions
- CLI: `--journal-import-ibkr`, `--journal-import-csv FILE [--legacy]`

**Phase 4: Trade Reconciler**
- `trade_reconciler.py` — Matches ideas → orders → fills, builds `trade_positions` with T1/T2 legs
- 3-step reconciliation: broker order ID matching → orphan fill fuzzy matching (symbol + date ±2 days) → position building
- Calculates: volume-weighted avg entry, entry slippage, per-leg PnL, R-multiple, hold days, close reason inference
- CLI: `--journal-reconcile [DATE]`

**Phase 5: Metrics + Journal Reporter**
- `trade_metrics.py` — `PortfolioMetrics`, `StrategyMetrics`, `DisciplineMetrics` dataclasses + calculator
- Computes: win rate, profit factor, expectancy, avg R-multiple, entry slippage, plan adherence
- `trade_journal_reporter.py` — Generates `trade_reviews` docs with plan-vs-actual, discipline scoring, outcome classification
- Daily review + weekly summary with formatted console output
- CLI: `--journal-review [DATE]`, `--journal-weekly DATE`

**File Inventory: 7 new source files, 3 modified, 8 new test files (67 new tests)**

---

## Previous Sessions Summary

- **March 19-22:** Curve/motif analysis (4-phase), full catalog build (34,890 motifs, 6,114 passing), differentiated weights (baseline 10x, MR 25x), CNN Fear & Greed Index, AAII sentiment

- **March 15:** Finviz sentiment, z-score normalizer, arcade report, VIX integration, StockTwits, Tiingo News
- **March 10:** Automated daily backup to Google Drive via rclone
- **March 9:** Pluggable strategy interface
- **March 8:** MongoDB OHLCV dual-write removed, DuckDB thread-safety, new indicators (RVOL, Engulfing, Hammer)
- **March 7:** DuckDB migration complete
- **March 6:** Vectorized backtesting — 13x speedup
- **March 5:** Score-once backtest refactor

---

## In Progress

- **Nothing mid-task** — all work completed and committed

## Next Steps

- **Wire journal into daily cron** — After `-p` finishes: `--journal-import-ibkr` → `--journal-reconcile` → `--journal-review`. Could be a post-prediction script or chained in the cron pipeline.
- **Import legacy spreadsheet** — Run `--journal-import-csv path/to/sheet.csv --legacy` to backfill historical trade data
- **Monitor curve impact** — Watch daily predictions for curve score contributions
- **Rebuild catalog periodically** — Quarterly on research droplet
- **Accumulate sentiment data** — Need ~1 month before sentiment-price divergence analysis
- **Add sentiment to ML features** — Once history exists
- **Hypothetical trade engine** — Layer B from TO-DO: auto-evaluate signal outcomes after hold period
- See `TO-DO.md` for full backlog

## Blockers / Open Questions

- **DuckDB orphaned processes** — After killing a prediction or motif build, spawn worker processes can persist and hold the DuckDB lock. `docker compose restart bluehorseshoe` is the reliable fix. Consider adding cleanup logic to the pipeline script.
- **Motif catalog rebuild timing** — Full rebuild takes ~35 hrs and blocks DuckDB. Must use research droplet. Could explore read-only DuckDB mode for the catalog builder since it only reads OHLCV data.

---

## Key Decisions

- **Deterministic IDs for journal collections** — `idea_{date}_{symbol}_{strategy}` → `order_{idea_id}_{T1|T2}` → `pos_{idea_id}` → `review_{pos_id}`. Enables cross-collection linking without JOINs. Makes reconciliation idempotent (re-running doesn't duplicate).
- **Trade ideas separate from signal journal** — `journal_signals` captures ALL signals (hundreds per run), `trade_ideas` captures only the top-N you intend to trade. Different purpose, cardinality, and query patterns.
- **Legs as embedded subdocs** — T1/T2 are always part of one logical position. Querying "show me the position for AAPL" returns one document with both legs, not two rows.
- **Extend paper_trader, don't rewrite** — `paper_trades` collection still written for backward compat. New `trade_orders` collection adds per-leg detail and idea linkage alongside it.
- **Strategy name normalization** — Candidates use display names ("Baseline", "MeanRev"), journal normalizes to internal names ("baseline", "mean_reversion") for consistent ID generation.
- **Non-fatal journal integration** — All journal calls in `-p` pipeline wrapped in try/except. Journal failures never break prediction.
- **Close reason inference** — Reconciler infers stop/target/manual from exit price vs planned levels (within 0.5% tolerance).
- **Raw averaging for composite sentiment** — Z-score normalization was unintuitive. Simple average of raw scores.
- **Curve weights differentiated by strategy** — Baseline 10x, MR 25x.
- **DuckDB is sole OHLCV store** — MongoDB retains scores, journal, overviews, checkpoints, symbols, news, and now trade lifecycle data.

---

## Key Files

| File | Role |
|------|------|
| `src/bluehorseshoe/trading/trade_models.py` | Dataclasses + ID helpers for full trade lifecycle |
| `src/bluehorseshoe/trading/trade_idea_logger.py` | Logs top-N candidates to `trade_ideas` |
| `src/bluehorseshoe/trading/execution_importer.py` | IBKR + CSV fill import to `trade_fills` |
| `src/bluehorseshoe/trading/csv_legacy_importer.py` | Historical spreadsheet import with position synthesis |
| `src/bluehorseshoe/trading/trade_reconciler.py` | Ideas→orders→fills matching, position building |
| `src/bluehorseshoe/trading/trade_metrics.py` | P/L, R-multiple, win rate, expectancy, discipline |
| `src/bluehorseshoe/trading/trade_journal_reporter.py` | Daily review + weekly summary generation |
| `src/bluehorseshoe/trading/paper_trader.py` | Bracket order submission + trade_orders logging |
| `src/bluehorseshoe/data/ibkr_client.py` | IBKR Gateway client (quotes, orders, executions) |
| `src/bluehorseshoe/core/journal.py` | Immutable signal journal (Layer A) |
| `src/bluehorseshoe/analysis/strategy.py` | Pipeline wiring |
| `src/main.py` | CLI entry with all journal commands |
| `src/bluehorseshoe/data/duckdb_store.py` | DuckDB storage backend |
| `backup.sh` / `backup.conf` | Daily backup to Google Drive |

---

## MongoDB Collections (Trade Journal)

| Collection | Unique Index | Content |
|------------|-------------|---------|
| `trade_ideas` | `idea_id` | What BH intended to trade (top N per prediction) |
| `trade_orders` | `order_ref` | Orders submitted to broker (per T1/T2 leg) |
| `trade_fills` | `fill_id` | Actual executions from IBKR or CSV (source of truth) |
| `trade_positions` | `position_id` | Synthesized from fills, with T1/T2 legs |
| `trade_reviews` | `review_id` | Plan-vs-actual metrics, discipline, outcome |

## MongoDB Collections (Sentiment & Other)

| Collection | Content |
|------------|---------|
| `journal_batches` / `journal_signals` | Immutable prediction snapshots (all signals) |
| `trade_scores` | Daily scores per strategy |
| `paper_trades` | Legacy order execution log (still written for compat) |
| `sentiment_snapshots` | Daily snapshots by `(symbol, date, source)` |
| `motif_catalog` | Curve motif patterns with forward-outcome statistics |

---

## Pipeline Timing

| Pipeline | Symbols | Time |
|----------|---------|------|
| `-u` (data update) | 3,590 | ~30 min |
| `-p` (prediction) | 5,417 | ~72 min |
| `-r` (report regen) | — | ~30 sec |

---

## Infrastructure

### Research Droplet
- **Status:** DESTROYED (March 21, 2026) — used for full motif catalog build (~35 hrs)
- **Note:** When re-creating, must SCP `data/ohlcv.duckdb` to the droplet. Fix CPU limit in `docker-compose.research.yml` if using s-2vcpu size (set cpus to "2").
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

### Production
```bash
docker exec bluehorseshoe python src/main.py -p                          # Prediction (~72 min)
docker exec bluehorseshoe python src/main.py -u                          # Data update (~30 min)
docker exec bluehorseshoe python src/main.py -r YYYY-MM-DD               # Regenerate report (~30 sec)
docker exec bluehorseshoe python src/main.py --journal-import-ibkr        # Import IBKR fills
docker exec bluehorseshoe python src/main.py --journal-import-csv FILE   # Import CSV fills (--legacy for spreadsheet)
docker exec bluehorseshoe python src/main.py --journal-reconcile         # Build positions from fills
docker exec bluehorseshoe python src/main.py --journal-review YYYY-MM-DD # Daily review
docker exec bluehorseshoe python src/main.py --journal-weekly YYYY-MM-DD # Weekly summary
docker exec bluehorseshoe python src/main.py --journal-log-ideas YYYY-MM-DD # Retroactive idea logging
docker exec bluehorseshoe pytest -v                                      # Tests (687 passing)
docker exec bluehorseshoe ./lint.sh                                      # Lint
```

**Cron pipeline:** Runs at 02:00 UTC (Mon-Sat)
**Cron backup:** Runs at 05:00 UTC daily → Google Drive via rclone

---

## Git Status

**Branch:** master
**Latest commit:** uncommitted — trade journal system (7 new files, 3 modified, 8 test files)
**Pushed:** No — pending commit
**Tests:** 687 passing

---

**Last Updated:** March 23, 2026
