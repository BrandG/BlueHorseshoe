# Session Handoff

**Date:** April 23, 2026
**Status:** Intraday context weights tuned and deployed. BH Lite health check fixed. Research droplet destroyed. System stable, 792 tests passing.

---

## What Was Done This Session (April 19–23)

### 1. Intraday Context Weight Tuning
- Built `src/tune_intraday_weights.py` — replay-based grid search that:
  - Loads historical trade_scores from MongoDB (22 dates, ~3,500 symbols each)
  - Pre-computes context signals from DuckDB OHLCV data
  - Grid-searches weight combinations, re-ranks candidates, grades against actual next-day price action
  - Reports win rate, avg PnL, profit factor per combo
- **Removed [-1,+1] clamp** from `compute_context_score()` — individual signal weights now control contribution directly, no intermediate saturation
- **Disabled zero-impact signals:** `FAILED_BREAKDOWN_BONUS` → 0.0, `WIDE_RANGE_REVERSAL_PENALTY` → 0.0
- **Deployed aggressive config** (validated by 504-combo full grid on research droplet):
  - `CLOSE_STRENGTH_WEIGHT`: 0.6 → 2.0
  - `INTRADAY_CONTEXT_WEIGHT`: 3.0 → 6.0 (baseline), 2.0 → 4.0 (MR)
  - `FAILED_BREAKOUT_PENALTY`: 0.5 (unchanged)
- **Result:** +17% avg PnL (0.668% vs 0.573%) and +7% profit factor (1.72 vs 1.61) vs no-context baseline

### 2. Research Droplet Weight Validation
- Synced code via scp (no GitHub SSH key on droplet)
- Set up SSH tunnel for MongoDB access (production stays bound to localhost — no exposure)
- Ran full 504-combo grid search (7 FBP × 8 CSW × 9 IW) — confirmed deployed config is global optimum
- **Destroyed droplet** after validation complete
- Revoked droplet SSH key from production `authorized_keys`

### 3. BH Lite Health Check Fixes
- **Entry strategy bug:** Health check was picking whichever strategy scored highest today. MeanRev trades that were working (oversold conditions resolving) would flip to Baseline with 0.0 → false CRITICAL. Now re-scores using the entry strategy stored in each position.
- **New `entry_strategy` field** saved in positions JSON; backfilled existing positions
- **New TAKE PROFIT status (`$$`):** Positions in profit with fading signal get "take your money" advice instead of false CRITICAL alarm. Status matrix:
  - `!!` CRITICAL — near stop, big loss (>3%), or losing + score collapsed
  - `$$` TAKE PROFIT — in profit but signal exhausted, consider closing
  - `!` WEAKENING — warnings present but not urgent
  - (blank) OK — no concerns
- Removed duplicate `entry_score` line in `check_position_health()`

---

## Previous Sessions Summary

- **April 17–19:** Intraday context layer (Phase 1 + Phase 2) shipped, BH Lite cron automated, research droplet spun up
- **April 15–17:** BH Lite FTMO signal generator built and iterated
- **April 12:** Holiday warning banner shipped, trade history CSV importer shipped with era tags
- **April 4–5:** Report cleanup, DuckDB read-only mode, code quality sweep
- **April 2–4:** Hypothesis engine (Layer B) shipped, MongoDB auth enabled
- **March 29 – April 2:** MR weight tuning (cap_8 deployed), research droplet
- **March 27:** Assumption tester, regime-aware stop/target multipliers
- **March 23:** Trade journal system
- **March 9:** Pluggable strategy interface
- **March 7-8:** DuckDB migration, new indicators (RVOL, Engulfing, Hammer)

---

## In Progress

- Nothing actively in progress. All items from this session are merged.

## Next Steps

