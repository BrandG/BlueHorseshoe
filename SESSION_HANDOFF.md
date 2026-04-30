# Session Handoff

**Date:** April 29-30, 2026
**Status:** **Sandbox-validated package landed in production, then FAILED the full walk-forward gate at 2.5% pass rate.** The 0/37 package-smoke result was NOT small-sample noise — full-fold gate (16 folds, 202 starts) on a clean droplet returned a verdict of FAILED across all six metrics: Sharpe -1.33, profit factor 0.84, win rate 36.6%, MaxDD 12.4%, FTMO pass-rate (lower 95% CI) **2.5%** (statistically tied with random_baseline at 2.5%), margin vs best baseline only +3.0pp. **Sandbox_v1 deployment is blocked** until the forecast-vs-gate gap is understood (lookahead leakage in the sandbox notebook? port introduced subtle differences? methodology mismatch?). BH Lite remains the only strategy with live evidence. Production signal-emission CLI was completed earlier in the day (4 commits across the day landed the port: `535a598` SandboxStrategy, `a0a930c` worker-cap fix, `a65d1ba` universe filter, `3be9463` active risk overlay; predict CLI `4797a57`). Predict cron is installed and emailing every 4 hours, so the live signal feed flows — but until the forecast-gap investigation gives a reason to trust those signals, treat the emails as research data, not actionable. Brand purchased the $99 unlimited-time 2-Step Swing 10k FTMO challenge earlier in the day and is now on hold from activating it. Total validation-run cost: ~$0.30 in droplet time — caught the issue before paying any FTMO challenge fee.

---

## What Was Done This Session (April 29-30)

### Late-evening / overnight: full walk-forward gate on droplet — VERDICT: FAILED

Pulled the trigger on the on-demand droplet validation run that the prior block had queued to settle the 0/37 question. Provisioned `bh-research` (`s-8vcpu-16gb`, ~$0.143/hr), bootstrapped natively (no Docker — apt + TA-Lib from source + venv + pip), rsynced the 298MB OANDA H4 DuckDB, ran `--strategies sandbox_v1` with all walk-forward folds + starts unlimited.

The run completed in ~36 minutes (16 folds, 202 starts, 4 workers). Verdict block:

```
 Sharpe (annualized, 1h basis):     -1.33  (≥ 1.00)    FAIL
 Profit factor:                      0.84  (≥ 1.30)    FAIL
 Win rate:                          36.6%  (≥ 45.0%)   FAIL
 Max drawdown:                      12.4%  (≤ 10.0%)   FAIL
 FTMO pass-rate (lower 95% CI):      2.5%  (≥ 70.0%)   FAIL
 Margin vs best baseline:          +3.0pp  (≥ 10.00)   FAIL
                                   (best baseline: random_baseline @ 2.5%)
```

The killer line: **pass rate 2.5%, statistically tied with a random baseline at 2.5%.** So the 0/37 package smoke was the real signal, not small-sample noise. Material gap from the sandbox track's 12-14% forecast — explanations to investigate: (a) lookahead leakage or other methodology issue in the sandbox notebook; (b) the port introduced subtle differences from the sandbox harness; (c) the gate's evaluation methodology differs from sandbox's scoring.

Cost: ~$0.30 in droplet time. Artifacts pulled to `src/graphs/sandbox_v1_full_2026-04-29_2311.html`, `src/logs/sandbox_v1_full_2026-04-29_2311.csv`, `src/logs/sandbox_v1_full_2026-04-29_2311.log`. Droplet destroyed.

**Operational lessons logged for future droplet work:**
- The original `humanaction.sh` swallowed stderr on the TA-Lib build step (`> /dev/null 2>&1` on `make`), so it failed silently and Brand's terminal showed nothing. The droplet sat idle for 2+ hours before we noticed during a status check. The recovery script (`/tmp/bh-bootstrap-resume.sh`) showed stderr properly. Future bootstrap scripts: never silence stderr on the long opaque build steps.
- The cron install in `/tmp/humanaction.sh` (and a parallel inline install I did) both initially dropped the `cd /root/BlueHorseshoe &&` prefix from the cron line, causing the first 20:15 UTC fire to hit `./run.sh: not found`. Fixed via sed; subsequent fires worked. Future cron lines that invoke `./run.sh`: the `cd` prefix is mandatory because cron's CWD isn't `$HOME`.
- The droplet bootstrap also needs OANDA credentials (`OANDA_API_TOKEN` + `OANDA_ACCOUNT_ID`) — the original bootstrap script didn't push a `.env` file, so the gate aborted on first launch with "OANDA_API_TOKEN is not set". Folded a minimal 2-line `.env` push into the recovery sequence. Future versions of `humanaction.sh` should include an `.env` push step (just OANDA lines, not SMTP/AlphaVantage etc.).

