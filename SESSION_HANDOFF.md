# Session Handoff

**Date:** April 25, 2026
**Status:** BH FTMO Phase 3 (Backtesting Framework) sub-phases 3.0 → 3.5 complete. Engine + rules + baselines + metrics + reporter + walk-forward + gate + CLI driver shipped. Gate verdict on locked Phase 2b weights not yet produced. 1396 tests passing, 3 skipped (Claude-verified; Codex sandbox can't run pytest because Docker network access is blocked, so MongoDB-backed equity tests fail spuriously there).

---

## What Was Done This Session (April 25)

Eleven commits land BH FTMO Phase 3 end-to-end (sub-phases 3.0 → 3.5). The full backtest framework is now functional: bid/ask-aware simulator, FTMO rule enforcement (static + trailing DD), three null baselines, walk-forward fold harness, metrics + reporter, entry-edge gate, CLI driver. `./run.sh python -m bh_ftmo.backtest.cli` runs the full Phase 3 gate evaluation on live 10y data and emits a pass/fail verdict.

Companion design doc `docs/planning/PHASE_3_BACKTEST_ARCH.md` (575 lines) drafted with `/plan-eng-review` + Codex cross-model review; 20 P3-* decisions locked.

### Pre-work — Architecture + config (`02d3234`, `68a169c`)
- `PHASE_3_BACKTEST_ARCH.md` drafted; full eng review and Codex cross-model review (6 cross-model decisions)
- `FTMO_RULES.md` updated for `max_loss_type` static/trailing fork (P3-13), account-currency-agnostic naming (P3-14), half-at-open/half-at-close commission (P3-15), swap-then-reset ordering (P3-16), hard-block on placeholder load (P3-3)
- `bh_ftmo_config.json` `ftmo` block filled with verified FTMO Free Trial values: 14-day, $100k, static DD, 10% target / 5% daily / 10% max, Europe/Prague server tz

### Phase 3.0 — Primitives + sizing (`e7e1503`)
- `types.py` — `Trade`, `Position`, `FillEvent`, `RuleBreach`, `ChallengeResult`, `ExitEvent` dataclasses (account-currency-agnostic, no `_usd` suffixes)
- `pip_value.py` — FX pip mechanics + quote-currency conversion (P3-14). Property tests against FTMO spec for 8 sample pairs
- `position.py`, `equity.py`, `swap.py`, `commission.py` — bookkeeping primitives (commission is half-at-open / half-at-close per P3-15)
- `intrabar.py` — 1h-path event extraction per position
- `event_queue.py` — portfolio-level chronological applier (P3-11)
- `trade_factory.py` — `Signal` → entry / stop / target / lots derivation; refuses to open if 1h data missing (P3-12)
- `calendar_provider.py` — `Protocol` + `NullCalendarProvider` (P3-8 Phase-5 seam)
- `risk_exits.py` — weekend-flatten + deadline awareness (P3-18 / locked decision 14)

### Phase 3.1 — Engine + rules (`7541516`, `c49ab49`, `418d214`, `d2052bd`, `1d93201`)
- `event_queue.apply_in_order` — applies portfolio events chronologically; deterministic tie-break by `(symbol_alphabetical, kind_priority)` with `stop > target`
- `ftmo_rules.FtmoRuleEngine` — daily loss / max DD (static OR trailing per P3-13) / profit target / min&max trading days / DST-aware CE(S)T resets via `fx_time_utils.ftmo_day_boundary`
- `ftmo_rules.load_ftmo_config` — raises `FtmoConfigUnverifiedError` on placeholder values (P3-3 hard-block, no `--allow-placeholders` flag)
- `engine.run_challenge` — process-safe main simulator (P3-9)
- `engine.run_n_randomized` — `ProcessPoolExecutor` fan-out for the gate's pass-rate metric; deterministic per-seed
- Golden frozen run + integration tests + lint cleanup

### Phase 3.2 — Baselines (`9844244`)
- `RandomEntryAtrExitStrategy` — uniform-random entry at configurable density, seeded
- `MondayInFridayOutStrategy` — long EUR_USD at Monday Asia open; exit handled by engine's weekend flatten
- `SimpleRsi14Strategy` — RSI(14)<30 long / >70 short; reuses `bh_ftmo.indicators.momentum.rsi`
- All three picklable for `ProcessPoolExecutor`; each produces `list[Signal]` consumable by `engine.run_challenge`
- 18 tests: 5 per baseline + 3 engine-integration

### Phase 3.3 — Metrics + reporter (`5b50d57`)
- `metrics.py` — Sharpe, Sortino (annualized from 1h-resampled equity per P3-17), profit factor, win rate, max DD, R-expectancy, payoff ratio, worst-DD trade chain
- `metrics.py` — FTMO pass rate with bootstrap 95% CI (Codex #9, P3-19 input)
- `reporter.py` — HTML + CSV: equity curve, per-cluster / per-session / per-strategy breakdowns, baselines side-by-side, gate verdict, worst-DD chain, pass-rate bootstrap-CI histogram

### Phase 3.4 — Walk-forward + gate (`e3af17a`)
- `walk_forward.py` — 18mo IS / 6mo OOS / 6mo roll fold splitter (decision 8); fold edges snap to trading days via `fx_time_utils.prior_forex_day`; OOS-contamination assertion property test
- `gate.py` — entry-edge gate evaluator (P3-19 + decision 16A): Sharpe ≥ 1.0, PF ≥ 1.3, WR ≥ 45%, MaxDD ≤ 10%, FTMO pass-rate lower-95%-CI ≥ 70%, AND ≥10pp better than best baseline pass-rate
- Exact trade risk added (per-trade account-currency dollar amount tracking)

### Phase 3.5 — CLI driver (`e842d9a`)
- `cli.py` — argparse-driven entry point: signal generation → walk-forward fold enumeration → `runner.run_full_comparison` → `gate.evaluate_gate` → reporter HTML/CSV. Exit codes: 0 pass, 1 fail, 2 error. stdout = verdict only; stderr = progress logs. Hard-block on placeholder ftmo config surfaces as exit 2.
- `swap_rates.py` — OANDA `/v3/accounts/{id}/instruments` financing fetcher with date-versioned cache at `data/swap_rates_<date>.json`. `--no-swap` fallback for offline / CI runs.
- `runner.py` — orchestration layer between `engine.run_n_randomized` and the CLI (added during 3.5; not in original arch doc)
- One-line bug fix in `_compute_atr_by_symbol`: ATR series index must be timestamps (`engine.py:560` looks up via `series.loc[bar_ts]`); pre-fix integration smoke test crashed with `KeyError`

---

## Previous Sessions Summary

- **April 24:** BH FTMO Phases 1, 2a, 2b complete — 24 commits land OANDA data foundation (10y/40 instruments/3.2M bars/zero gaps), full forex indicator suite (independent per decision 15D), and scoring layer (BaselineStrategy + MeanReversionStrategy + multi-pair `SignalGenerator` + currency flag-bearer cluster filter). Tests 792 → 1211.
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

- Phase 3 build complete. **First gate evaluation on locked Phase 2b weights has NOT been run yet** — this is the Phase 3 exit criterion (§10 #3 in `PHASE_3_BACKTEST_ARCH.md`). Until the verdict is in, we don't know whether Phase 4 (edge-exits) unblocks or whether we halt to debug entries.

## Next Steps

1. **Run the Phase 3 gate against locked Phase 2b weights** to produce the first verdict. Command: `./run.sh python -m bh_ftmo.backtest.cli`. Capture verdict + reporter HTML output. Exit codes: 0 pass / 1 fail / 2 error.
2. **If gate passes** → unblock Phase 4 (edge-exit scoring) AND Phase 2c (indicator lookback tuning + walk-forward optimizer per P3-20).
3. **If gate fails** → halt, debug entry side, do NOT enter Phase 4 (per `PHASE_3_BACKTEST_ARCH.md` §10 #6).
4. **Investigate `bh_ftmo_config.json instruments` block pip values** vs. the verified `pip_value.py` module. The legacy `dollar_per_pip_per_lot` values copied from BH Lite (USDHUF 0.27, EURCZK 0.44, EURNOK 0.95, EURSEK 0.97, USDZAR 0.55, JPY-quoted 6.67) are still in the JSON. Determine whether these are dead/legacy or actively read by `trade_factory.py` — if read, port `pip_value.py`'s verified values into the JSON or delete the field.
5. **Codex sandbox limitation** — Codex's session blocks Docker network access, so MongoDB at `127.0.0.1:27017` is unreachable. Equity-side tests that depend on MongoDB (~13 fixtures, ~31 cascading failures) fail spuriously in Codex's environment. Pick one workaround for future Codex Next Actions that need test validation: (a) Brand runs pytest from his shell and supplies the count, (b) add pytest markers to skip MongoDB-dependent tests so Codex can run a Codex-runnable subset, or (c) reconfigure Codex sandbox to allow Docker network access.
6. **Brand action items still open from prior sessions:**
   - Run `bash /tmp/humanaction.sh` to install every-4h incremental-update cron
   - Install GitHub App before May 8 so `trig_01RfvYoMo6V7bETCRBLn5WNT` (BH FTMO check-in routine) can run
   - SMTP from Claude Code sandbox is blocked — Brand runs `send_report_email.py` manually for equity reports
7. **Phase 2c — Indicator Tuning** kicks off after Phase 3 gate passes (walk-forward grid search for forex-appropriate lookback periods).
8. See `TODO.md` for full backlog and `docs/planning/BH_FTMO_PLAN.md` for the locked plan.

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
**Working tree:** clean
**Active feature branches:** `docs-refresh-handoff-phase3` (this branch, awaiting merge)
**Phase 3 commits:** `02d3234`, `68a169c`, `e7e1503`, `7541516`, `c49ab49`, `418d214`, `d2052bd`, `1d93201`, `9844244`, `5b50d57`, `e3af17a`, `e842d9a`
**Tests:** 1396 passing, 3 skipped (verified by Claude in a Docker-accessible session; see Status note above)

---

**Last Updated:** April 25, 2026
