# Session Handoff

**Date:** April 28, 2026
**Status:** Methodological pivot day — paused integrated Phase 3 gate work and built a parallel ground-up sandbox validation track in `/tmp/sandbox_*.py`. Outcome of the day: a 2-signal long-only forex portfolio (`stoch_oversold_cross` + `sma_cross_long` at 4h, 0.5%/0.75% RR, 18-pair filtered universe) that's clearly net-positive in challenge expectation when paired with active intraday risk management. **Best config so far:** `relax_10` — pass rate 15.7%, total fail 9.5%, decisive-outcome ratio 61.2%, mean +0.81% per challenge attempt. **The single biggest mechanical lever was active risk management** — adding intraday liquidation + entry restraint converted the 30% daily-fail rate to 0.9% with only a 1.8pp drop in pass rate. The `--strategies` CLI flag from yesterday's queue is no longer the next step — see "Next Steps" below for the revised order.

---

## What Was Done This Session (April 28)

### Methodological pivot — sandbox-first signal validation
After yesterday's Phase 3 gate produced a FAILED verdict and the indicator validation suite eliminated measurement-noise as the cause, Brand pushed back on the assumption that *any* of the constituent signals had real edge. Pivot: build a parallel sandbox track that validates ONE signal at a time before recomposing them. (See `feedback_validate_incrementally.md` — formalized as a memory this session.)

All scripts live in `/tmp/`. They are deliberately disposable but the methodology should land back in the repo once a passing combo is identified. Order:

| Script | Question answered |
|--------|-------------------|
| `h1_validate.py` | Does BH Lite have detectable edge on 12-month forex daily-bar walk-forward? **Yes — +0.10 R/trade across 5,705 signals, 12σ vs random.** |
| `h1b_components.py` | Why is BH Lite's total-score Spearman ρ negative vs `pnl_R`? **Component-level analysis: most components are noise; `c_trend` is inverted (ρ -0.094); `c_candlestick` is the only positive predictor (ρ +0.031).** |
| `sandbox_indicators.py` | Which singleton indicators have lift across 1h/4h/1d? **All daily winners; H4 mostly noise as singletons; 1H pure noise.** Top: `hammer @ 1d` (+0.056), `sma_20_50_cross long @ 1d` (+0.050), `rsi14_oversold_bounce @ 1d` (+0.045). |
| `sandbox_combinations.py` | Do combinations of singletons stack? **Mostly no.** Pairs add ~0.03 R lift on top of singletons in some cases; triples mostly destroy signal via tiny samples. **`shooting_star` bug fixed** — TA-Lib returns -100 not +100. |
| `sandbox_rr_sweep.py` | What RR shape resolves cleanest at 4h? **0.5% stop / 0.75% target.** 13 of 22 combos go positive. Random baseline pulls from -0.18 → -0.07 R. |
| `sandbox_1d_sweep.py` | Tighter 1d targets to fix 75% timeout rate? **Yes** — 1d@1%/1.5% gives 10 profitable cells vs 2 at 2%/3%. But the highest-WR 1d combos still need wider targets to capture the move. |
| `sandbox_deepdive.py` | Are the leads pair/era-coherent or fluke-driven? **Mixed.** `S_stoch_oversold_cross @ 4h@0.5%` is the most robust (n=7,712, 26/40 pairs profitable, top-3 only 44% of total R, positive across all eras). `P_bb+rsi_short` headline lift is recency-fitted. 1d combos are top-3-pair-concentrated. |
| `sandbox_portfolio.py` | Does the 4-signal portfolio survive realistic spreads? **Filtered yes.** 18-pair filter (drop pairs where spread > 5% of stop) → +28% over 3y. Then 2-signal long-only (drop the bleeders) → +80% over 3y but -31% DD. |
| `sandbox_ftmo_challenge.py` | What's the per-window challenge outcome distribution? **15.6% pass / 30.5% fail_daily / 6.5% fail_total / 47.5% timeout. Decisive ratio 30%.** Daily DD is the binding constraint, not total. |
| `sandbox_ftmo_v2.py` | Does active intraday risk management (entry restraint + liquidation) help? **Dramatically.** Daily fails 30.5% → 0.9%. Decisive ratio 30% → 67%. Mean return +0.27% → +0.77%. |
| `sandbox_ftmo_sweep.py` | Which parameter knob (risk size, buffer relax, RR shape) moves the needle most on v2? **`relax_10` wins.** 15.7% pass, 9.5% total fail, 61.2% decisive ratio, mean +0.81%. Half-risk variants kill the strategy by making it impossible to hit +10% in 14 days (99.7% timeout). |

