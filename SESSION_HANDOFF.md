# Session Handoff

**Date:** April 24, 2026
**Status:** BH FTMO Phases 1, 2a, 2b complete — full multi-pair signal pipeline running on real OANDA data. 1211 tests passing.

---

## What Was Done This Session (April 24)

Twenty-four BH FTMO commits land Phases 1 → 2b. The system now ingests 10 years of OANDA bid/ask 4h forex bars for the 40 FTMO instruments, computes a full forex indicator suite, and emits cluster-filtered Baseline + MeanReversion signals across the universe.

### Phase 0.5 — OANDA Validation Probe ✅
- `src/bh_ftmo/data/oanda_probe.py` ran against the live OANDA account
- 40/40 FTMO instruments pass: bid+ask, 10y history, 5000-bar pages, zero rate-limit hits
- Verdict GO; commits `7d8c8f1`

### Phase 1 — Data Foundation ✅
- `src/bh_ftmo/data/oanda_client.py` — OANDA v20 REST client with rate limiter, paginated candle iterator, `Retry-After` honoring exponential backoff (`5570fef`)
- `src/bh_ftmo/data/fx_time_utils.py` + `docs/planning/FX_TIME_SPEC.md` — DST-aware NY 5pm session anchor, UK/US holiday handling, gap classifier with `BarGapKind {WEEKEND, US_HOLIDAY, UK_HOLIDAY, DATA_GAP}` (`8fed8bd`)
- `src/bh_ftmo/data/fx_store.py` — DuckDB wrapper for `ohlcv_4h` + `ohlcv_1h` (PK `(symbol, timestamp)`, bid+ask + `provider`/`ingested_at`/`is_complete`). `save_rows` dedupes within batch to handle pagination overlap. (`5f93a80`)
- `src/bh_ftmo/data/validate.py` — pre-ingestion candle validator + post-storage audit using `classify_gaps` (`889ace7`)
- `src/bh_ftmo/logging/scrubber.py` — `SecretScrubber` logging filter redacting OANDA tokens + account IDs (decision C-2) (`94a4f24`)
- `src/bh_ftmo/data/backfill.py` — year-chunked, resumable 10y backfill with `CheckpointStore` (`7975ecf`)
- `docs/planning/FTMO_RULES.md` — policy spec for daily-loss / max-drawdown / profit-target / weekend-flatten rules (decision 5A) (`d105cdb`)
- `data/fx_4h.duckdb` added to `backup.sh` pipeline (`8d7808a`)
- `src/bh_ftmo/data/incremental_update.py` — every-4h cron entry point with SMTP failure email (`0edb681`)
- **Live backfill ran cleanly: 3,207,322 bars across 40 symbols × H4+H1 in ~14 min, zero gaps.**

### Phase 2a — Indicator Port (decision 15D, fully independent) ✅
Decision 15D reversed the original "share-with-equity" plan after investigation showed deep coupling to `weights_config`/`reporting`/`curves`/`constants`. BH FTMO indicators are now wholly independent at `src/bh_ftmo/indicators/`. Equity code untouched.