### Predict cron installed and verified (afternoon)

After predict CLI landed, installed the every-4h cron (`15 */4 * * *` UTC = 6 emails/day). First scheduled fire at 20:15 UTC failed because the cron line dropped the `cd` prefix — sed-fixed in place. Manual run with the corrected invocation succeeded and emailed a real 1-signal report (GBP_CAD long, $100 risk, 0.29 lots). Subsequent cron fires expected to work normally; next is 04:15 UTC (will be the first true cron-triggered email).

HTML report formatting was iterated on — the report originally had Gmail-stripped CSS (no borders, merged columns) because the styles were in a `<style>` block and Gmail's renderer drops most of those plus pseudo-selectors like `:nth-child`. Rewrote `render_html` in `predict.py` to inline every style attribute on each cell directly — fixed Gmail rendering. Visible improvements: cell borders, dark-blue header row, alternating zebra stripes, right-aligned numeric columns with tabular-nums, centered uppercase Direction column, breathing-room padding.

### Production port: 4 commits, package validated end-to-end (afternoon-evening)

After the morning's sandbox validation finalized, executed the porting sequence to land the validated package in production code.

**Commits, in landing order:**

1. `535a598` **SandboxStrategy port** (merged via `deac0b5`) — `src/bh_ftmo/analysis/sandbox_strategy.py` with the 3 event-based rules + 4-pair short whitelist; 7 unit tests; `sandbox_v1` block in `bh_ftmo_weights.json`; `--strategies sandbox_v1` CLI flag. Codex's first attempt at this NA crashed mid-run when the user got disconnected; second attempt reran from a fresh nextaction.md and committed cleanly.

2. `a0a930c` **Worker-cap fix** — cap sandbox_v1 default workers at 2 to avoid OOM on this 7.8 GB host. Diagnosed via kernel OOM trace after a prior session lost a Codex tab to a self-inflicted OOM (concurrent `--max-workers 2` and `--max-workers 4` runs exceeded RAM and systemd SIGKILLed the entire tmux-spawn cgroup, taking out bash, node, and codex). Fix: `_resolve_max_workers` in `cli.py` defaults sandbox_v1 to `max_workers=2` when no `--max-workers` is passed.

3. `a65d1ba` **Universe filter** (merged via `6c7ef1c`) — new `src/bh_ftmo/backtest/universe_filter.py`, opt-in per strategy via `universe_filter` config block, applied at cli.py before signal generation. 7 unit tests + 1 real-data integration test (skips when DuckDB unavailable). On current OANDA data, 21/40 pairs dropped (sandbox said 22; 1-pair drift is current-data variance in the 30-day lookback). Filter solo-edge confirmed: win rate 31.7% → 35.0%, profit factor 0.70 → 0.81, FTMO breaches 15 → 7 across 37 challenges.

4. `3be9463` **Active risk overlay** (merged via `ed49ef1`) — `src/bh_ftmo/backtest/risk_overlay.py` with entry restraint + intraday liquidation cascade, opt-in via `risk_overlay` weights block, integrated into `engine.run_challenge`. 8 unit tests + 2 engine integration tests including the regression test (overlay-disabled bit-identical to pre-overlay). The first smoke test on the unfiltered universe showed the overlay regressing every metric (Sharpe -3.30 vs -2.87, MaxDD 11.8% vs 10.8%, FTMO breaches 20 vs 15) — likely cause: on cost-killer pairs the overlay turns probabilistic recoveries into deterministic spread-cost realized losses. Held as WIP commit on branch (`fdf5576`, then rebased to `3be9463` after filter merge) per `feedback_validate_incrementally.md`. Package smoke (filter + overlay) on filtered universe confirmed zero FTMO breaches across 37 challenges.

