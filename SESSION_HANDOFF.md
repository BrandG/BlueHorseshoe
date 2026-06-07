# Session Handoff

**Date:** June 7, 2026 (continuation — same day as the HA/PSAR-ADX session below)
**Status:** **Live equity book productionized around the validated sleeves.** Demoted the dead
scorers to tracking-only, replaced the slot reservation with edge-weighted ranking + conviction
sizing, attempted fractional shares (BLOCKED by IBKR), surfaced the bot's fractional plan in the
report, and closed the "indicators as ML features" door with a decisive null. All committed to
`master` (not pushed unless noted). All code; full suite green (1687).

## What this session did (in order)
1. **Demoted Baseline + MeanReversion to tracking-only** (`887ef10`). `paper_tradeable=False` on both —
   no validated entry edge (scorer anti-selects; MR net-losing). Live book is now ONLY {DeepOS, DeepOS+HA}.
   They still score / journal / forward-R.
2. **Edge-weighted slot allocation** (`5383573`). Disabled the 3:7 DeepOS reservation
   (`paper_slots_deep_oversold=0`); slots now fill by global top-N on `score * edge_weight` (validated
   per-trade R: DeepOS 0.142, DeepOS+HA 0.404, ADX-Down 0.149, legacy 0.0 → leftover-only). Fixes that
   DeepOS/HA share a scoring formula and tied at equal depth. Weight map derived from the registry
   (`PaperTrader._edge_weight_map`), works for `-p` and `-r`; unregistered Connors → 0.0.
3. **Conviction-weighted sizing** (`5383573`). Capital split ∝ `edge_weight` instead of flat; pot =
   `len(selected)*base` (same total, tilted distribution); capped at `max_position_mult*base` (2.5).
   Reduces to flat for a single-sleeve book. `PaperTrader._position_sizes`.
4. **Price-ceiling bucket test** (`c9d97a9`, `research/indicator_screen/rsi_oversold_pricebucket.*`). Tested
   MAX_STOCK_PRICE $500→$1000: signal generalizes (nonbull $500-1k alpha +0.297R ≈ validated +0.309R) but
   marginal (~2% volume, half R, t=1.8). **KEPT $500.**
5. **Fractional-share sizing** (`85cc4dd`) — then **BLOCKED + reverted to whole-share** (`816f6b5`). Code is
   complete (`_split_quantity`, float qty through the stack) but `verify_fractional_bracket.py` on paper acct
   DUE… returned **IBKR Error 10243 "Fractional-sized order cannot be placed via API."** With conviction
   sizing nearly every order is fractional → True would reject EVERY bracket. So `paper_fractional_shares`
   **defaults False** (whole-share floor). Code stays flag-gated.
6. **Bot's intended fractional position in the report** (`1ea3034`). `PaperTrader.preview_fractional_plan`
   reuses the live selection+sizing (broker-free, empty-book, unfloored) → `SwingTrader._annotate_planned_sizing`
   tags candidates → 📐 fractional badge in the ARCADE report. Report = unfloored ideal, bot floors. Verified
   on a full `-p` (2026-06-05): 10 planned, all DeepOS, fractional (e.g. WU 132.3662 sh).
7. **Deep-OS ML selection — NULL** (`ba37e77`, `research/indicator_screen/deep_os_ml_selection.*`). Tested
   whether the 26-indicator set as ML FEATURES can pick winners among deep-oversold fires (70,271 fires,
   time-split). **Test AUC 0.4981 (coin flip); nonbull model ANTI-selective.** Indicators fail as features
   too. "Take every fire" beats ML AND depth-rank → edge is in the SETUP, not the ranking.

## Commits this session (on `master`)
`887ef10` demote Baseline/MR · `5383573` edge-weighted alloc + conviction sizing · `c9d97a9` price-bucket
test · `85cc4dd` fractional sizing · `816f6b5` fractional blocked→whole-share + verify script · `1ea3034`
fractional plan in report · `ba37e77` deep-OS ML selection NULL.

## Live strategy roster (post-session)
| name | display | live orders? | notes |
|---|---|---|---|
| deep_oversold | DeepOS | **yes** | edge_weight 0.142 |
| deep_oversold_ha | DeepOS+HA | **yes** | edge_weight 0.404 (high-conviction) |
| baseline, mean_reversion | Baseline, MeanRev | **NO — demoted** | tracking-only; forward-R only |
| adx_didown | ADX-Down | **NO** | tracking-only |
Allocation: global top-N by `score*edge_weight`; sizing ∝ edge_weight (cap 2.5×); **whole-share floor**.

