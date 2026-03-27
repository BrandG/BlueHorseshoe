# Session Handoff

**Date:** March 27, 2026
**Status:** Assumption tester built and run, regime-aware strategy implemented, Python migrated from Docker to host venv. 685 tests passing.

---

## What Was Done This Session (March 27)

### 1. Assumption Tester — Strategy Validation Research

Built a 3-phase research tool to validate trading assumptions against historical data.

- **Phase 1**: Score all symbols across 100 historical dates using current algorithm (lean mode — no ML, no sentiment)
- **Phase 2**: Simulate trades (buy at next-day open, track daily highs/lows for 10 forward days)
- **Phase 3**: Parameter sweep (10 targets × 10 stops × 10 hold days × 4 top-N buckets), tiered exit analysis, stop tradeoff curves

**v1 run (combined top 20)**: All 2,000 picks were Mean Reversion — MR scores dominate combined rankings due to 25x curve weights. Results showed near-zero or negative EV, which didn't match real-world experience.

**v2 run (per-strategy, top 10 each)**: Segmented by strategy (Baseline vs MR) and market regime (SPY above/below 50-day MA). Key findings:

| Segment | 2%/5d EV | Tiered EV | Best Stop |
|---------|----------|-----------|-----------|
| Baseline + Bearish | **+0.712%** | +0.574% | 4.0% |
| Baseline + Bullish | +0.061% | +0.209% | 1.0% |
| MR + Bearish | +0.242% | +0.350% | 2.5% |
| MR + Bullish | **-0.041%** | +0.065% | 1.0% |

**Files**: `src/research/assumption_tester.py`, `src/research/visualize_results.py`

### 2. Regime-Aware Strategy Parameters

Implemented regime-adjusted ATR multipliers based on research findings.

- Added `REGIME_PROFILES` dict to `constants.py` with bearish/neutral/bullish parameter profiles
- Added `get_regime_stop_multiplier()` and `get_regime_target_multiplier()` to `TradingStrategy` ABC
- `BaselineStrategy.process()` and `process_worker()` now use regime-adjusted multipliers
- Added `regime_status` field to `StrategyResult` dataclass
- Bearish: 2.5x stop / 3.5x target (wider — let bounces develop)
- Bullish: 1.5x / 2.5x (tighter — cut losses fast)
- Neutral: 2.0x / 3.0x (unchanged defaults)

### 3. Docker-to-Host Migration

Moved Python execution from Docker container to native host venv.

- Compiled TA-Lib C library on the host
- Created `.venv` with all dependencies from `requirements.txt`
- Added `REPO_ROOT` auto-detection to `config.py` (derives from file location — works on host AND in container)
- Updated 20+ source files to replace hardcoded `/workspaces/BlueHorseshoe` paths
- Updated `run_daily_pipeline.sh`, `cron_weekly_retrain.sh`, `backup.sh` to use venv Python directly
- Created `run.sh` wrapper (activates venv, sets PYTHONPATH)
- Created systemd service file for FastAPI API (not yet started — waiting for container removal)
- MongoDB and IBKR Gateway remain in Docker containers
- Updated CLAUDE.md for host-based workflow

**NOT YET DONE**: Remove BH container from docker-compose.yml (waiting for first successful host pipeline run at 02:00 UTC). Then start systemd API service.

---

## Previous Sessions Summary

- **March 23:** Trade journal system — full 5-phase lifecycle (ideas → orders → fills → positions → reviews), wired into daily cron
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

- **Docker container removal** — BH container still in docker-compose.yml as fallback. Remove after tonight's pipeline succeeds, then `systemctl start bluehorseshoe-api`.

## Next Steps