### Robust 2-signal portfolio (current production candidate)
- **Signals**: `stoch_oversold_cross` (long) + `sma_cross_long` (long), both at 4h granularity
- **RR**: 0.5% stop / 0.75% target = 1.5R
- **Universe**: 18 pairs (drops the 22 where spread > 5% of stop distance — kills HUF/CZK/TRY/ZAR + most exotic crosses)
- **Sizing**: 1% of equity per trade
- **Position cap**: 5 concurrent
- **Active risk mgmt**:
  - Entry restraint: don't open if `(today_realized_loss + sum(open_risks) + new_risk) > daily_buffer × buffer_mult`
  - Intraday liquidation: at -4% intraday from start-of-day, close largest losing position; repeat until back above -4%
- **Tested under FTMO 14-day rules**: pass +10%, fail -5% daily, fail -10% total

### Sandbox-track key findings (durable, even if specific scripts are thrown away)
1. **Universe filter is the single biggest lever for cost-survival** — wide-spread exotics destroy any tight-stop strategy. Spread/stop_distance ≤ 5% is a defensible cutoff.
2. **Active risk management beats both signal-design and sizing changes for FTMO survival** — converting "let trades run" into "liquidate before daily limit" was the dominant win.
3. **Decisive-outcome ratio (pass / (pass + fail)) is the meaningful metric for FTMO**, not raw pass rate. v2 baseline 67%, v2 `relax_10` 61%, `rr_2_tight` 89%. Higher P/(P+F) means fewer attempts wasted.
4. **Long-only signals are now structurally exposed to USD-strength regimes.** The next signal we add should be a real short with cost-survivable lift on the filtered universe; none of the 4 shorts tested in `sandbox_combinations.py` cleared the bar.
5. **Forward-window math depends on volatility regime**: 0.5%/0.75% on 4h with 14-day window is the highest-frequency profitable shape we found; 1%/2% (`rr_2_wide`) is most decisive per attempt but only fires 7.8 trades per 14d so most challenges time out.

### Memories saved this session
- `feedback_validate_incrementally.md` — formal capture of the "build the smallest validated subset before integrating" rule that drove this whole session.

### What this means for the BH FTMO Phase 3 gate
The 2026-04-27 gate failure (Baseline long-only, ASIA losses, AUD cluster) is now better understood as a *consequence* of integrating unvalidated components, not as five separate bugs. The right path back to the gate is to introduce the validated sandbox findings (signal universe, RR shape, risk-management overlay) into the BH FTMO production code path before re-running. This is **scope-larger than the `--strategies` flag** that was queued yesterday.

---

## What Was Done This Session (April 27)

### Doc-refresh sweep (Codex Next Actions, all merged)
Four sequential Next Actions refreshed all the planning docs against shipped Phase 3 reality:
- `5f7fc3b` SESSION_HANDOFF refresh for Phase 3 completion
- `4ce0070` BH_FTMO_PLAN — Phase 3 marked complete
- `f328161` FTMO_RULES §2 filled with verified Free Trial values (14-day, $100k, static DD, $0 commission, Europe/Prague tz)
- `d595c2b` TODO refresh for Phase 3 completion + new follow-ups

### Repo housekeeping
- Stale worktrees + feature branches pruned
- `.gitignore` extended (`94f3885`, `c20f244`) for `data/swap_rates_*.json`, `src/.codex`, `src/temp.txt`
- `merge_branch.sh` helper added (`c2577e5`) — `--no-ff` merge + safe (`-d`, lowercase) branch delete + optional push