## Blockers / open questions
- **Fractional deploy gate (BLOCKED):** IBKR Error 10243 — account can't place fractional via API. To enable:
  turn on fractional-share trading on the IBKR account → re-run `src/verify_fractional_bracket.py` to PASS →
  flip `paper_fractional_shares=True`. Operator step (Brand's account access).
- **Standard report is stale:** `report_*.html` two columns are hardcoded to Baseline/MeanRev and don't
  surface the deep-oversold sleeves at all → planned sizing only lands in the ARCADE report. Modernizing it
  is a separate task.

## In progress / parked (all in memory `project_live_sleeve_gate`, `project_deep_os_ml_selection`)
- **Efficiency lever (now stronger):** the full indicator suite + ML overlay are computed every `-p` ONLY to
  feed tracking-only Baseline/MR — the live deep sleeves bypass them, and the ML-selection null proves the
  indicators don't earn their keep as features either. Could retire Baseline/MR + the suite to lean out `-p`;
  the only remaining cost is their OOS forward-R record. NOT acted on.
- **Depth-rank vs allocation tension:** depth-rank top-quartile UNDERPERFORMS take-every-fire in 2021-26
  (+0.218 vs +0.401R nonbull), yet we rank DeepOS by score=oversold depth. Era-dependent (contradicts the
  full-sample depth-helps lock). Worth a dedicated look when DeepOS is oversubscribed; FLAG, not acted on.
- **OOS forward-R watch:** DeepOS/DeepOS+HA/ADX-Down accrue forward-R in `journal_hypothetical_trades`. Promote
  ADX-Down to live only if its OOS record justifies the modest edge.

## Next steps (Brand's pick)
- Decide the efficiency lever (retire Baseline/MR + indicator suite vs keep for OOS tracking).
- **Market-neutral long-short prototype** (carried, still the biggest deployable door): long dislocation /
  short trend-extension, dollar-neutral, nonbull-gated. Needs a real paired backtest (overlap/sizing/turnover/
  borrow), not two single-leg numbers added.
- Optional: modernize standard report to surface deep sleeves; migrate retrain feature path to DuckDB.

## Key decisions this session
- **Only validated sleeves go live** — Baseline/MR demoted; the score alone shouldn't allocate, so allocation
  is edge-weighted (validated R), not raw-score.
- **Fractional kept in code but defaulted OFF** — IBKR blocks API fractional; whole-share is the safe default,
  one flag away from enabling once the account permits it.
- **No ML on the deep-oversold sleeve** — AUC 0.498 proves indicators add no conditional selection edge; keep
  it mechanical. "Take every fire" beats selection.

## Standing corrections (DO NOT repeat) — see memory
- `feedback_trend_family_not_dead`: don't call the trend family "dead/closed." Long-only 10d bracket tests
  mean-revert; a negative long = a SHORT-selector candidate. State horizon/direction; report measurements,
  not verdicts; let Brand steer.
- `feedback_no_premature_indicator_verdicts`: explain an indicator + audit the harness before any verdict.

## Carry-forward ops state (still live)
- **Equity cron** `run_daily_pipeline.sh` Tue–Sat 01:00 UTC (`-u→-p→journal→--evaluate→report→email`).
  **Weekly retrain** `cron_weekly_retrain.sh` Sun 02:00 UTC (works post the prior-session `.env` fix).
- **Retrain tech debt:** feature builder reads legacy `StockPrice-*.json` then LIVE re-fetches instead of
  DuckDB (~1hr; should migrate). `--retrain` only refreshes overlay (win-prob) models, not profit_target/stop_loss.
- **PAPER_TRADING_ENABLED=true** in `.env` — so `-p` submits orders unless you pass `--no-paper` (used this
  session to test reports without trading on a closed Sunday market).
- **Score-backfill PAUSED** — sentinel `.score_backfill_pause`; do NOT remove. Live scorer UNTOUCHED.
- **Workflow:** solo, no PRs — branch/commit/push direct to `master`. 4-vCPU/8GB box; serialize backtests;
  NEVER run heavy jobs concurrent with `-p`/`-u` (DuckDB lock + OOM). Guard with `ps -eo args | grep '[s]rc/main.py'`.

## Relevant files (this session)
- `src/bluehorseshoe/analysis/strategy_interface.py` — `paper_tradeable` / `edge_weight` per sleeve.
- `src/bluehorseshoe/core/config.py` — paper_* knobs (slots_deep_oversold=0, conviction_sizing, fractional_*).
- `src/bluehorseshoe/trading/paper_trader.py` — `_select_with_reservation`, `_position_sizes`, `_split_quantity`,
  `preview_fractional_plan`.
- `src/bluehorseshoe/analysis/strategy.py` — `_annotate_planned_sizing`.
- `src/bluehorseshoe/reporting/html_reporter.py` — arcade planned-shares badge + JSON.
- `src/verify_fractional_bracket.py` — paper-gateway fractional verification (re-run after enabling fractional).
- `research/indicator_screen/{rsi_oversold_pricebucket,deep_os_ml_selection}.{py,out}` — research records.

## The synthesis (unchanged, still the governing model)
Mean-reversion is the only edge, one factor with two legs + a discriminant: persistent DISLOCATION reverts up
(long), persistent EXTENSION reverts down (short), TIMESCALE gates both. The live book harvests the long/
dislocation leg (DeepOS, DeepOS+HA). Selection WITHIN the setup adds nothing (ML null) — the edge is the setup.

---
## Prior session (June 7, earlier) — HA + PSAR/ADX characterization
Heiken-Ashi: deployed 3-green-bar trend shape ANTI-predictive → zeroed HA trend weight; `ha_flip_up × deep-
oversold` LOCKED as DeepOS+HA sleeve. PSAR/ADX: continuation DEAD, contrarian `adx_diDown` ALIVE but modest →
ADX-Down tracking-only sleeve. Cron `.env` bug fixed. Commits `a383030`/`8898c48`/`421a96f`/`37fe164`/`035eb52`/
`d76349c`. Detail in memory: `project_heiken_ashi_deepdive`, `project_psar_adx_reaudit`, `project_weekly_retrain_env_bug`,
`project_deoverlap_signflip_newey_west`.
