# Session Handoff

**Date:** April 2, 2026
**Status:** MR weight tuning resolved (cap_8 deployed). Baseline tuning complete (no changes needed). Email fixed. Docker cleanup done. System stable and producing good predictions.

---

## What Was Done This Session (March 29 – April 2)

### 1. MR Weight Tuning Experiment

Recovered research data from crashed session on droplet `161.35.178.128`. Ran extensive weight tuning:

- Tested `mr_mean_reversion_specific` at various multipliers — 6.0 produced +1.37% bearish EV but caught falling knives in production (GOOG, GLAD in freefall)
- Tested `mr_curve` (motif) at 3x, 5x, 10x, 20x, 30x — saturates between 3x and 5x
- Tested combo and blend approaches — worse than individual signals
- **Deployed experimental weights → caught falling knives → reverted to production weights**
- Tested dominance fixes: cap_8, cap_10, average aggregation
- **Cap_8 won** (+0.381% bearish EV vs +0.338% control) — deployed and validated
- Falling knife filter also added (-5.0 penalty for 2 consecutive red candles, MR only)

**Final MR state:** Original production weights + cap_8 on mr_specific + falling knife filter. Validated by eyeballing 2026-03-31 prediction — top 10 were all healthy uptrending stocks with balanced multi-factor scores.

### 2. Baseline Weight Tuning

Ran full category-by-category tuning (trend, momentum, volume, candlestick, price_action, curve at 0.5x/1.0x/2.0x):
- **Uniform 1.0 is optimal for bullish** (+0.116% EV) — no category boost helps
- momentum_2x best for bearish (+0.90%) but kills bullish
- Production weights tested: better for bearish (+0.914%) but worse for bullish (-0.020%)
- **Decision: Keep current production Baseline weights** — bearish edge matters more since bull markets lift all boats

### 3. Arcade Report Improvements
- Portfolio QTY column shows half-quantity per bracket leg (labeled "QTY/2")
- All numeric columns right-aligned
- Removed standalone CALC button (per-symbol CALC SHARES buttons retained)

### 4. Email Delivery Fix
- Root cause: Brevo SMTP credentials were in `docker/.env` but not root `.env` after Docker→host migration
- Fixed: Updated root `.env` with Brevo settings (port 2525)
- Fixed: Added `.env` sourcing to `run.sh` and `run_daily_pipeline.sh`
- Cron pipeline now sends emails successfully

### 5. Infrastructure Cleanup
- BH Python container stopped, removed from docker-compose.yml (pending merge)
- Research droplet (`161.35.178.128`) destroyed — all findings preserved in memory
- Docker system prune reclaimed 15.3 GB (orphaned images, volumes, build cache)
- Codex's 6 refactor commits reviewed and approved (orchestration, postprocessing, symbol repository, etc.)
- Renamed TO-DO.md → TODO.md

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

- **Codex branch:** `origin/codex-refactor` has 1 pending commit (`f30bafa Remove bluehorseshoe compose service`) — needs merge

## Next Steps

1. **Merge codex-refactor** — docker-compose cleanup commit
2. **Start systemd API service** — `systemctl start bluehorseshoe-api` (port 8001, replaces removed container)
3. **Test API** — verify endpoints work after switching from container to systemd
4. **MongoDB authentication** — configure auth, update MONGO_URI. Defense-in-depth after ransomware incident.
5. **Hypothetical trade engine** — Layer B from TODO: auto-evaluate signal outcomes after hold period
6. See `TODO.md` for full backlog

## Blockers / Open Questions

- **SMTP from Claude Code sandbox is blocked** — user must run `send_report_email.py` manually from their shell. Daily cron works fine.
- **API service not yet started** — port 8001 is unserved after container removal. Start systemd service when ready.

---

## Key Decisions

- **MR cap_8 is the production solution** — caps mr_mean_reversion_specific contribution at 8.0 points. Prevents falling knife dominance while preserving signal. Tested and validated.
- **Run both strategies in all regimes** — don't gate MR in bullish or BL in bearish. Scores naturally surface best picks.
- **Keep current production Baseline weights** — non-uniform weights (momentum-heavy) are better for bearish where edge matters. Bullish is "good enough" since rising tide lifts all boats.
- **Validate before deploying weight changes** — always eyeball prediction output, not just assumption tester EV numbers. Learned the hard way.
- **Email via Brevo on port 2525** — Gmail blocked by DigitalOcean, SendGrid key is stale.
- **Research droplet destroyed** — findings preserved in memory, raw data expendable.

---

## Key Files

| File | Role |
|------|------|
| `src/weights.json` | Indicator weights — original production values with cap_8 protection |
| `src/bluehorseshoe/analysis/indicators/mean_reversion_indicators.py` | Cap_8 in `get_score()`, falling knife filter |
| `src/bluehorseshoe/analysis/technical_analyzer.py` | `_calculate_mean_reversion_modifiers()` wires knife filter |
| `src/bluehorseshoe/core/email_service.py` | SMTP delivery via Brevo |
| `src/bluehorseshoe/reporting/html_reporter.py` | QTY/2, right-align, removed standalone CALC |
| `src/bluehorseshoe/application/services.py` | Orchestration layer (Codex refactor) |
| `src/bluehorseshoe/analysis/postprocess.py` | Candidate assembly + sentiment (Codex refactor) |
| `run.sh` | Sources `.env`, activates venv |
| `run_daily_pipeline.sh` | Sources `.env` for cron email delivery |
| `.env` | Brevo SMTP credentials |
| `docker/docker-compose.yml` | BH container removed (pending merge), mongo + ib-gateway remain |

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
**Codex branch:** `origin/codex-refactor` — 1 commit ahead (docker-compose cleanup)
**Tests:** 685+ passing

---

**Last Updated:** April 2, 2026