**Package smoke comparison summary (same 37 challenges, same RNG seed):**

| Config | FTMO breaches | Win rate | Profit factor | MaxDD | Sharpe |
|--------|--------------:|---------:|--------------:|------:|-------:|
| Both off | 15 | 31.7% | 0.70 | 10.8% | -2.87 |
| Filter only | 7 | 35.0% | 0.81 | 12.1% | n/a |
| **Package** | **0** | **36.5%** | **0.88** | 11.3% | **-0.40** |

### Reporter MaxDD vs FTMO breach discrepancy (worth noting, already on TODO)

Package smoke shows MaxDD 11.3% in the verdict block but **zero** FTMO breach exits in the trade ledger. These metrics measure different things — `ftmo_breach` is the engine's check against per-day buffer / total balance limits in real time, while reporter MaxDD is peak-to-trough on the equity curve which captures intraday lows the overlay later liquidates out of. The TODO item about reporter Sharpe/MaxDD computing on different bases (line 231) is the same family of issue. Worth investigating but does NOT invalidate the breach-count finding — for FTMO survival, breach count is the operative metric.

### ~~Open question: 0% pass rate on 37 challenges~~ — **RESOLVED: real signal, not noise**

Sandbox forecast was 12-14% pass rate on full walk-forward (925 challenges). At that rate, 37 challenges expects 4-5 passes. We got 0. Three possibilities listed at the time: small-sample bad luck (P(0 passes | p=0.13, n=37) ≈ 0.6%, improbable but not impossible), tough-regime sample, or production code has lower expected value than sandbox. **Resolved by the late-evening droplet gate run**: 202-start full walk-forward returned a 2.5% pass-rate (lower 95% CI), statistically tied with random_baseline at 2.5%. So it's not bad luck and it's not a tough sample — the production code's expected pass rate genuinely sits near zero, far below the sandbox's 12-14% forecast. The forecast-vs-gate gap investigation is the new open question; see top of this file and the late-evening entry above.

### FTMO challenge purchased — 2-Step Swing 10k

Brand purchased the $99 unlimited-time 2-Step Swing 10k challenge. Swing exempts funded-stage weekend/news restrictions, downgrading the "Engine: weekend-flatten architecture" TODO from "should land before Phase 4" to "nice to have" for FTMO compliance (still useful for general gap-risk management). Memory saved at `project_ftmo_challenge.md`.

### Paper-derived TODO additions

After Brand shared a research paper on FTMO pass strategies, three items added to BH FTMO follow-ups:
- **Backward-looking risk circuit breakers** — daily realized-loss cutoff + N-consecutive-losses circuit breaker. Paper's strongest tactical insight ("stop after 2 bad trades / 1.5% realized loss") is genuinely absent from our overlay (which is purely forward-looking). Sandbox-validate first per validate-incrementally rule.
- **Risk-per-trade tightening sweep** (1% → 0.5% with tighter targets) — paper recommends 0.25-0.5%, we use 1%. Lower priority; only run if 1% feels too aggressive in live.
- **OANDA demo forward-test rehearsal** — ≥5 trading days on demo before activating paid challenge. Paper's most-repeated cheap-edge.

### Walk-forward (G), short-hunt (F), buffer sweep (H) — all complete
After committing the April 28 doc updates (commit `e21bc95`), executed Brand's G→F→H plan from yesterday:

**(G) Long-signal pair-restriction test — REJECTED.** Applied the same 3-way temporal pair-validation methodology to `stoch_oversold` and `sma_cross_long` that worked for `rsi_overbought`. Both longs failed the test:
- `stoch_oversold`: train +0.145 → test -0.016 (only 41% of train-selected pairs persisted)
- `sma_cross_long`: train +0.234 → test -0.009 (54% persisted)
- All-pairs version is BETTER than train-selected version for both longs

Interpretation: the longs are broad-regime signals (work everywhere, modulated by global regime), not pair-specific. Pair restriction is overfitting noise. **Conclusion: longs stay on all 18 pairs.**