### Dead-code removal (`1ea889c`)
- Removed `dollar_per_pip_per_lot` field from all 40 instrument entries in `bh_ftmo_config.json`. Investigation confirmed nothing reads it; `pip_value.py` (Phase 3) is the verified source of truth, and the JSON values were dead copies of the BH Lite suspect 10× values. **Closes the 🔥 PRIORITY block** that's been sitting at the top of TODO.md since April 24.

### First end-to-end Phase 3 gate run
Provisioned a c2-48vcpu-96gb DigitalOcean droplet (`bh-research`) at NYC3, rsynced repo + DuckDB store, kicked off `./run.sh python -m bh_ftmo.backtest.cli` inside a tmux session. Took five attempts to get a clean run because each attempt surfaced a different lurking engine bug:

1. `9f321e3` **rates-snapshot-bridge** — `_rates_snapshot_at` was being called with only the open-position symbols, leaving BFS in `quote_to_account_rate` unable to find currency bridges. Widened to `bars_4h.keys()` at all call sites.
2. `384f084` **cli-print-traceback** — `cli.py:440` was catching `FileNotFoundError`/`ValueError`/`KeyError` with a friendly handler that swallowed tracebacks. Split the catch so diagnostic exceptions print full tracebacks via `traceback.print_exc()`.
3. `eeb2225` **data-gap-filter** — `_bid_ask_snapshot_at` is strict (callers shouldn't act on unobservable positions). Added `open_symbols_with_data` / `open_positions_with_data` filtering at all callers in `engine.run_challenge` for the FX week-end Friday-21:00 UTC data gap.
4. `b34db4f` **rates-snapshot-tolerant** — `_rates_snapshot_at` is the rates *graph*, not a "specific symbol" lookup; it should silently skip symbols whose `bar_ts` isn't in their frame index. BFS walks whatever graph is present; if a critical bridge is missing, `quote_to_account_rate` raises a clear `ValueError`. Internal-skip fix; semantically distinct from the strict bid/ask-snapshot fix above.

Also fixed `/tmp/run_gate.sh` in place (set `-o pipefail` + `${PIPESTATUS[0]}`) to capture the actual gate exit code instead of `tee`'s.

### Gate verdict: FAILED
Run `bh_ftmo_gate_20260427_104629_5883064` — 13,538 trades over 30 walk-forward folds, all five gate criteria failed (Sharpe, PF, WR, MaxDD, pass-rate). HTML + CSV pulled to `src/graphs/` and `src/logs/`. Three structural findings on inspection:
- **Baseline appears long-only** — 0 short trades of 3,652 baseline trades. Likely a strategy-implementation bug, not weights.
- **ASIA session = 65% of losses** across all strategies (every strategy is structurally bleeding during low-liquidity hours).
- **AUD cluster concentration** — 41% of trades touch AUD; AUD trades are 59% of losses. Cluster filter may be under-suppressing.
- **Sharpe and Max DD mismatched** between per-strategy table (0.20 / 22.2%) and verdict block (-2.90 / 14.6%) — suggests reporter is computing on different equity-curve bases.

### Methodological pivot (Brand's call)
Composite testing of two strategies × 40 pairs × 30 folds masks individual-component bugs. Brand pushed back on patching the symptoms (filter ASIA, tighten cluster) and instead asked: **can we even guarantee that RSI / EMA / ADX are calculating correctly?** Answer: no — `src/bh_ftmo/indicators/` has zero unit tests in `src/tests/bh_ftmo/`, and the indicators are hand-rolled pandas/numpy implementations, not ports of equity-side `talib.RSI` / `talib.MACD` / `talib.ADX` calls. The math *looks* correct on inspection but several functions have known footguns (RSI/MACD/ADX seed-init differs from TA-Lib; SuperTrend's stateful loop is bespoke).

### Droplet teardown
`bh-research` destroyed via `/tmp/teardown.sh`, three known_hosts entries cleaned. Total cost: ~30 min × $0.69/hr ≈ $0.35.

### Indicator validation suite (4 Codex Next Actions, all merged)
Built out `src/tests/bh_ftmo/indicators/` from scratch. 92 tests across all 9 indicator modules; every module that has a TA-Lib equivalent is compared against it past a documented warmup window, every module without a TA-Lib equivalent is compared against hand-computed reference values on small inline fixtures.

- `5e962d8` momentum — RSI, MACD, Stochastic (vs TA-Lib `STOCHF` not `STOCH`), CCI, Williams %R. Established the shared `ohlc_fixture` (500 deterministic 4h bars) and the `_last_n_compare` helper. **Found:** RSI(14) needed `period * 12` warmup (~28 days of 4h) to converge within 1e-3 vs the suggested `period * 5` — Wilder seed-init mismatch with TA-Lib's SMA seed, decays geometrically.
- `ef31efc` trend + volatility — SMA, EMA, ADX, Donchian, SuperTrend, Ichimoku, true_range, ATR, atr_percent, Bollinger Bands. Hoisted `_last_n_compare` into conftest. **Found:** ATR converges much tighter than RSI at the same warmup (1.57e-09 vs 1e-3) despite the same seed math — its absolute-value range is ~1e-3, so absolute divergence at convergence is correspondingly tiny. **Confirmed:** TA-Lib's BBANDS uses population stddev (ddof=0), matching bh_ftmo. **SuperTrend hand-fixture re-walked** to match implementation's prior-bar-close carry-forward variant; the implementation is treated as spec since there's no TA-Lib reference.
- `ddb1923` candlestick + pivots + strength — anatomy helpers + 5 pattern detectors, classic pivot formula + day aggregation + weekend-rollover (Monday uses Friday's pivots), multi-pair currency strength meter. **Hand-verified:** `currency_strength` on a 3-pair scenario (EUR_USD +1%, EUR_JPY +2%, USD_JPY +0.5%) produced exactly the expected contributions (EUR=+0.015, USD=-0.0025, JPY=-0.0125).
- `a60a3c9` sessions + dxy_correlation + _common — Session enum + DST handling (paired summer/winter UTC bars, both classify as OVERLAP), CLOSED weekend labeling, session_ranges aggregation, DXY synthesis from 6 ICE constituents (identity case + sign-convention test on +1% EUR_USD), rolling DXY correlation, ohlc_mid + _require_ohlc.

All four merged. Suite runtime: <1 second. No xfails — every divergence found was either warmup-only (and waited out) or bounded by the documented seed-init pattern.

---

## Previous Sessions Summary

- **April 25:** BH FTMO Phase 3 (Backtesting Framework) sub-phases 3.0 → 3.5 shipped — 11 commits (`02d3234` → `e842d9a`). Bid/ask-aware simulator, FTMO rule enforcement (static + trailing DD), three null baselines, walk-forward fold harness, metrics + reporter, entry-edge gate, CLI driver. Companion design doc `docs/planning/PHASE_3_BACKTEST_ARCH.md` (20 P3-* decisions). Tests 1211 → 1396.
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

- **Sandbox-track validation of the 2-signal long-only forex portfolio.** Latest config (`relax_10`): 15.7% pass / 9.5% total-fail / 61.2% decisive ratio / +0.81% mean per challenge. All sandbox scripts in `/tmp/sandbox_*.py` and `/tmp/h1*.py`. Trade ledgers + equity curves preserved at `/tmp/sandbox_*_trades.csv`, `/tmp/sandbox_*_equity.csv`, `/tmp/sandbox_ftmo*_challenges.csv`.
- **`--strategies` CLI flag** previously top-of-queue is **deprioritized** — the per-strategy isolation question is largely moot because the sandbox track has shown both `BaselineStrategy` and `MeanReversionStrategy` as composed are likely chasing the wrong components. The flag is still cheap to land for future investigation but is no longer the next high-leverage move.
- BH FTMO Phase 3 framework + indicator validation suite remain shipped and useful; the *signal layer* is what's being rebuilt in the sandbox.

## Next Steps

**Immediate research-track work (highest leverage):**
1. **Pick a port-target for the sandbox findings.** Decision needed: do we (a) port the validated 2-signal portfolio + active-risk-mgmt overlay back into `bh_ftmo` production code as a new strategy class, or (b) keep iterating in `/tmp/` until we find a third signal (likely a real short) that lifts pass rate above the FTMO breakeven economic line? Brand to call.
2. **Find a cost-survivable short signal.** All 4 shorts tested in `sandbox_combinations.py` failed the universe-filter cost test. Need to widen the search: divergence patterns, regime-conditional shorts, short-only filtered universes, etc.
3. **Investigate `relax_10`'s 9.5% total-fail rate.** That's 88 challenges out of 925 hitting -10% even with active risk management. Audit those specific challenges to see whether they're salvageable with a tighter buffer multiplier (1.05 instead of 1.10) or signal a deeper structural problem.

**Pending Brand decision before any code lands in `bh_ftmo`:**
4. **Port-back vs. continue-iterating decision.** The sandbox track has produced a viable enough candidate that "ship something" is now a reasonable option. But it's still long-only and the daily-fail cliff is barely 1pp away from hard-limit failures. Both options are defensible.

**Lower priority / inherited from yesterday:**
5. **`--strategies` CLI flag** — Codex Next Action drafted on branch `cli-strategies-flag` (see `/tmp/nextaction.md`). Cheap to land but no longer urgent.
6. **Investigate Baseline long-only bug** (0 short trades of 3,652 in the 2026-04-27 gate run). Less urgent now that the sandbox track has identified that the production strategy composition itself is suspect.
7. **Investigate Sharpe/MaxDD mismatch in reporter** — per-strategy table 0.20/22.2% vs verdict block -2.90/14.6%. Low-effort fix once spotted.

**Brand action items (still open from prior sessions):**
- Run `bash /tmp/humanaction.sh` to install every-4h incremental-update cron (when re-emitted; the slot has been used for sandbox-track work this session)
- Install GitHub App before May 8 so `trig_01RfvYoMo6V7bETCRBLn5WNT` (BH FTMO check-in routine) can run
- SMTP from Claude Code sandbox is blocked — Brand runs `send_report_email.py` manually for equity reports

**Deferred:**
- **Phase 2c — Indicator Tuning** stays deferred. The sandbox track is producing better signal-validation feedback than walk-forward weight optimization on the existing strategy classes would.
- See `TODO.md` for full backlog and `docs/planning/BH_FTMO_PLAN.md` for the locked plan.

## Blockers / Open Questions

- **SMTP from Claude Code sandbox is blocked** — Brand must run `send_report_email.py` manually for equity reports
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
**Working tree:** docs updated this session (SESSION_HANDOFF.md, TODO.md). All sandbox/ research scripts live in `/tmp/` and are not committed — they are deliberately disposable; only the methodology + findings should land back in `bh_ftmo`.
**Active feature branches:** `cli-strategies-flag` (deprioritized per pivot above)
**This session's commits:** None — all research output is in `/tmp/` artifacts. Doc updates pending Brand commit approval.
**Prior session's commits (April 27):** `5f7fc3b`, `4ce0070`, `f328161`, `d595c2b` (doc-refresh sweep), `c2577e5` (merge_branch.sh), `94f3885`, `c20f244` (.gitignore), `1ea889c` (dead-field cleanup), `9f321e3`, `384f084`, `eeb2225`, `b34db4f` (engine bug fixes), `feb6d2a` (RSI seed-init follow-up note), `5e962d8`, `ef31efc`, `ddb1923`, `a60a3c9` (indicator validation suite)
**Phase 3 commits (April 25):** `02d3234`, `68a169c`, `e7e1503`, `7541516`, `c49ab49`, `418d214`, `d2052bd`, `1d93201`, `9844244`, `5b50d57`, `e3af17a`, `e842d9a`
**Tests:** 1396 prior + 92 new BH FTMO indicator tests = 1488 BH-side tests. All green when run via `./run.sh pytest src/tests/bh_ftmo/ -q`. Equity-side requires Docker for MongoDB; works from Brand's shell, blocked from Codex sandbox.

---

**Last Updated:** April 28, 2026
