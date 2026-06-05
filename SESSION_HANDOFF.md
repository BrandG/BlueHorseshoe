# Session Handoff

**Date:** June 4, 2026
**Status:** **DeepOS (deep-oversold persistent-dip) entry strategy went research → validated → productionized → LIVE on paper, all this session. 2 of 3 first orders filled.**

This was a big session. We took the one entry edge that survived the honest gauntlet (deep-oversold) all the way to live paper fills, caught and fixed a real execution bug live, and laid the scaffold for a new per-factor scoring product.

## Current status (on `origin/master`)

Three commits shipped + pushed (master fast-forwarded each time):
- `c2c5c0e` — **DeepOversoldStrategy** + reserved paper slots
- `26974b8` — **factor-briefing scaffold** (per-orthogonal-factor candidate view)
- `f33f103` — **DeepOS marketable entry** (limit slightly above prior close)

**DeepOS is live on paper account DUE616654.** Today's `-p` submitted 3 DeepOS brackets into its 3 reserved slots; **MKTX (8sh @123.06) and HCA (2sh @362.96) FILLED** (both below their +1% limit — the fade-capture worked, >2:1 from actual fill); **ZTS resting** (BUY LMT 78.37, DAY tif — fills on a dip or expires + re-picks tomorrow).

### What DeepOS is
ML-free strategy (`strategy_interface.py::DeepOversoldStrategy`, registered `deep_oversold`/"DeepOS"). Fires when: RSI(14)<30 for **≥3 consecutive bars** (persistence is the edge, NOT the crossing) + 20d avg **$-vol ≥ $25M** + price in range + 1·ATR stop realistic. Entry = **prior close × 1.01** as a DAY limit; stop = entry−1ATR, target = entry+2ATR (2:1, talib ATR). Score = `14.5 + (age−3)·1.5` (monotone in oversold depth). Backtest: **+0.142R/trade, t6.2, ~43% win, 9/11 yrs positive, post-cost, strongest in liquid names.**

### Slot reservation
`PaperTrader._select_with_reservation` reserves `paper_slots_deep_oversold` (default **3 of 10**) for DeepOS, 7 for legacy, **with spillover** (idle reserved slots fill from the other side). Per-strategy occupancy via `paper_trades` lookup preserves "at most N on the book." `=0` disables (global top-N). Confirmed working live today (legacy full at 7 → DeepOS took its 3).

## In progress / not done
- **Forward-R tracking fidelity — ✅ SHIPPED TO `master` (commit `ca88cfe`, pushed; branch `deepos-tracking-fidelity` merged via fast-forward then deleted local+remote).** Traced the path 2026-06-04: plumbing is strategy-agnostic and correct (score-save → `journal_signals` → `--evaluate` → `journal_hypothetical_trades` all loop the registry and key on `strategy`), BUT the engine evaluated *every* strategy at the **regime** `hold_days` (only 5/7 existed in `journal_hypothetical_trades`) with a **limit-below-from-signal-bar** entry — neither matches DeepOS (hold=10, marketable +1% next-open). Two bounded Codex NAs (verified by me, full suite 1644 passed) made it per-strategy faithful:
  - **NA-1** — `TradingStrategy.get_hold_days(regime)` + `.entry_style` on the ABC (defaults preserve baseline/MR exactly); DeepOS → hold=10 / `marketable_next_open`. `DEEP_OVERSOLD_HOLD_DAYS=10`. `trade_evaluator` gets `check_entry_marketable` (1-session next-open fill: `min(open,limit)` on the bar after signal, else NOT_ENTERED; no look-ahead). `limit_below` path byte-identical.
  - **NA-2** — `hypothesis_engine` resolves `get_hold_days`/`entry_style` per-signal via the registry, defers immature strategies (DeepOS evaluated at 10+5, baseline/MR still at regime+5), unknown-strategy fallback, batch-pin age-out guard. `_get_hold_days` kept; `evaluate_batch(as_of_date=None)` backward-compatible.
  - **Why DeepOS still shows 0 journal rows:** the last pipeline freeze (batch `2026-06-03`) ran at commit `cbc90e0`, *before* DeepOS landed. It begins automatically at the next daily-pipeline run **if DeepOS fires** (HEAD now has it), then matures for eval ~10 trading days later (~mid/late June). DeepOS docs will carry `hold_days: 10` as proof the fix works.
  - **Pending:** (a) **NA-3** — registry-driven per-strategy breakout in `track_record.py` + `-r` (still hardcoded baseline/mean_reversion → DeepOS folds into `overall`), parked behind Brand's `html_reporter.py` WIP; (b) ~2 weeks out, read the DeepOS `NOT_ENTERED` rate from the marketable model to calibrate `DEEP_OVERSOLD_ENTRY_PREMIUM` (Next-Step #2).
- **Factor briefing is standalone** (`reporting/factor_briefing.py`) — deliberately NOT wired into `html_reporter.py` because Brand has uncommitted WIP there (track_record). Preview at `src/logs/factor_briefing_preview.html` (gitignored). Wire into main report once his html_reporter settles.