**(F) Hunt for additional cost-survivable shorts.** Tested 6 short candidates (4 originals re-tested on filtered universe + 2sigma_above, ma20_rejection, failed_breakout, strong_bear_bar, macd_hist_rollover, double_top) using the singleton sandbox harness, then 3-way temporal validation on the survivors:

| Candidate | All-pair avg_R | 3-way validated pairs |
|---|---|---|
| `rsi_overbought_cross` | +0.032 | **4 pairs** (CAD_JPY, EUR_NOK, USD_CAD, USD_CHF) — held in test |
| `bb_upper_fade` | +0.006 | 3 pairs (EUR_AUD, USD_NOK, USD_ZAR) — held in test |
| `2sigma_above` | -0.007 | 1 pair only |
| `ma20_rejection` | -0.028 | 1 ultra-pair, but failed test |
| `macd_hist_rollover` | -0.008 | 1 pair only |
| `failed_breakout` | -0.027 | 0 validated pairs |
| `shooting_star`, `bearish_engulfing` | < 0 | <2 stable pairs |

Then ran a 4-signal portfolio test (longs + rsi_overbought + bb_upper_fade) at FTMO challenge mode. **The two shorts are correlated** — both fire on overbought conditions, both lose if overbought extends. Adding bb_upper_fade dropped decisive ratio from 66.9% → 63.6% (worse) and lifted total-fail from 8.2% → 9.4%. **Verdict: rsi_overbought is the only second signal that adds value.**

**(H) Buffer multiplier sweep — buf 1.10 confirmed.** Swept buffer_mult ∈ {1.00, 1.10, 1.20, 1.30, 1.50}:

| buffer | pass | fail_t | P/(P+F) | meanR% |
|---|---|---|---|---|
| 1.00 | 14.6% | 5.3% | 71.8% | +1.13% |
| **1.10** (current) | 17.3% | 8.2% | 66.9% | **+1.19%** |
| 1.20 | 18.2% | 8.0% | 67.2% | +1.04% |
| 1.30 | 19.5% | 10.3% | 64.7% | +1.08% |
| 1.50 | 19.6% | 10.1% | 61.1% | +0.97% |

Three different "best" depending on what you optimize: buf 1.00 maximizes decisive ratio (71.8%); buf 1.10 maximizes mean return per attempt; buf 1.30+ maximizes raw pass rate. **Buf 1.10 wins on $-EV per attempt** — keep it.

### Walk-forward stability test — PASSED with shrinkage
Two non-overlapping 12-month walk-forward windows on the 3-year data:

| Window | Config | Pass | Fail_t | Decisive | meanR% |
|---|---|---|---|---|---|
| WF1 (test 2024-05→2025-05) | baseline_2sig | 14.0% | 9.3% | 60.0% | +0.69% |
| | 3sig_train_selected (dynamic) | 14.6% | 14.0% | 51.2% | +0.44% |
| | **3sig_IS_champion (4 hardcoded pairs)** | **14.3%** | **7.6%** | **65.2%** | **+1.15%** |
| WF2 (test 2025-05→2026-05) | baseline_2sig | 11.4% | 7.7% | 59.6% | +0.24% |
| | 3sig_train_selected (dynamic) | 9.7% | 7.0% | 58.0% | +0.47% |
| | **3sig_IS_champion (4 hardcoded pairs)** | **12.0%** | **7.7%** | **61.0%** | **+0.46%** |

**Three findings:**
1. **Strategy holds OOS with expected ~30% shrinkage** — pass rate goes from 17.3% IS to 14.3% (WF1) and 12.0% (WF2). True forward expectation: 12-14% pass.
2. **The 4-pair "ultra-validated" set is the most robust selection** — beats dynamically re-selecting pairs each window on both walk-forward periods. The dynamic train-selected set in WF1 included EUR_USD, EUR_SEK, USD_HUF that turned out to be noise (hurt fail_t from 7.6% → 14.0%). **Conclusion: keep CAD_JPY, EUR_NOK, USD_CAD, USD_CHF as a fixed selection.**
3. **The short's lift holds OOS** — IS-champion mean return beats baseline by +0.34pp average across windows, very close to the in-sample +0.38pp (1.19 - 0.81). The short signal is structurally additive, not period-specific.