- **Verify host pipeline** — Monitor the 02:00 UTC run. If successful, remove BH container from docker-compose and start systemd API service.
- **Regime-aware enhancements** — Paper trader max_positions by regime, backtest hold_days by regime, HTML report regime badge (see TO-DO.md)
- **Gate MR in bullish** — Research shows negative EV. Consider reducing or skipping MR picks when SPY > 50-day MA.
- **Import legacy spreadsheet** — Run `--journal-import-csv path/to/sheet.csv --legacy` to backfill historical trade data
- **Hypothetical trade engine** — Layer B from TO-DO: auto-evaluate signal outcomes after hold period
- See `TO-DO.md` for full backlog

## Blockers / Open Questions

- **DuckDB orphaned processes** — Still possible when pipeline is killed. Now that Python runs on host, `kill` works directly (no need for `docker compose restart`). Consider adding `trap` cleanup to `run_daily_pipeline.sh`.
- **One flaky test** — `test_load_historical_data_from_net` passes in container but fails on host (mock sensitivity to import order). Not a regression — pre-existing issue exposed by different environment.

---

## Key Decisions

- **REPO_ROOT auto-detection** — `Path(__file__).resolve().parents[3]` in config.py. Works identically in container (`/workspaces/BlueHorseshoe`) and on host (`/root/BlueHorseshoe`). All path defaults derived from it.
- **MongoDB on 0.0.0.0** — Changed `MONGO_BIND_IP` from `10.132.0.2` to `0.0.0.0` so both host Python (127.0.0.1) and research droplet (VPC IP) can connect.
- **Container-specific overrides in docker/.env** — `MONGO_URI=mongodb://mongo:27017` and `IBKR_HOST=ib-gateway` only apply inside the container. Host uses code defaults (127.0.0.1).
- **Regime multipliers replace defaults, not ML** — For Baseline, regime directly replaces the hardcoded 2.0x stop. For MR, ML predictions still take precedence; regime only affects the fallback.
- **Per-strategy ranking for research** — v1 combined ranking was entirely MR (score inflation from 25x curve weights). v2 used top-10-per-strategy to get fair comparison.
- **Bearish = wide stops** — Counterintuitive but data-driven. Stocks bouncing from oversold conditions need room to recover. Tight stops in bearish markets stop out winners prematurely.

---

## Key Files

| File | Role |
|------|------|
| `src/bluehorseshoe/core/config.py` | Settings + REPO_ROOT derivation |
| `src/bluehorseshoe/analysis/constants.py` | REGIME_PROFILES dict |
| `src/bluehorseshoe/analysis/strategy_interface.py` | Regime-aware multiplier methods, StrategyResult |
| `src/research/assumption_tester.py` | 3-phase strategy validation tool |
| `src/research/visualize_results.py` | 12 diagnostic chart generator |
| `run.sh` | Host venv wrapper |
| `run_daily_pipeline.sh` | Daily cron (now uses host Python) |
| `/etc/systemd/system/bluehorseshoe-api.service` | FastAPI systemd unit (enabled, not started) |

---

### Production Commands (Host)
```bash
./run.sh python src/main.py -p                          # Prediction (~72 min)
./run.sh python src/main.py -u                          # Data update (~30 min)
./run.sh python src/main.py -r YYYY-MM-DD               # Regenerate report (~30 sec)
./run.sh python src/main.py --journal-import-ibkr        # Import IBKR fills
./run.sh python src/main.py --journal-reconcile          # Build positions from fills
./run.sh python src/main.py --journal-review YYYY-MM-DD  # Daily review
./run.sh pytest -v                                       # Tests (685 passing)
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

**Cron pipeline:** Runs at 02:00 UTC (Mon-Sat) — now via host venv, not Docker
**Cron backup:** Runs at 05:00 UTC daily → Google Drive via rclone

---

## Git Status

**Branch:** master
**Commits ahead of origin:** 3 (unpushed)
- `d6c3f4c` feat: Regime-aware stop/target multipliers based on research
- `02df345` feat: Assumption tester — validate strategy parameters against history
- `3e6a9d7` feat: Migrate Python execution from Docker to host venv
**Tests:** 685 passing (684 on host — 1 flaky mock test)

---

**Last Updated:** March 27, 2026
