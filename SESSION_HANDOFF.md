# Session Handoff

**Date:** March 31, 2026
**Status:** MR weight experiment attempted and reverted. Baseline weight tuning complete. Arcade report improvements shipped. Email delivery fixed. Falling knife filter added.

---

## What Was Done This Session (March 29-31)

### 1. MR Weight Tuning Experiment (bh-research droplet)

Recovered research data from crashed session on droplet `161.35.178.128`. The previous session had:
- Created a +1/-1 "baseline" for MR weights based on indicator directionality
- Tested individual category multipliers (trend, momentum, volume, specific, curve)
- Found `mr_specific_3x` was the best single lever for bearish EV (+1.37%)

**This session extended the research:**
- Tested `mr_curve` at 5x, 10x, 20x, 30x — signal saturates between 3x and 5x (identical results 5x through 30x)
- Tested combo `spec3x + curve5x` — worse than spec alone (+1.04% vs +1.37%)
- Tested blend approach (top-5 from each signal) — also worse (+0.96%), despite only 1.3/5 overlap per date
- **Deployed optimized weights to production → caught falling knives (GOOG, GLAD in freefall)**
- Root cause: `mr_mean_reversion_specific` at 6.0 contributed up to 96 points, drowning all other indicators
- **Reverted to pre-experiment production weights** — known-good values back in place

**Key lesson:** The assumption tester optimizes for "most oversold = best" because backtests capture the bounce mechanically. But in real trading, deeply oversold stocks may still be falling. Weight changes must be validated against qualitative checks, not just EV numbers.

### 2. Baseline Weight Tuning (bh-research droplet)

Ran full category-by-category tuning with uniform 1.0 baseline as control:

| Config | BL Bullish EV | BL Bearish EV |
|--------|---------------|--------------|
| baseline_1x (control) | **+0.116%** | +0.675% |
| trend_2x | +0.114% | +0.609% |
| trend_0.5x | -0.069% | +0.664% |
| momentum_2x | -0.053% | **+0.897%** |
| momentum_0.5x | +0.084% | +0.658% |
| volume_2x | +0.062% | +0.624% |
| candlestick_2x | -0.046% | +0.441% |
| price_action_2x | +0.107% | +0.706% |
| curve_10x | +0.116% | +0.675% |

**Findings:**
- Uniform 1.0 is optimal for bullish — no category boost improves it
- Momentum_2x is best for bearish (+0.90%, 31% win rate) but kills bullish
- Curve at 10x identical to 1x (same saturation as MR)
- Baseline has real edge in bearish markets too (+0.67-0.90%), challenging the "BL=bullish only" assumption
- Decision: Run both strategies in all regimes, let scores sort it out

### 3. Arcade Report Improvements

- **Half-quantity display** — Portfolio QTY column now shows shares/2 (per bracket leg), header labeled "QTY/2"
- **Right-aligned numeric columns** — All portfolio table numbers right-aligned for readability
- **Removed standalone CALC button** — Toolbar CALC button removed (opened empty calculator). Per-symbol "CALC SHARES" buttons on cards retained.

### 4. Falling Knife Filter

Added `calculate_falling_knife()` to `mean_reversion_indicators.py`:
- Returns -5.0 if last 2 candles both closed below open
- Wired into MR scoring only (not baseline) via `_calculate_mean_reversion_modifiers()` in `technical_analyzer.py`
- Appears as `penalty_falling_knife` in score components
- **Note:** The -5.0 penalty is insufficient against inflated mr_specific scores. Adequate with the reverted (original) weights.

### 5. Email Delivery Fix

- **Root cause:** Docker→host migration left SMTP credentials in `docker/.env` but not root `.env`. Also, Gmail SMTP was configured but DigitalOcean blocks SMTP ports. Brevo credentials (from `docker/.env`) work on port 2525.
- **Fixed:** Updated root `.env` with Brevo SMTP settings
- **Fixed:** Added `.env` sourcing to `run.sh` (handles unquoted values with spaces)
- **Fixed:** Added `.env` sourcing to `run_daily_pipeline.sh` (same pattern)
- **Refactored:** `email_service.py` extracted `_build_report_email()` helper

### 6. Codex Workflow

- Established "make it so" shorthand — user says this to mean "write to /tmp/nextaction.md"
- Codex venv setup instructions provided (one-time: `python3 -m venv .venv && pip install -r requirements.txt`)

---

## Previous Sessions Summary

- **March 27:** Assumption tester built, regime-aware stop/target multipliers, Docker→host migration
- **March 23:** Trade journal system (5-phase lifecycle)
- **March 19-22:** Curve/motif analysis, CNN Fear & Greed, AAII sentiment
- **March 15:** Finviz sentiment, z-score normalizer, arcade report, VIX, StockTwits, Tiingo News
- **March 9:** Pluggable strategy interface
- **March 7-8:** DuckDB migration, new indicators (RVOL, Engulfing, Hammer)
- **March 5-6:** Vectorized backtesting, score-once backtest refactor