Honest forward-expectations for production (post-walk-forward):
- Pass rate ~12-14%
- Mean return per challenge ~+0.5% to +1.0%
- Decisive ratio ~60-65%
- Daily-fail rate ~0.3%, total-fail rate ~8-10%

Still positive-EV per attempt, just not as juicy as the in-sample +1.19% headline.

### Codex Next Action drafted: port SandboxStrategy back to bh_ftmo
Branch `port-sandbox-v1-strategy` created from master (not checked out, per the one-worktree-per-branch rule). Next Action at `/tmp/nextaction.md` covers **just the strategy class** (a Codex-sized piece):

- New `src/bh_ftmo/analysis/sandbox_strategy.py` — `SandboxStrategy` class with the 3 event-based rules
- New `src/tests/bh_ftmo/test_sandbox_strategy.py` — 7 unit tests
- New `sandbox_v1` block in `src/bh_ftmo_weights.json` — defaults + 4-pair whitelist
- Extend the existing plural `--strategies` flag in `src/bh_ftmo/backtest/cli.py` to accept `sandbox_v1` (NA originally proposed a competing singular `--strategy` flag; revised after Codex flagged that the plural list-style flag was already merged via `d25f276`)
- Export from `src/bh_ftmo/analysis/__init__.py`

Two things explicitly **deferred to a follow-up Next Action**:
- **Active risk management overlay** (entry restraint + intraday liquidation at -4%) — engine-touching, warrants its own scoped change
- **Universe filter** (drop pairs where spread > 5% of stop distance) — also engine-level, will land with the risk overlay

The split is deliberate: landing the strategy first lets us run the gate with `--strategies sandbox_v1` and see how much of the in-sample edge comes from the strategy itself vs. the active risk management. That's a useful diagnostic for the second NA.

### Sandbox track final state
All artifacts preserved at `/tmp/sandbox_*.py` (do not delete until the port-back lands). Final validated portfolio:

| | |
|---|---|
| Signals | `stoch_oversold` (long, 18 pairs) + `sma_cross_long` (long, 18 pairs) + `rsi_overbought` (short, **4 ultra-validated pairs**: CAD_JPY, EUR_NOK, USD_CAD, USD_CHF) |
| Timeframe | H4 |
| RR | 0.5% stop / 0.75% target = 1.5R |
| Sizing | 1% equity per trade, max 5 concurrent, 1 per pair |
| Active risk mgmt | Entry restraint (buffer × 1.10), intraday liquidation at -4% |
| Universe | 18 pairs (spread/stop_distance ≤ 5%) |
| In-sample pass | 17.3% / OOS 12-14% |
| In-sample meanR | +1.19% / OOS +0.5-1.0% |

---

## What Was Done This Session (April 28)

**Date:** April 28, 2026
**Summary:** Methodological pivot day — paused integrated Phase 3 gate work and built a parallel ground-up sandbox validation track in `/tmp/sandbox_*.py`. Outcome of the day: a 2-signal long-only forex portfolio (`stoch_oversold_cross` + `sma_cross_long` at 4h, 0.5%/0.75% RR, 18-pair filtered universe) that's clearly net-positive in challenge expectation when paired with active intraday risk management. **Best config:** `relax_10` — pass rate 15.7%, total fail 9.5%, decisive-outcome ratio 61.2%, mean +0.81% per challenge attempt. **The single biggest mechanical lever was active risk management** — adding intraday liquidation + entry restraint converted the 30% daily-fail rate to 0.9% with only a 1.8pp drop in pass rate.

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

- **Codex Next Action: port `SandboxStrategy` to `bh_ftmo`** — branch `port-sandbox-v1-strategy` created (not checked out per the one-worktree-per-branch rule), Next Action drafted at `/tmp/nextaction.md` and revised after Codex flagged a CLI-flag scope conflict. Adds `SandboxStrategy` class + tests + `sandbox_v1` weights config; extends the existing plural `--strategies` flag to accept `sandbox_v1` (no new singular flag). Awaiting send to Codex.
- **Two follow-up Next Actions queued (post-strategy-class):**
  - Active risk-management overlay (entry restraint + intraday liquidation at -4%) — engine-touching, will require modifications to `engine.py`, `position.py`, `ftmo_rules.py`
  - Universe filter (drop pairs where spread > 5% of stop distance at the configured RR shape) — engine-level decision, will land with the risk overlay