- `momentum.py` — RSI (Wilder's), MACD, Stochastic, CCI, Williams %R (`7ed29f6`)
- `volatility.py` — true_range, ATR (Wilder's), atr_percent, Bollinger Bands (`bfac46c`)
- `trend.py` — SMA, EMA, ADX (with +DI/-DI), SuperTrend (iterative), Donchian, Ichimoku (`c57a757`)
- `pivots.py` — vectorized NY-calendar-day aggregation + classic pivot formulas; Monday uses Friday via `prior_forex_day` (`ca8c67b`)
- `candlestick.py` — hand-rolled (no talib): doji, hammer, shooting star, bullish/bearish engulfing (`279ef0c`)
- `strength.py` — currency strength meter via log-return aggregation across all pairs each currency appears in (`5d7550d`)
- `dxy_correlation.py` — synthesized DXY using ICE formula `50.14348112 × EURUSD^-0.576 × USDJPY^0.136 × ...` + per-pair rolling correlation (`25998e2`)
- `sessions.py` — `Session` enum (ASIA/LONDON/OVERLAP/NY/CLOSED) with NY-local hour boundaries; `session_label`, `session_ranges` (`a2a8b97`)

### Phase 2b — Scoring Layer ✅
- `src/bh_ftmo/analysis/strategy.py` + `bh_ftmo_weights.json` — `Signal` dataclass, `BaselineStrategy` (12 rule components: trend / momentum / candlestick / context). Each Signal carries `components: dict[str, float]` for explainability. (`8f2338a`)
- `src/bh_ftmo/analysis/signal_generator.py` — `SignalGenerator` builds shared DXY + currency-strength context once, fans strategies across pairs. Best-effort context: DXY needs all 6 ICE constituents; strengths needs ≥4 pairs. Default 20-pair strength universe ensures every G8 currency appears in ≥3 pairs. (`d18b9c8`)
- `src/bh_ftmo/analysis/cluster_filter.py` — currency flag-bearer dedup. Each long signal on `BASE_QUOTE` expresses long-BASE + short-QUOTE; per `(timestamp, currency, direction)`, the highest-scoring signal wins. A signal survives if it's the flag-bearer for ≥1 of its 2 exposures. `explain_cluster_filter()` returns per-candidate diagnostics. (`a1f131e`)
- `src/bh_ftmo/analysis/mean_reversion.py` — two-sided MR. Per-bar direction: oversold conditions (RSI<30, BB-lower, Williams<-80, CCI<-100) fire long; overbought conditions fire short; neither fires direction=0. Direction-neutral bonuses (ADX<20, ASIA session) attach to whichever side anchored. (`17983c2`)

**Live multi-strategy smoke (Apr 15-23, 2026)**: 1440 baseline + 1440 MR signals → 565 above-threshold (395 baseline-long, 117 MR-long, 53 MR-short) → 361 after cluster filter.

---

## Previous Sessions Summary

- **April 19–23:** Intraday context weight tuning (504-combo grid search), unclamped context score, deployed CSW=2.0/IW=6.0; BH Lite health check fixes (entry-strategy stickiness + TAKE PROFIT status); research droplet destroyed
- **April 17–19:** Intraday context layer (Phase 1 + Phase 2) shipped, BH Lite cron automated, research droplet spun up
- **April 15–17:** BH Lite FTMO signal generator built and iterated
- **April 12:** Holiday warning banner, trade history CSV importer with era tags
- **April 4–5:** Report cleanup, DuckDB read-only mode, code quality sweep
- **April 2–4:** Hypothesis engine (Layer B) shipped, MongoDB auth enabled
- **March 29 – April 2:** MR weight tuning (cap_8 deployed), research droplet
- **March 27:** Assumption tester, regime-aware stop/target multipliers
- **March 23:** Trade journal system
- **March 9:** Pluggable strategy interface
- **March 7-8:** DuckDB migration, new indicators (RVOL, Engulfing, Hammer)

---

## In Progress

- Nothing actively in progress. All Phase 2b items committed and tests green.

## Next Steps

1. **Phase 3 — Backtesting Framework** (~1–2 weeks): bid/ask-aware simulator, FTMO rule enforcement (daily 5%, max 10%, profit target, CE(S)T reset), walk-forward harness over 10y backfill, Phase-3 entry-edge gate (Sharpe ≥1.0, PF ≥1.3, win-rate ≥45%, MaxDD ≤10%, FTMO pass-rate ≥70%).
2. **Brand fills FTMO_RULES.md §2 TBD values** from FTMO live dashboard → `bh_ftmo_config.json` `ftmo` block. Doesn't block Phase 3 simulator development; it gates the Phase 6 cutover.
3. **Brand installs GitHub App** before May 8 so the scheduled BH FTMO check-in routine (`trig_01RfvYoMo6V7bETCRBLn5WNT`) can run.
4. **Brand runs `bash /tmp/humanaction.sh`** to install the every-4h incremental-update cron when ready.
5. **Phase 2c — Indicator Tuning** runs after Phase 3 exists (walk-forward grid search for forex-appropriate lookback periods).
6. See `TODO.md` for full backlog and `docs/planning/BH_FTMO_PLAN.md` for the locked plan.

## Blockers / Open Questions

- **SMTP from Claude Code sandbox is blocked** — Brand must run `send_report_email.py` manually for equity reports
- **Phase 3 baseline implementations** (decision 17B): random-entry+ATR-exit, Mon-in/Fri-out fixed-schedule, simple RSI(14) — needed for entry-edge-gate comparison
- **Crypto deferred for v1** — no BTC_USD / ETH_USD on this OANDA account; if crypto becomes strategically important, fall back to Binance public REST 4h klines

---

## Key Decisions

- **Decision 15D (BH FTMO indicator isolation)** — fully independent indicators at `src/bh_ftmo/indicators/`. Zero shared code with equity. Reverses the original 15C "extract to `src/shared/`" plan after investigation showed deep equity-side coupling.
- **MR strategy drops strength/DXY rules** — those are trend-following heuristics that fight the MR thesis. Phase 2c can revisit if tuning shows benefit.
- **Cluster filter is currency flag-bearer, not correlation-based** — per `(timestamp, currency, direction)` the highest-scoring signal wins; a signal survives if it's the flag-bearer for ≥1 of its 2 exposures. Balanced dedup that doesn't over-suppress independent setups.
- **Default strength universe is 20 majors crosses** ensuring every G8 currency appears in ≥3 pairs.
- **OANDA live account, data-only** — Brand's token is live-scoped. Demo account dormant. Data-only access to live is zero-risk since orders are manual paste to FTMO MT5. Configurable via `OANDA_ENV=practice` later.
- Prior decisions (intraday context unclamped, MongoDB auth, hypothesis engine, MR cap_8, Brevo email, human-action scripts, advisory budget model, fresh Codex branches, BH Lite frozen until Phase 6 cutover) remain in effect.

---

## Key Files (BH FTMO additions)

| File | Role |
|------|------|
| `src/bh_ftmo/data/oanda_client.py` | OANDA v20 REST client with rate limiter + retry |
| `src/bh_ftmo/data/fx_store.py` | DuckDB wrapper for 4h + 1h forex bars (bid/ask) |
| `src/bh_ftmo/data/fx_time_utils.py` | DST-aware session boundaries + gap classification |
| `src/bh_ftmo/data/backfill.py` | Resumable 10y year-chunked OANDA backfill |
| `src/bh_ftmo/data/incremental_update.py` | Every-4h cron entry point with email-on-failure |
| `src/bh_ftmo/data/validate.py` | OANDA candle + stored-bar validators |
| `src/bh_ftmo/indicators/` | Full forex indicator suite (independent of equity) |
| `src/bh_ftmo/analysis/strategy.py` | `BaselineStrategy` + `Signal` |
| `src/bh_ftmo/analysis/mean_reversion.py` | `MeanReversionStrategy` (two-sided) |
| `src/bh_ftmo/analysis/signal_generator.py` | Multi-pair driver with shared context |
| `src/bh_ftmo/analysis/cluster_filter.py` | Currency flag-bearer dedup |
| `src/bh_ftmo/logging/scrubber.py` | Token/account-ID redaction filter |
| `src/bh_ftmo_weights.json` | Baseline + mean_reversion weight blocks |
| `data/fx_4h.duckdb` | 10y bid/ask 4h + 1h bars (gitignored) |
| `docs/planning/FTMO_RULES.md` | FTMO policy spec — §2 TBD until Brand fills |
| `docs/planning/FX_TIME_SPEC.md` | Canonical time/DST/holiday rules |
| `docs/planning/BH_FTMO_PLAN.md` | Locked plan, source of truth for architecture |

---

### Production Commands (Host)
```bash
./run.sh python src/main.py -p                          # Equity prediction (~3 hours)
./run.sh python src/main.py -u                          # Equity data update (~30 min)
./run.sh python src/main.py --evaluate                  # Evaluate matured hypotheses
./run.sh python src/main.py -r YYYY-MM-DD               # Regenerate equity report
./run.sh python src/send_report_email.py                # Send latest report email
./run.sh python src/bh_lite.py --top 5                  # BH Lite manual run (frozen until Phase 6)
./run.sh python -m bh_ftmo.data.backfill                # BH FTMO backfill CLI
./run.sh python -m bh_ftmo.data.incremental_update      # BH FTMO incremental update
./run.sh python -m bh_ftmo.data.oanda_client            # BH FTMO health check
./run.sh pytest -v                                      # Tests
./run.sh ./lint.sh                                      # Lint
```

*************** DO NOT EDIT THE FOLLOWING SECTION WHEN UPDATING SESSION_HANDOFF.md
**IMPORTANT:** All SSH commands to the research droplet MUST `cd /root/BlueHorseshoe` first.
The default login directory is `/root`, NOT the repo directory.

**Workaround for Claude Code:** Write remote commands to `/tmp/remote_cmd.sh` and pipe via `ssh root@161.35.136.234 bash < /tmp/remote_cmd.sh` — this reliably includes the `cd`.

```bash
ssh root@161.35.136.234
# All commands must run from /root/BlueHorseshoe
# Direct SSH (for humans):
ssh root@161.35.136.234 "cd /root/BlueHorseshoe && ./run.sh pytest"
# Destroy when done:
doctl compute droplet delete bh-research --force
```
*************** END OF IMMUTABLE SECTION

**Cron schedule:**
- BH Lite: 23:30 UTC Mon-Fri (7:30 PM EDT / 6:30 PM EST) — frozen until Phase 6 cutover
- BH Main: 01:00 UTC Mon-Sat (9 PM EDT / 8 PM EST)
- BH FTMO incremental update: every 4 hours (pending Brand running `/tmp/humanaction.sh` to install)
- Backup: 05:00 UTC daily → Google Drive via rclone (now includes `data/fx_4h.duckdb`)

---

## Git Status

**Branch:** master
**Working tree:** clean (post-Phase-2b commits)
**Active feature branches:** none
**Phase 2b commits:** `8f2338a`, `d18b9c8`, `a1f131e`, `17983c2`
**Tests:** 1211 passing, 3 skipped

---

**Last Updated:** April 24, 2026