1. **Monitor tuned weights in production** — compare prediction quality before/after over the next week
2. **Monitor BH Lite cron** — health check fixes will show in next automated run
3. **yfinance upgrade** (0.2.25 → 1.2.2+) — currently bypassed with direct Yahoo API
4. **Suppress "cannot write to read-only store" warnings** — cosmetic DuckDB noise
5. **Signal Track Record report section** — needs more hypothesis batches to mature
6. See `TODO.md` for full backlog

## Blockers / Open Questions

- **SMTP from Claude Code sandbox is blocked** — user must run `send_report_email.py` manually
- **bh-codex worktree** at `/root/bh-codex` — still on `codex/intraday-phase2` branch. Will get cleaned up on next Codex task.
- **Phase 2 intraday confirmation on weekends/holidays** — 5-min bars won't be available. Handled gracefully (skips silently).

---

## Key Decisions

- **Intraday context score is unclamped** — no [-1,+1] saturation. Each signal's weight directly controls its score-point contribution. The integration weight (IW) is a strategy-level multiplier.
- **Effective close-strength weight = 12** (CSW 2.0 × IW 6.0). Validated as global optimum across 504 weight combinations.
- **FBB and WRP disabled** — empirically zero impact across all tested dates. Signals kept in code but weights set to 0.0.
- **Health check uses entry strategy** — MeanRev positions scored as MeanRev, not whatever strategy happens to score highest today.
- **TAKE PROFIT status** — profitable positions with fading signals get actionable "lock in gains" advice instead of false CRITICAL.
- **SSH tunnel for remote MongoDB** — never expose MongoDB port to network. Research droplet used `ssh -fN -L` tunnel through private VPC.
- Prior decisions (MongoDB auth, hypothesis engine, MR cap_8, Brevo email, human action scripts, advisory budget model, fresh Codex branches) remain in effect.

---

## Key Files

| File | Role |
|------|------|
| `src/tune_intraday_weights.py` | Replay-based grid search for intraday context weights |
| `src/bluehorseshoe/analysis/intraday_context.py` | Shared intraday context module (unclamped, tuned weights) |
| `src/bluehorseshoe/analysis/constants.py` | `INTRADAY_CONTEXT_WEIGHT` = 6.0, `_MR` = 4.0 |
| `src/bluehorseshoe/analysis/strategy_interface.py` | Context bonus integration (4 process variants) |
| `src/bluehorseshoe/analysis/strategy.py` | `_enrich_with_intraday()` for BH main top-20 candidates |
| `src/bh_lite.py` | BH Lite with fixed health check + TAKE PROFIT status |
| `src/bh_lite_positions.json` | Open positions with `entry_strategy` field (gitignored) |
| `run_bh_lite.sh` | Cron wrapper for BH Lite (23:30 UTC Mon-Fri) |
| `run_daily_pipeline.sh` | BH main cron wrapper (01:00 UTC Mon-Sat) |

---

### Production Commands (Host)
```bash
./run.sh python src/main.py -p                          # Prediction (~3 hours)
./run.sh python src/main.py -u                          # Data update (~30 min)
./run.sh python src/main.py --evaluate                  # Evaluate matured hypotheses
./run.sh python src/main.py -r YYYY-MM-DD               # Regenerate report
./run.sh python src/send_report_email.py                # Send latest report email
./run.sh python src/bh_lite.py --top 5                  # BH Lite manual run
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
- BH Lite: 23:30 UTC Mon-Fri (7:30 PM EDT / 6:30 PM EST)
- BH Main: 01:00 UTC Mon-Sat (9 PM EDT / 8 PM EST)
- Backup: 05:00 UTC daily → Google Drive via rclone

---

## Git Status

**Branch:** master
**Working tree:** clean (SESSION_HANDOFF.md pending)
**Active feature branches:** none (codex/intraday-phase2 local only, tied to bh-codex worktree)
**Codex-refactor branch:** stale, safe to delete when convenient
**Tests:** 792 passing, 2 skipped

---

**Last Updated:** April 23, 2026