- BH FTMO Phase 3 framework + indicator validation suite remain shipped and useful; the *signal layer* is what's being rebuilt via the sandbox.

## Next Steps

**Immediate (this session's port-back):**
1. **Send Next Action to Codex.** Branch `port-sandbox-v1-strategy` and prompt at `/tmp/nextaction.md`. Awaiting Brand's go-ahead.
2. **Once landed: smoke-test gate with `--strategies sandbox_v1`** (no risk overlay yet). Useful diagnostic for how much of the in-sample edge comes from the strategy itself vs. the active risk management.
3. **Draft NA #2: active risk-management overlay.** New `src/bh_ftmo/backtest/risk_overlay.py`, plus integration hooks in `engine.py`. After this lands, run a full per-strategy gate (`--strategies sandbox_v1` + active risk overlay) to compare against the `/tmp/` sandbox numbers.
4. **Draft NA #3: universe filter at the engine level.** Drop pairs where `spread / (stop_pct × median_price) > 0.05` from the runnable universe. Modifies `runner.py` or `cli.py` and adds a config option in `bh_ftmo_weights.json`.

**Lower priority / inherited:**
5. **Investigate Baseline long-only bug** (0 short trades of 3,652 in the 2026-04-27 gate run). The sandbox track suggests the prod baseline composition itself is suspect; once `sandbox_v1` is producing clean numbers we can decide whether to fix the prod baseline or retire it.
6. **Investigate Sharpe/MaxDD mismatch in reporter** — per-strategy table 0.20/22.2% vs verdict block -2.90/14.6%. Low-effort fix once spotted.

**Brand action items (still open from prior sessions):**
- Run `bash /tmp/humanaction.sh` to install every-4h incremental-update cron (when re-emitted; the slot has been used for sandbox-track work this session)
- Install GitHub App before May 8 so `trig_01RfvYoMo6V7bETCRBLn5WNT` (BH FTMO check-in routine) can run
- SMTP from Claude Code sandbox is blocked — Brand runs `send_report_email.py` manually for equity reports

**Deferred:**
- **Phase 2c — Indicator Tuning** stays deferred until the `sandbox_v1` gate produces a passing verdict.
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
**Working tree:** docs updated this session (SESSION_HANDOFF.md, TODO.md). All sandbox/ research scripts live in `/tmp/` and are not committed — they are deliberately disposable; only the methodology + findings should land back in `bh_ftmo` via the queued Next Actions.
**Active feature branches:**
- `port-sandbox-v1-strategy` — created today (April 29), Codex Next Action drafted at `/tmp/nextaction.md`, awaiting send
- `cli-strategies-flag` — already merged (commit `d25f276` on April 27); branch deleted. Note added here because earlier handoff entries listed it as deprioritized/queued, which was stale.
**Prior session's commits (April 28):** `e21bc95` (docs: capture sandbox-track signal validation pivot)
**Prior session's commits (April 27):** `5f7fc3b`, `4ce0070`, `f328161`, `d595c2b` (doc-refresh sweep), `c2577e5` (merge_branch.sh), `94f3885`, `c20f244` (.gitignore), `1ea889c` (dead-field cleanup), `9f321e3`, `384f084`, `eeb2225`, `b34db4f` (engine bug fixes), `feb6d2a` (RSI seed-init follow-up note), `5e962d8`, `ef31efc`, `ddb1923`, `a60a3c9` (indicator validation suite)
**Phase 3 commits (April 25):** `02d3234`, `68a169c`, `e7e1503`, `7541516`, `c49ab49`, `418d214`, `d2052bd`, `1d93201`, `9844244`, `5b50d57`, `e3af17a`, `e842d9a`
**Tests:** 1396 prior + 92 new BH FTMO indicator tests = 1488 BH-side tests. All green when run via `./run.sh pytest src/tests/bh_ftmo/ -q`. Equity-side requires Docker for MongoDB; works from Brand's shell, blocked from Codex sandbox.

---

**Last Updated:** April 29, 2026