---

## In Progress

- **Codex branch sync** — `origin/codex-refactor` has `65219c6 Load env for daily pipeline` that needs merging to master
- **Research droplet** (`161.35.178.128`) — All tuning runs complete. Data preserved in `src/research/bl_tuning_*` and `src/research/tuning_*` directories

## Next Steps

1. **Merge codex-refactor** — Pipeline env fix needs to land before tonight's cron run
2. **MR weight strategy rethink** — The +1/-1 baseline approach produced falling knives. Need a different approach:
   - Option B (average instead of sum for mr_specific aggregation) was discussed but not tested
   - Consider capping mr_specific contribution (Option A)
   - Consider gating on trend/momentum confirmation (Option D)
   - Whatever approach is chosen, **validate with assumption tester before deploying**
3. **Validate falling knife filter effectiveness** — The -5.0 penalty works with current weights but was insufficient with inflated mr_specific. May need scaling.
4. **Baseline weights decision** — Uniform 1.0 is optimal for bullish. Current production has non-uniform weights. Consider testing current production weights through assumption tester vs uniform 1.0 to decide if a change is warranted.
5. **Run prediction and email** — `./run.sh python src/send_report_email.py` to send today's report

## Blockers / Open Questions

- **MR weight optimization is unresolved** — The experiment showed real signal (mr_specific_3x had +1.37% bearish EV) but the scoring system amplifies it into falling knife territory. Need to find a way to capture the signal without the dominance problem.
- **SMTP from sandbox is blocked** — User must run `send_report_email.py` manually from their shell. The daily cron pipeline will work once the env fix is merged.
- **TO-DO item to validate mr_curve at 5.0** — This was added but is now moot since weights were reverted. Update TODO.md when MR weights are revisited.

---

## Key Decisions

- **Run both strategies in all regimes** — Don't gate MR in bullish or BL in bearish. Let scores naturally surface the best picks. User can see strategy labels in the report and apply judgment.
- **Reverted MR weights to pre-experiment values** — The +1/-1 baseline research was valid directionally but the magnitude was wrong. Deploying untested weight combinations to production was premature.
- **Uniform 1.0 is the Baseline weight answer** — No single category boost improves bullish EV. The indicators are naturally well-balanced for trend-following.
- **Email via Brevo on port 2525** — Gmail SMTP blocked by DigitalOcean. SendGrid key is stale. Brevo works.
- **Falling knife filter: 2 red candles = -5.0 penalty** — Conservative threshold per user preference. MR-only, not applied to baseline.

---

## Key Files

| File | Role |
|------|------|
| `src/weights.json` | Indicator weights — MR reverted to pre-experiment values |
| `src/bluehorseshoe/analysis/indicators/mean_reversion_indicators.py` | Falling knife filter added here |
| `src/bluehorseshoe/analysis/technical_analyzer.py` | `_calculate_mean_reversion_modifiers()` wires knife filter |
| `src/bluehorseshoe/core/email_service.py` | Refactored, SMTP-only delivery |
| `src/bluehorseshoe/reporting/html_reporter.py` | QTY/2, right-align, removed standalone CALC |
| `run.sh` | Now sources `.env` |
| `run_daily_pipeline.sh` | Now sources `.env` (pending merge) |
| `.env` | Updated with Brevo SMTP credentials |
| `docker/.env` | Source of truth for Brevo credentials (was missing from root `.env`) |

### Research Droplet (`161.35.178.128`)

| Directory | Contents |
|-----------|----------|
| `src/research/tuning_*` | MR weight tuning runs (baseline_1x through combo_spec2x_curve2x) |
| `src/research/tuning_mr_curve_*` | MR curve multiplier tests (3x, 5x, 10x, 20x, 30x) |
| `src/research/tuning_combo_spec3x_curve5x` | Combo test |
| `src/research/tuning_blend_spec3x_curve5x` | Blend analysis (post-hoc, no Phase 1) |
| `src/research/tuning_optimal` | Final MR run from previous session |
| `src/research/bl_tuning_*` | Baseline weight tuning runs (all categories) |
| `src/research/tuning_results.csv` | MR tuning summary CSV |

---

### Production Commands (Host)
```bash
./run.sh python src/main.py -p                          # Prediction (~60 min)
./run.sh python src/main.py -u                          # Data update (~30 min)
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
**Working tree:** Clean
**Codex branch:** `origin/codex-refactor` — 1 commit ahead (pipeline env fix, needs merge)
**Tests:** 685+ passing

---

**Last Updated:** March 31, 2026