## Next steps
1. **Confirm DeepOS forward-R rows land** — the fidelity fix is on `master` (`ca88cfe`, pushed). Once the next pipeline run freezes a DeepOS-era batch and it matures (~10 trading days), check `journal_hypothetical_trades` for `strategy: deep_oversold` rows carrying `hold_days: 10`. NA-3 (per-strategy report breakout) is the only remaining code piece, parked behind the `html_reporter.py` WIP.
2. **Calibrate the +1% entry premium** (`DEEP_OVERSOLD_ENTRY_PREMIUM`) from accumulating live fill rates — it's currently a reasoned guess. If pre-market runs miss names that rip from the open without fading, revisit MOO-with-fill-anchored-bracket.
3. **Cadence (CORRECTED 2026-06-04):** there IS an equity cron — `run_daily_pipeline.sh` runs `0 1 * * 2-6` (Tue–Sat 01:00 UTC, after each US close) and does `-u → -p (freeze batch) → journal → --evaluate → report → email`. Evaluation is **automated** inside the pipeline (`run_daily_pipeline.sh:103`), not manual. The earlier "no equity cron / runs are manual" note was wrong. Open question is genuinely about *cadence fit*, not existence: the post-close 01:00 UTC `-p` submits the +1% DAY limits for the next session (correct for a resting pre-open fade order) — confirm this matches the intended pre-market behavior, or add a dedicated pre-market run if the post-close timing drifts fills.
4. **Screen the remaining factor columns** (volume/volatility/candlestick) through the same gauntlet to light up / confirm-dark the briefing (`factor_groups.py`). Volume (rvol/$-vol) is the most promising untested orthogonal source.

## Key decisions
- **Scoring philosophy:** stop summing weighted indicator triggers (anti-selects — ~24 of 31 signals are one no-edge factor). Move to **gate-and-rank per orthogonal factor** (~3.7 effective factors); confidence = *measured edge*, not signal strength. Factor groups locked in `factor_groups.py`.
- **$25M $-vol floor** (strongest tier; edge dead in <$1M tail).
- **Marketable +1% limit over market-on-open:** MOO fills at the gapped-up open but our brackets are close-anchored → skews 2:1 badly on a gap. A small premium with brackets anchored to entry keeps geometry correct and skips spent runners.
- **PSAR + ADX re-confirmed dead** under the corrected production-sim + age-gradient lens (edge gradient FALLS with trend persistence — opposite of oversold). The corrected method is *discriminating*, not permissive.

## Blockers / open questions
- **+1% premium is unvalidated** — calibrate from live fills (Next Steps #2).
- **Score backfill is PAUSED** by Brand — sentinel `.score_backfill_pause` (do NOT remove; `-p` does not touch it; only `backfill_missing_overviews`, which is unrelated overview/metadata backfill, runs in `-p`).
- **Pre-existing uncommitted changes are Brand's — leave them:** `CLAUDE.md`, `src/bluehorseshoe/reporting/html_reporter.py`, `research/`, `src/bluehorseshoe/reporting/track_record.py`, `src/tests/test_track_record.py`, `docs/handoff/GORDON_TEARDOWN_NEXT.md`.
- **Branch cleanup done 2026-06-04:** after the fidelity merge, deleted 26 fully-merged branches (3 local + 23 remote — the old issue/feature backlog + the 3 DeepOS-session branches). KEPT (not merged): `origin/22-fix-up-linting`, `origin/BlueHorseshoe`. Workflow note: Brand is solo, **no PRs** — branch+commit+push, direct merge to `master`.
- **(From prior session, unverified):** the `bh_swing_friday_flatten` cron line may still be un-enabled — verify if relevant.

## Relevant files (this session)
- `src/bluehorseshoe/analysis/strategy_interface.py` — `DeepOversoldStrategy`
- `src/bluehorseshoe/analysis/constants.py` — `DEEP_OVERSOLD_*` (incl. `_ENTRY_PREMIUM`, `_MIN_DOLLAR_VOLUME`)
- `src/bluehorseshoe/analysis/strategy_registry.py` — registers `deep_oversold`
- `src/bluehorseshoe/analysis/factor_groups.py` — locked 5 factor groups
- `src/bluehorseshoe/reporting/factor_briefing.py` — per-factor briefing renderer
- `src/bluehorseshoe/trading/paper_trader.py` — slot reservation; `src/bluehorseshoe/core/config.py`, `src/main.py` — wiring
- Tests: `test_deep_oversold_strategy.py`, `test_paper_trader_reservation.py`, `test_factor_briefing.py`, `test_strategy_registry.py` (full equity suite green: 1283 passed)
- Research (untracked `research/indicator_screen/`): `rsi_oversold_{gauntlet,production,depth,byyear,crashgate,coststress}.py`, `psar_adx_corrected.py`, `factor_grouping.py`

### Forward-R fidelity (on `master`, commit `ca88cfe`)
- `src/bluehorseshoe/analysis/strategy_interface.py` — `TradingStrategy.get_hold_days()`/`entry_style` (ABC defaults) + DeepOS overrides
- `src/bluehorseshoe/analysis/constants.py` — `DEEP_OVERSOLD_HOLD_DAYS = 10`
- `src/bluehorseshoe/analysis/trade_evaluator.py` — `TradeEvalConfig.entry_style` + `check_entry_marketable`
- `src/bluehorseshoe/analysis/hypothesis_engine.py` — per-signal hold/entry resolution, maturity deferral, unknown-strategy fallback, `PIN_GRACE_TRADING_DAYS` age-out
- Tests: `test_strategy_hold_entry.py`, `test_trade_evaluator_marketable.py`, +5 appended to `test_hypothesis_engine.py` (16 new; full suite **1644 passed, 4 skipped**)
- Codex NA artifacts: `/tmp/nextaction.md` (last = NA-2), run logs `/tmp/codex_na1_run.log`, `/tmp/codex_na2_run.log`; commit script `/tmp/humanaction.sh`. **NA-3 (track_record breakout) not yet drafted** — parked behind `html_reporter.py` WIP.

---
*Prior handoff history (May 22 Friday-flatten, etc.) superseded — that work shipped (`6e68a5d`). Recover from git history if needed.*
