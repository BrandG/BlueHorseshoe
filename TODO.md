# TO-DO

## Near Term

### 🔥 PRIORITY — Validate V2 autonomous trader in live practice (added 2026-05-06; rearchitected to unified trader 2026-05-30; rising_3bar retired 2026-05-31)

**State of the case:** Track 2 shipped, then got folded into a **single unified trader**. The standalone `bh_ftmo_v2_paper.py` is gone — both it and the rising_3bar paper trader were merged into `src/bud/auto_trader.py` (`SignalSource` protocol; one process pulls broker state once, runs every source's candidates through shared safety gates). As of 2026-05-31 the active source list is **V2-only** (`sources = [V2CellSource()]`); `Rising3BarSource` is retired but kept dormant in-file with re-enable instructions (see `auto_trader.py:626`). V2 deploys all graduated cells whose strategy is in `DEPLOYED_STRATEGIES` (9 of 10: every family except candlestick — `deploy_predicate` at `auto_trader.py:104`), **not** the old 5-macd-cell first deploy. 0.5% NAV per trade (`V2_RISK_PER_TRADE_PCT = 0.005`), 1.0%/1.0% RR, GTD = next H4 close. Cron `16 1,5,9,13,17,21 * * *` via `run_bh_ftmo_trader.sh`. Journal: `src/logs/bh_ftmo_trader_journal.csv` (per-candidate `source` column: `v2` / `rising_3bar`).

What's been exercised (journal 05-28 → 05-31): clean `event` values flowing (`order_placed`, `skip_already_open`, `skip_direction_imbalance`, `skip_conflict`, `no_candidates`, `skip_margin_budget`, `skip_cap`). OANDA LIMIT body + GTD + bracket confirmed on live `order_placed` rows. V2 landed **only 1 of 8** orders in the window — the rest were rising_3bar (now retired). See memory `project_v2_order_flow_post_retirement.md`.

**Validation steps now:**

1. **🔬 Measure V2 order flow after the rising_3bar retirement clears (the open experiment).** The post-retirement window so far is entirely the weekend forex halt, and rising_3bar's 7 longs are *still open* pending the flatten — so V2's headroom hasn't materialized yet. After forex reopens (~Sun 21:00 UTC) and the flatten closes those 7: at the 21:16 run and the days after, did V2 `order_placed` rate rise? Did `skip_direction_imbalance` (was the #1 blocker — rising_3bar's long-only flood ate 47/61) and `skip_already_open` (v2: 27) drop? The retirement targets exactly these two chokepoints.

2. **If V2 throughput stays low even with rising_3bar gone**, the limiter is the **net-direction-imbalance gate** (net-long cap 12) and/or `skip_already_open`, not source contention. Revisit the gate sizing or a per-cell NAV slice. `skip_conflict` is benign — it's v2-internal same-pair dedup (two v2 strategies firing one pair), not a policy problem.

3. **Graduation of more cells / live-R check.** Once V2 accumulates a track record (~50+ filled orders), check the live R distribution against the v2 backtest expectation (e.g. macd-limit mean_R ~+0.30 R/trade per the macd planning doc). `DEPLOYED_STRATEGIES` already spans 9 families, so "graduation" now means *pruning* underperformers, not adding — the inverse of the original plan.

**Files:**
- `src/bud/auto_trader.py` (~680 lines) — unified trader: `SignalSource` protocol, `V2CellSource`, dormant `Rising3BarSource`, `deploy_predicate`, journal schema, safety-gate composition
- `src/bud/auto_v2.py` / `src/bud/auto_rising3bar.py` — per-source signal logic imported by the unified trader (standalone entrypoints superseded; `bh_ftmo_v2_paper_journal.csv` dead since 2026-05-28)
- `run_bh_ftmo_trader.sh` — cron wrapper (runs `src/bud/auto_trader.py`)
- `src/bh_ftmo/trading/oanda_trader.py` — `create_limit_order_with_bracket` (GTD support)
- `src/logs/bh_ftmo_trader.log` (run log) and `bh_ftmo_trader_journal.csv` (per-candidate record)

**Commits:** `262e1e4` (original v2_paper), unified-trader refactor + `34d41c4` (rising_3bar retirement), on master.

### 🔥 PRIORITY — Validate BH Briefing in real morning use + decide on filter integration (added 2026-05-06)

**State of the case:** Track 1 of the two-track plan (`project_two_track_plan.md`) shipped end-to-end. `src/bh_briefing.py` evaluates 34 v2 production cells across 17 pairs on the most-recently-closed H4 bar (stoch 4, bb 5, macd 5 limit, sma 3, ema 4, rsi 3, cci 5, atr 3 limit, ichimoku 1 limit, candlestick 1) and emails an inline-styled HTML briefing. Cron installed at `20 1,5,9,13,17,21 * * *` (20 min after each H4 close). Companion shell wrapper at `run_bh_briefing.sh`. All 4 FTMO crons shifted to the bar-close-aligned schedule (incremental :05, predict :10, paper :15, briefing :20) — worst-case latency dropped from ~3h25m to ~20m.

The reframe that produced this: Brand wants a daily-decision aid where *he* picks signals, not an autonomous trader. Concurrency / FTMO sizing-sim survival are NOT engineering concerns for Track 1 — Brand is the gate. The FTMO sizing simulator (`research/ftmo_sizing_sim/`) and conservative-vs-realistic intra-trade analysis inform Track 2, not Track 1.

**Validation steps now:**

1. **Watch the first 1-2 weeks of cron-fired briefings.** Confirm timing (does `:20 UTC` post-H4-close land in the inbox before Brand wakes up?), email rendering on his actual inbox, and the multi-confirmation grouping when 2+ strategies overlap on the same pair/direction. Iterate on format only after enough live runs to know what's missing — don't pre-optimize.

2. **✅ DONE 2026-05-31 — session + D1-alignment findings wired into the briefing as annotations.** Decided: *annotate, don't suppress* (the briefing is a human-in-loop aid; Brand is the gate, so give him the edge-relevant metadata rather than hiding signals). Each fire now shows a **D1 with-trend / counter-trend** tag (with-trend carried ~3.3× per-trade R in the diagnostic) and its **session** (asia/london/overlap/ny), in both console and HTML. ATR + candlestick fires that go counter-trend get a ⚠ "negative counter-trend (historical money-loser)" warning (those are the 3 indicators with negative counter-trend mean_R per `MULTITF_FILTER_v1.md`). Reuses `bh_ftmo.indicators.sessions.session_label` + `pivots.daily_ohlc` (same definitions as the research). Helpers `d1_alignment()` / `session_of()` in `src/bud/briefing.py`; tests in `src/tests/test_briefing_annotations.py`. Memory: `project_briefing_filter_annotations`.
   - **Deferred (separate play):** the +245-pair *universe expansion* from the D1 filter is a V2 cell-selection change, not a briefing change — revisit for the autonomous trader, not here. Combining both filters (drop overlap AND require D1) is still untested. The per-indicator session *suppression* variant (drop OVERLAP) was rejected for the briefing in favor of annotation.

3. **Mid-day check-in mode.** Right now the briefing only reports fires from the most-recently-closed bar. If Brand checks at lunch and the morning's bar fired but he missed it, he sees nothing. Decision: do we add a `--since-last-N-bars` mode (or just bake it into the default — show fires from last 24h, sorted newest-first)? Wait until live use surfaces the need.

4. **Strategy graduation pipeline (Track 1 → Track 2).** As Brand develops trust in the briefing's signals, individual strategies (or the multi-confirmation subset of cells) can graduate to autonomous-paper deployment alongside `rising_3bar`. No code change needed yet — when a candidate emerges, the pattern is the same as `bh_ftmo_paper.py` (cron-driven, OANDA practice account, clear logging).

**Files:**
- `src/bh_briefing.py` (730 lines) — Cell defs + 10 evaluators + console/HTML rendering + email delivery
- `run_bh_briefing.sh` — cron wrapper
- `research/ftmo_sizing_sim/` — sizing sim + sweep results (Track 2 input only)
- `src/bh_ftmo_swing_config.json` — 2-Step Swing 10k FTMO rules used by sizing sim
- Memory: `project_two_track_plan.md`

**Commits:** `6d6195f` (briefing tool, on master), `5c928a0` (v2 research artifacts including sizing sim, on master).

### ✅ RESOLVED (2026-05-31) — `rising_3bar` RETIRED; amplifier question closed (added 2026-04-30)

**Resolution:** rising_3bar was re-tested through the same v2 cell-selection gate every
v2 cell had to clear (its config = stoch `k14/d3/thr20/rec3/long`, already a row in the
stoch v2 sweep). At the v2-standard 1%/1% RR it survives on **1/40 pairs (CHF_JPY long)**
— a pair v2 already trades in 5 strategies, so zero additive edge. Brand judged this
sufficient (skipped the 1.5%-RR re-run). **Removed `Rising3BarSource` from
`src/bud/auto_trader.py`**; v2 untouched. Open positions flattened on retirement (staged
for market open). The amplifier (priority 1 below) is moot — the base signal it amplified
is retired. Full record: memory `project_rising3bar_retired.md`. Historical case kept
below for the research record.

**State of the case:** The "find a signal with measurable edge" search succeeded. `rising_3bar_from_oversold` (stochastic %K rising 3 consecutive bars from below 20) at 1.5%/1.5% RR survives all friction layers we know how to test:

| Layer | Result |
|---|---|
| Per-trade R (held-out 2023-2026) | +0.066 R, CI [+0.046, +0.083] excludes 0 |
| Per-pair spread costs | edge intact |
| Strict 70/30 walk-forward | sign stable, all selection rules beat random by +15-20pp |
| Today's OANDA swap rates | <0.001 R/trade impact, pass rate unchanged |
| Bootstrap FTMO 2-Step Swing 10k sim | **52.8% pass rate vs 34.4% random (+18.5pp lift)** |

Now deployed in paper trading: `src/bh_ftmo_paper.py`, every 4h via cron at `:20 UTC`, OANDA practice account `101-001-39154243-001`, all 40 pairs, 1% NAV per trade. RSI(14)<30 amplifier wired in as 1.5× tiered sizing (borderline P=81% — capture lift if real, lose little if illusory).

**The two priorities now:**

1. **Validate amplifier signal in live paper data.** RSI<30 amplifier shows ~+0.029 R lift in held-out backtest but P(positive)=81%, not 95%. After 2-3 weeks of paper fills (~50-100 trades), split the journal by `rsi_oversold` flag and compare avg R between cohorts. If differential matches backtest (+0.029 R), graduate from tiered sizing to filter mode (only trade confirmed). If not, revert to flat 1% risk and retire the amplifier.

2. **Grow the signal lineup.** Each candidate gets a solo-edge sweep first (TF + RR independent of rising_3bar's config). Outcome decides deployment shape:
   - **Strong solo edge** → standalone strategy that runs in parallel with rising_3bar (don't subordinate it as an amplifier; AND-ing destroys most of its trades and creates a different distribution).
   - **No solo edge but stable cohort delta on host** → amplifier/filter on rising_3bar.
   - **Conditioning state** (HTF trend, ADX level, ATR regime) → filter by definition; skip solo-edge, go straight to cohort-delta.

   Standalone strategy candidates (event signals with their own edge expected):
   - ~~**Bollinger Bands**~~ — *RETIRED 2026-04-30*. Looked STRONG on mid OHLC at H1 (3 RR cells, 81k trades), but realistic OANDA bid/ask modeling flipped every cell negative or to near-zero (H1 1%/1% went +0.013 → **-0.037** R, CI excluded zero on the negative side). The "edge" was mid-price noise. Methodology lesson: spread-cost simulation belongs in the *first* gate, not deferred.
   - **MACD** — bullish histogram cross, MACD>signal, divergence

   Amplifier / filter candidates (state signals or weak-solo events):
   - **ADX(14) low** (weak trend = better mean reversion bounce)
   - **Higher-timeframe trend** (D1 SMA(50) rising when H4 trigger fires)
   - **Volatility regime** (ATR(14) elevated vs rolling median)

   Tooling: `/tmp/sweep_bb_solo.py` for solo-edge sweeps, `/tmp/test_bb_amplifier.py` for amplifier/cohort-delta tests. Both are template scripts — copy and adapt for the next candidate.

**Tooling in place:**
- `src/bh_ftmo/research/test_signal.py` — per-trade R harness
- `/tmp/score_rsi_amplifier.py` — train/test cohort + sign-stability framework (copy-paste for next amplifier)
- `/tmp/ftmo_clean_walkforward.py` — strict walk-forward FTMO sim
- `src/bh_ftmo/trading/oanda_trader.py` — practice account order client
- `src/bh_ftmo_paper.py` — cron-driven paper trader with tiered sizing
- `src/logs/bh_ftmo_paper_journal.csv` — every signal logged with RSI value + sizing tier

**Proven-not-to-help (do not re-test without new evidence):**
- V-bottom stochastic pattern (sign flipped train→test — overfitting)
- RSI < 40 (looser threshold dilutes the signal — sign flipped)
- RSI rising direction (small wrong-direction effect both periods)
- Continuous strength scores (Spearman ρ ≈ 0 between score and R; threshold-crossings carry signal, not magnitudes)
- Union ("OR") combination — RSI alone has near-zero R, adding to rising_3bar dilutes edge
- D1 timeframe at fixed 1.5%/1.5% — spread cost in R is timeframe-invariant
- Linear sum of `stoch_strength + rsi_strength` — no usable rank ordering
- Sandbox_v1 portfolio (3-signal stack) — failed walk-forward, underperformed random
- **BB-below-lower as rising_3bar amplifier** (2026-04-30) — FLIP at H1 across 1%/1%, 1.5%/1.5%, 1%/2% with decisively negative test deltas. The AND-of-(rising_3bar AND BB) intersection is a tiny extreme-oversold subset (~10k of 200k trades) that doesn't behave like either signal alone. NOTE: BB still passed solo-edge — promoted to standalone strategy candidate, just not as an amplifier on rising_3bar.

### ~~🔥 PRIORITY — Find a signal with measurable positive R-expectancy under realistic windows~~ (done 2026-04-30 — see new top priority above)

**State of the case:** Sandbox_v1 doesn't have measurable edge. After fixing the sandbox-harness methodology bug AND running with `max_trading_days: 120` (vs the 14 the original gate used), sandbox_v1 came in at **25.0%** pass rate vs random_baseline's **31.2%**. PF 0.84 and R-expectancy -0.085 confirm it loses money per trade in expectation. The +3pp margin observed at the 14-day cap was a window-boundary artifact — the cap was terminating challenges before the strategy's negative drag could compound. **Sandbox_v1 should not be deployed in any form.** No commercial-EV calculation makes sense when the strategy doesn't beat random.

**The actual open question now:** Is there a signal — any signal — that shows positive R-expectancy with the bootstrap CI excluding zero, after realistic spread cost, under windows long enough that boundary effects don't dominate?

**Tooling now in place to answer this fast:** `src/bh_ftmo/research/test_signal.py` exports `test_signal(signal_fn, pairs, ...)` returning per-trade R distribution + bootstrap CI in seconds, *without* invoking the FTMO challenge sim. Run it with the example `sma_cross_long` signal to see the shape; replace with your own signal callable for new ideas. Output explicitly tells you "POSITIVE EDGE / NEGATIVE EDGE / NO CLEAR EDGE" based on whether the avg-R 95% CI includes zero.

**Workflow for any new signal idea:**
1. Define a `signal_fn(bars) -> pd.Series` of -1/0/+1 values.
2. `test_signal(signal_fn, pairs=...)` — measures per-trade R-expectancy. If 95% CI excludes zero on the positive side, signal has edge.
3. *Only if* step 2 shows positive edge: wire into a strategy class and run the production gate (`bh_ftmo.backtest.cli --strategies <name>`) for FTMO survival validation.

The ordering is the discipline: edge-discovery first, survival-simulation second. The original sandbox_v1 work conflated these and the survival sim was masking lack of edge.

**Hypotheses to test (signal candidates worth a `test_signal` smoke):**
- SMA crosses at different periods (20/50, 50/200, 9/21)
- RSI mean reversion (long when RSI < 25 with reversal candle, short when RSI > 75 with reversal)
- Range breakouts (Donchian-style) with various lookbacks
- Session-specific signals (Asia open breakouts, London close fades)
- Pair-specific signals (some pairs may have idiosyncratic edge that doesn't average across the universe)
- ATR-volatility-conditional entries (only fire when ATR is elevated/depressed)

**What got retired in this pivot:**
- `/tmp/sandbox_*` (65 files): deleted. The methodology bug in that track is the reason the prior validation was misleading; the track's conclusions are no longer trusted as anything more than directional history.
- The "buffer sweep / RR sweep / portfolio sim" sandbox harness work: the relative rankings (buf 1.10, 4-pair whitelist, 0.5%/0.75% RR) are still informative *if* a future signal actually has edge, but they're configured-on-no-edge and shouldn't be cargo-culted into new strategies without re-validation.
- `max_trading_days: 14`: gone. Production config is now 180, matching unlimited-time Swing.

**Artifacts (kept for institutional knowledge):**
- 14-day gate (sandbox_v1 vs baselines): `src/graphs/sandbox_v1_full_2026-04-29_2311.html`, `src/logs/sandbox_v1_full_2026-04-29_2311.csv`
- 120-day gate (sandbox_v1 vs baselines, unlimited-time analog): `src/graphs/sandbox_120d_2026-04-30.html`, `src/logs/sandbox_120d_2026-04-30.csv`

### ~~🔥 PRIORITY — Sandbox `SandboxStrategy` port-back to `bh_ftmo`~~ (ported 2026-04-29; ⚠️ FAILED production gate 2026-04-29)

✅ **Code shipped, but BLOCKED from deployment.** All three sub-NAs landed in master via four commits across three PRs:
- `535a598` SandboxStrategy port (merged via `deac0b5`)
- `a0a930c` worker-cap fix for sandbox_v1 (avoids OOM on 7.8 GB host)
- `a65d1ba` cost-survivability universe filter (merged via `6c7ef1c`)
- `3be9463` active risk overlay, held as WIP on branch for half a day until package validated, then rebased onto post-filter master and merged via `ed49ef1`

**Package smoke result (overlay ON + filter ON, 37 challenges, same RNG seed throughout):**

| Config | FTMO breaches | Win rate | Profit factor | MaxDD | Sharpe |
|--------|--------------:|---------:|--------------:|------:|-------:|
| Both off (baseline) | 15 | 31.7% | 0.70 | 10.8% | -2.87 |
| Filter only | 7 | 35.0% | 0.81 | 12.1% | n/a |
| **Package** | **0** | **36.5%** | **0.88** | 11.3% | **-0.40** |

**Full walk-forward gate result (2026-04-29 evening, 202 starts on `s-8vcpu-16gb` droplet) — VERDICT: FAILED:**

| Metric | Result | Threshold | Verdict |
|---|---|---|---|
| Sharpe (annualized, 1h basis) | -1.33 | ≥ 1.00 | FAIL |
| Profit factor | 0.84 | ≥ 1.30 | FAIL |
| Win rate | 36.6% | ≥ 45.0% | FAIL |
| Max drawdown | 12.4% | ≤ 10.0% | FAIL |
| FTMO pass-rate (lower 95% CI) | **2.5%** | ≥ 70.0% | FAIL |
| Margin vs best baseline | +3.0pp vs random_baseline @ 2.5% | ≥ 10pp | FAIL |

2.5% is statistically tied with random_baseline at 2.5%. So 0/37 in the package smoke wasn't small-sample noise — it was the real signal. Material gap from the sandbox's 12-14% forecast — see the new top-priority investigation block above.

**Reference (kept as institutional knowledge for tuning work):** Validated portfolio recipe — 3 signals (`stoch_oversold_cross` long, `sma_cross_long` long, `rsi_overbought_cross` short with 4-pair whitelist `CAD_JPY/EUR_NOK/USD_CAD/USD_CHF`), H4, 0.5%/0.75% RR (1.5R), 18-pair filtered universe, 1% equity per trade, max 5 concurrent, max 1 per pair. Active-risk-mgmt parameters: `relax_10` config (`buffer_mult=1.10`, `soft_daily_limit=-0.04`).

**Proven-not-to-help levers (kept for future reference, do not re-test without new evidence):**
- Half-risk sizing (0.5%/trade) at current RR — kills strategy via 99.7% timeout
- 2R RR shapes — high decisive ratio but most challenges time out
- Long-side pair restriction — longs are broad-regime signals, train-selected pairs go negative OOS
- Adding `bb_upper_fade` as 2nd short — correlated with `rsi_overbought`, drops decisive ratio
- 4-signal portfolios — competing for position-cap slots increases total-fail risk
- Re-deriving pairs each walk-forward window — UNDERPERFORMS the hardcoded 4-pair selection

**Original status note (preserved for context — pre-merge):** Validation complete + walk-forward stable. Codex Next Action drafted on branch `port-sandbox-v1-strategy` at `/tmp/nextaction.md`. Awaiting send to Codex.

**Validated portfolio recipe (final, post-walk-forward):**
- Signals: `stoch_oversold_cross` (long, all 18 pairs) + `sma_cross_long` (long, all 18 pairs) + `rsi_overbought_cross` (short, **4 ultra-validated pairs only**: CAD_JPY, EUR_NOK, USD_CAD, USD_CHF)
- Timeframe: H4
- RR: 0.5% stop / 0.75% target = 1.5R
- Universe: 18 pairs after filtering pairs where spread > 5% of stop distance (drops HUF/CZK/TRY/ZAR + most exotic crosses)
- Sizing: 1% equity per trade, max 5 concurrent, max 1 per pair
- Active risk mgmt:
  - Entry restraint: block opens that push (today_realized + open_risks + new_risk) past `daily_buffer × 1.10`
  - Intraday liquidation: at -4% intraday, close largest losing position; repeat until back above -4%

**Honest forward expectations (post-walk-forward):**
- Pass rate: **12-14%** (in-sample 17.3%, OOS WF1 14.3%, WF2 12.0%)
- Mean return per challenge: **+0.5% to +1.0%** (in-sample +1.19%, OOS varies)
- Decisive ratio: **60-65%**
- Daily-fail rate: ~0.3%
- Total-fail rate: ~8-10%

**Proven-not-to-help levers (the `relax_10`/buf_1.10 setting is near-optimal):**
- Half-risk sizing (0.5%/trade) — kills strategy via 99.7% timeout
- 2R RR shapes (1%/2%, 0.75%/1.5%) — high decisive ratio but most challenges time out
- Long-side pair restriction — longs are broad-regime signals, train-selected pairs go negative OOS
- Adding `bb_upper_fade` as 2nd short — correlated with `rsi_overbought` (both fire on overbought conditions), drops decisive ratio
- 4-signal portfolios — the two shorts compete for position-cap slots, increasing total-fail risk
- Re-deriving pairs each walk-forward window — UNDERPERFORMS the hardcoded 4-pair selection (dynamic re-selection just adds noise)

**Active Codex Next Actions:** ~~all three landed 2026-04-29~~
1. ✅ ~~**NA #1:** Port `SandboxStrategy` class~~ — landed `535a598`
2. ✅ ~~**NA #2:** Active risk-management overlay~~ — landed `3be9463` after package validation
3. ✅ ~~**NA #3:** Universe filter at engine level~~ — landed `a65d1ba`

**Follow-up diagnostic (still useful):** the package smoke confirmed the sandbox-track thesis that overlay alone (without filter) regresses every metric. The filter is the operative cost-survivability gate; the overlay only earns its keep on the filtered universe. This is documented in the WIP commit `3be9463`'s message and in this session's SESSION_HANDOFF entry.

**Sandbox artifacts (preserved at /tmp/, do not delete until NA #2 + NA #3 land):**
- `sandbox_indicators.py`, `sandbox_combinations.py`, `sandbox_rr_sweep.py`, `sandbox_1d_sweep.py`, `sandbox_deepdive.py`, `sandbox_portfolio.py`, `sandbox_ftmo_challenge.py`, `sandbox_ftmo_v2.py`, `sandbox_ftmo_sweep.py`, `sandbox_ftmo_3sig.py`, `sandbox_buffer_sweep.py`, `sandbox_walkforward.py`, `sandbox_shorts_hunt.py`
- `h1_validate.py`, `h1b_components.py` (BH Lite edge validation)
- Validation logs: `/tmp/sandbox_rsi_3way.log`, `/tmp/sandbox_rsi_temporal.log`, `/tmp/sandbox_walkforward.log`
- Trade ledgers: `/tmp/sandbox_*_trades.csv`, equity curves: `/tmp/sandbox_*_equity.csv`, challenge results: `/tmp/sandbox_ftmo*_challenges.csv`

### ~~🔥 PRIORITY — BH FTMO Indicator Validation Suite~~ (added 2026-04-27, completed 2026-04-27)

✅ **Done.** Built out `src/tests/bh_ftmo/indicators/` from scratch across four Codex Next Actions: `5e962d8` (momentum), `ef31efc` (trend + volatility), `ddb1923` (candlestick + pivots + strength), `a60a3c9` (sessions + dxy + common). 92 tests, 100% module coverage, 0 xfails. Suite runtime <1 second.

**Key findings from the suite (preserved for future reference):**
- **RSI Wilder seed-init mismatch** — RSI(14) needs `period * 12` warmup (~28 days of 4h bars) to converge within 1e-3 of `talib.RSI`; at `period * 5` max divergence is ~0.33 RSI points. TA-Lib seeds with SMA-of-first-period gains/losses; pandas `ewm(alpha=1/period)` skips the SMA seed. Math is correct in steady state. See low-priority follow-up below.
- **ATR converges much tighter than RSI at the same warmup** (1.57e-09 vs needing 1e-3) despite the same seed-init pattern. Reason: ATR's value range is ~1e-3, so the same proportional divergence is correspondingly tiny in absolute terms. Likely the same is true for any Wilder-smoothed indicator on a small-magnitude series.
- **Bollinger Bands stddev convention** — TA-Lib's BBANDS uses population stddev (ddof=0), matching bh_ftmo's `std(ddof=0)`. Confirmed empirically.
- **SuperTrend variant choice** — bh_ftmo uses `close[i-1]` (previous-bar close) in the carry-forward decision at `trend.py:138`, vs the `close[i]` variant used by some references. The implementation is treated as spec; the test fixture re-walks the state machine to match.
- **DST is handled implicitly through `tz_convert`** — paired summer/winter UTC bars at 13:00 both classify as OVERLAP because tz_convert respects the active DST offset. Verified explicitly.
- **`_split_pair` accepts BTC_USD** since both legs are 3 letters — surprised the action prompt; it's not really a "no" filter, just an alphabet/length filter. Currency-meter callers that want crypto excluded need to filter upstream.

**Next:** add the `--strategies` CLI flag (next Codex Next Action) to enable per-strategy gate isolation, then re-run the gate.

### ~~🔥 PRIORITY — BH Lite live-trading correctness~~ (added 2026-04-24, BH FTMO half resolved 2026-04-27)

Discovered during `/plan-ceo-review` of BH FTMO plan: `bh_lite`'s displayed P&L is diverging from FTMO's actual account P&L. Root cause appears to be `dollar_per_pip_per_lot` config values that are off by ~10x for several exotic/low-value pairs. Brand observed a position displayed at +$122 that's actually near +$2,000 on FTMO. This silently misleads every trading decision driven by position health output (take-profit candidates, R-multiple tracking, daily P&L).

**Do these in order, they build on each other:**

1. **Verify `dollar_per_pip_per_lot` values against FTMO's official specification.** Suspect pairs (apparent 10x scale error or quote-convention mismatch): EURHUF (0.27), USDHUF (0.27), EURCZK (0.44), USDCZK (0.44), EURNOK (0.95), USDNOK (0.95), EURSEK (0.97), USDSEK (0.97). Less suspect but worth double-checking: USDZAR (0.55), JPY-quoted pairs at 6.67. File with findings: `src/bh_lite_config.json` (and eventual `src/bh_ftmo_config.json`).

2. **Patch the config** for any pairs that test wrong. Single commit, include a comment or doc entry citing FTMO's spec page so future-us knows where the numbers came from.

3. **Add a P&L reconciliation test** — for each open position, compute P&L from config, compare to a user-entered "FTMO-displayed P&L" value, flag mismatch > 5%. Runs once per daily cron and prints a warning block if any row diverges. This is the v1 version of CEO-review decision C-3 (position/FTMO sync ritual) scoped specifically to P&L accuracy rather than position existence.

4. **Notable-position highlighting** (cosmetic, after math is trusted) — add `NOTABLE WIN` tag to positions > +$500 or > +1R realized, `DANGER` tag to positions < -$500 or within 0.5 ATR of stop. Sort position list by `|P&L|` so the loudest ones are on top. Strictly polish — only ship after items 1-3 are done, otherwise we're decorating wrong numbers.

**Why priority:** Brand is actively trading these positions. Every day the system mis-displays P&L is another day of suboptimal take-profit / stop-adjust decisions. The fix is small (config patch + one test) but the leverage is high.

**Upstream reference (added 2026-04-25):** Phase 3 shipped `src/bh_ftmo/backtest/pip_value.py` with property tests against FTMO's spec page for 8 sample pairs (majors, JPY-quoted, exotic, cross). When you port the BH Lite fix, derive the verified `dollar_per_pip_per_lot` values from that module's logic rather than computing fresh — the FTMO spec property test is the cross-check that catches the original 10x error.

**BH FTMO half resolved (2026-04-27, commit `1ea889c`):** investigation confirmed nothing reads `dollar_per_pip_per_lot` in the BH FTMO code path — `pip_value.py` is the sole pip-mechanics source. Field deleted from all 40 `bh_ftmo_config.json` instrument entries as dead code. **The BH Lite half (items 1-3 above) is still open** if BH Lite is still being used for live position tracking; if BH Lite has been fully retired in favor of MT5-direct trading, this whole block can be closed.

**Not blocking:** BH FTMO plan work. Items 1-3 ship on BH Lite directly; item 4 lands post-BH-FTMO-cutover in whichever code path is live at that point.

### Reporting
- ~~Holiday-aware exit warning banner~~ (done 2026-04-12) — Amber/neon banners on all three HTML report types (standard, email, arcade) when an NYSE holiday falls in the current week. Uses existing `pandas.tseries.holiday` via shared `market_calendar.py` module (no new dependency). Banner uses the report's target date, not system clock.

### Architecture & Refactoring

- Event-driven backtest with an order book. Instead of the current "check high/low against levels" approach, model it as: generate orders → feed daily bars → match orders → update positions. That naturally handles split exits, trailing stops, breakeven stops, shorts — all as different order types rather than special-case code paths.

### Weight Optimization
- ~~Intraday context weight tuning~~ (done 2026-04-19) — Grid search (504 combos, 22 dates) found optimal: CSW=2.0, IW=6.0/4.0, FBP=0.5. Removed [-1,+1] clamp. +17% avg PnL vs baseline. FBB and WRP disabled (zero impact). Research droplet validated and destroyed.
- ~~MR cap_8~~ (done 2026-03-29) — mr_specific capped at 8.0
- ~~Falling knife filter~~ (done) — -5.0 penalty for 2 consecutive red candles, MR only.
- Baseline weight tuning complete — uniform 1.0 is optimal for bullish. No changes needed to production Baseline weights.
- ~~mr_curve saturation test~~ (done) — motif signal saturates between 3x and 5x for both MR and Baseline.

### Hypothesis Engine Enhancements
- ~~Build hypothesis engine (Layer B)~~ (done 2026-04-04) — `trade_evaluator.py`, `hypothesis_engine.py`, CLI `--evaluate`, pipeline integration
- ~~Remove "Yesterday's Results" from reports~~ (done 2026-04-04) — one-day price action is noise
- **Add "Signal Track Record" report section** — replace Yesterday's Results with real N-day outcomes from `journal_hypothetical_trades`. Show win rate, avg P&L, alpha vs SPY, top winners/losers for recently matured batches. Wait until 5-10 batches accumulate before building.
- **Refactor Backtester to use trade_evaluator.py** — Phase 2: `_check_entry()` and `_check_active_trade()` in backtest.py delegate to shared `trade_evaluator` functions, eliminating duplication.

### Regime-Aware Strategy (partially done)
- ~~Add REGIME_PROFILES to constants.py~~ (done)
- ~~Wire regime-adjusted stop/target multipliers into BaselineStrategy~~ (done)
- Paper trader: apply `max_positions_pct` from regime profile (reduce positions in bullish market)
- Backtester: regime-aware hold_days (Bearish=7d, Neutral/Bullish=5d)
- HTML report: display active regime parameters ("Stop 2.5x / Target 3.5x / Hold 7d")
- MR stop/target: use regime multiplier as ML fallback instead of hardcoded 2.0
- ~~Consider gating MR picks in bullish regime~~ — decided against. Both strategies run in all regimes; scores naturally surface the best picks. MR bullish EV is mediocre but not terrible.

## Medium Term

### IBKR Integration
- Paper trading mode — bracket order submission code written (`f3ed895`) but not yet tested with live IBKR connection
- Move T2 stop to breakeven after T1 fills — requires real-time order monitoring loop
- Position sizing based on account equity and per-trade risk (`MAX_RISK_PERCENT`)
- Real-time P&L tracking and stop-loss/take-profit order management

### Sentiment Analysis
- Consider weighting sentiment more heavily for baseline/trend-following than mean reversion (oversold names often have bad news by definition)
- After ~1 month of snapshot data, analyze rate-of-change and sentiment-price divergence signals
- **Future sentiment sources:**
  - **Options flow / put-call ratio** — institutional sentiment proxy, available via CBOE or broker APIs
  - **Earnings sentiment** — NLP on earnings call transcripts (e.g. via SEC EDGAR XBRL filings)
  - **FinBERT / custom NLP** — run our own sentiment model on headlines or SEC filings for higher accuracy than AV's generic scoring
- Design as pluggable `SentimentProvider` interface so multiple sources can be aggregated with configurable weights
- Phase 3 (only if Phase 2 shows value): Explore LLM-based enrichment for nuanced reads
  - High cost/latency per call — only justified if structured sentiment proves insufficient
  - Non-deterministic output makes backtesting difficult; would need caching/snapshotting

### Track Record / Signal Journal
- ~~Layer B: Hypothetical trade engine~~ (done 2026-04-04) — `trade_evaluator.py`, `hypothesis_engine.py`, CLI `--evaluate`, pipeline integration. Auto-evaluates matured signals for entry/stop/target/time exit. Stores outcomes in `journal_hypothetical_trades` with MAE/MFE.
  - Remaining: win rate, expectancy, profit factor, Sharpe, Sortino, max drawdown computations (will come with Signal Track Record report section)
  - Remaining: SPY benchmark comparison for the same period
- ~~Trade history CSV import~~ (done 2026-04-12) — `src/import_trade_history.py` imports raw broker fills into `trade_fills`, synthesizes FIFO positions into `trade_positions`, generates `trade_reviews`. Era-tagged: `"pre_bh"` (pre-2026) vs `"bh_v2"` (2026+). 101 positions imported, 64.9% win rate on BH-era trades.
- **Journal enhancements:**
  - `journal_capital_snapshots` — daily equity state (one record per trading day)
  - `journal_skipped_signals` — signals BH recommended but you chose not to trade
  - Monthly capital statement — auto-generated with returns, benchmark comparison, model adherence score
  - HTML journal report generation (alongside existing prediction reports)
- Portfolio-level metrics dashboard (auto-computed weekly)
  - CAGR, monthly returns, win rate, expectancy, profit factor
  - Sharpe, Sortino, Ulcer index, max drawdown (absolute + rolling 30-day)
  - Hypothetical vs actual comparison table
- Statistical validation
  - Confidence intervals on win rate and expectancy
  - Monte Carlo simulation for edge significance (p-values)
  - ~~Regime-tagged performance breakdown (bull/bear/choppy)~~ (done — assumption_tester v2)
  - ~~Rank decay analysis — does top-5 outperform top-10?~~ (done — no significant difference found)

### Backtest Realism
- Add commission modeling to `BacktestConfig` (e.g. `commission_pct` applied on entry and exit)
- Add spread/slippage modeling beyond current gap logic (configurable `avg_spread_bps`)
- Portfolio-level backtesting — simulate running top N picks simultaneously with fixed capital allocation
- Track max drawdown, Sharpe ratio, and other portfolio-level metrics

### Security
- ~~Add MongoDB authentication~~ (done 2026-04-03) — User `bhapp` with readWrite on `bluehorseshoe` database, `--auth` flag in docker-compose. Defense-in-depth alongside the ufw firewall and localhost bind (both done 2026-03-27 after ransomware incident).

### Data & Infrastructure
- **Migrate OHLCV storage from DuckDB to Parquet files** — DuckDB's single-writer file lock causes contention when multiple processes/pipelines run concurrently (e.g. `-u` and `-p`, or orphaned ProcessPoolExecutor workers holding the lock after a kill). Two-phase approach:
  1. **Phase 1: DuckDB read-only mode** — worker processes and concurrent readers open with `read_only=True`. Eliminates lock contention for the common case (one writer, many readers). Quick win.
  2. **Phase 2: Parquet file backend** — replace `DuckDBStore` with a `ParquetStore` using the same interface. Writes become atomic file swaps (`to_parquet` + rename), reads never block. DuckDB can still query Parquet via `read_parquet()` for ad-hoc analysis. No server, no lock files, no orphaned connections. The 15 consumer files go through the store abstraction so downstream changes are minimal.
- Full historical backfill — backfill all ~6,000 active symbols going back 20 years. Deep history improves ML training, long-range backtesting, and indicator calculations that depend on long lookback periods (200-day EMA, etc.). Will need to run in batches respecting API rate limits (`-b --resume --limit N`). SPY + QQQ already backfilled to 2000.
- Backfill overviews — ~2,000 symbols still missing overviews. Run `-u --refresh-overviews --ov-limit 500` in batches.
- Add post-prediction step to track symbols with stale/insufficient data and update an invalid symbols list, so they can be excluded from future runs or flagged for re-backfill
- Add Redis or in-memory caching for repeated indicator calculations during LOO/optimization runs
- Distributed backtesting — allow running date ranges in parallel across multiple workers
- Remove BH Python container from docker-compose — Python now runs natively on host via venv, but the container is still defined in docker-compose.yml as a fallback. Remove it after confirming the host-based daily pipeline succeeds (next run: 02:00 UTC). Then start the systemd API service (`systemctl start bluehorseshoe-api`).
- ~~Fix email delivery after Docker→host migration~~ (done) — Brevo SMTP credentials moved to root `.env`, `.env` sourcing added to `run.sh` and `run_daily_pipeline.sh`
- ~~Research droplet~~ (destroyed 2026-04-19) — weight tuning complete, SSH key revoked
- Upgrade yfinance from 0.2.25 to latest (1.2.2+) — Yahoo changed their API and the old version can't parse responses. Raw API works fine; the library is broken. Test upgrade impact on BH's existing Yahoo provider before deploying.
- Suppress "Cannot write to a read-only DuckDBStore" warnings during `-p` — `save_historical_data()` in `historical_data.py:86` attempts opportunistic cache-writes that correctly fail in read-only mode. Check `store._read_only` (or add a `store.is_read_only` property) before calling `save_symbol()` to avoid noisy warnings. Low priority — harmless, prediction still works.

## Long Term

### Strategy Expansion
- Intraday/scalping strategy using shorter timeframes
- Sector rotation overlay — weight candidates by sector momentum
- Earnings avoidance filter — skip symbols with earnings within hold period
- Correlation filter — avoid picking multiple highly correlated symbols in the same batch

### ML Improvements
- Automated model retraining pipeline on a schedule (monthly or quarterly)
- Feature importance tracking over time — detect model drift
- Ensemble methods — combine XGBoost with other models (LightGBM, neural net)
- **Meta-score ranking** — fuse independent signals (technical score, sentiment, ML win probability, Connors flag) into a single composite rank for candidate sorting. Currently candidates are ranked by technical score alone; ML/sentiment are displayed but don't influence selection order.
  - Use logistic regression on journal_signals outcomes: `P(win) = sigmoid(w1*score + w2*sentiment + w3*ml_prob + w4*connors)` — learned coefficients become the weights
  - Validate with grid search over weight combinations, measuring top-N win rate / avg P&L
  - Normalize features to comparable scales before fitting (score is 0-30, sentiment -1 to +1, ML prob 0-1)
  - Use leave-one-date-out cross-validation to guard against overfitting (small sample size until more batch dates accumulate)
  - Prerequisite: accumulate several more weeks of journal_signals with sentiment data before fitting is meaningful
  - **Interim signal hierarchy** (until meta-score is built): ML Win% as gate (skip < ~55%), Score for ranking among survivors, Sentiment as tiebreaker only for baseline picks. Sentiment is weakest signal — AV can't backfill historical data so it was never validated against outcomes, and for MR picks negative sentiment is expected (oversold names have bad news by definition).
- Use split-exit outcome data as additional training signal

### Monitoring & Ops
- Dashboard for live system health (API rate limits, data freshness, model staleness)
- Alert on prediction pipeline failures or anomalous outputs
- Backtest regression suite — auto-run on weight or code changes to catch performance degradation

### BH FTMO

**Phases 0 → 3 complete (2026-04-25).** Full backtest framework shipped end-to-end across sub-phases 3.0 → 3.5 (11 commits `02d3234` → `e842d9a`). See `docs/planning/BH_FTMO_PLAN.md` for the locked plan and `docs/planning/PHASE_3_BACKTEST_ARCH.md` for as-shipped architecture (20 P3-* decisions).

**Phase 3 ✅ COMPLETED 2026-04-25** — bid/ask-aware simulator, FTMO rule enforcement (static + trailing DD per P3-13), three null baselines (random+ATR / Mon-Fri / RSI(14)), walk-forward fold harness (18mo IS / 6mo OOS / 6mo roll), metrics + reporter (Sharpe / Sortino / PF / WR / MaxDD / FTMO pass-rate w/ bootstrap CI), entry-edge gate evaluator, CLI driver (`./run.sh python -m bh_ftmo.backtest.cli`).

**🚧 First gate run completed 2026-04-27 — verdict FAILED.** Run id `bh_ftmo_gate_20260427_104629_5883064`. 13,538 trades over 30 walk-forward folds on a c2-48vcpu-96gb droplet, ~30 min wall time. Five attempts were needed before getting a clean run; each attempt surfaced and fixed a lurking engine bug (`9f321e3` rates-snapshot-bridge, `384f084` cli-print-traceback, `eeb2225` data-gap-filter, `b34db4f` rates-snapshot-tolerant). Gate failed all five criteria (Sharpe / PF / WR / MaxDD / pass-rate) plus structural findings: Baseline appears long-only (0/3,652 short), ASIA session = 65% of losses, AUD cluster = 41% of trades.

**Indicator validation suite shipped 2026-04-27 (resolved block above).** Math is verified. The gate verdict is now actionable — failures are real strategy/engine signal, not measurement noise. Next is adding the `--strategies` CLI flag for per-strategy isolation, then re-running.

**Decision tree:**
- After re-run, if a single-strategy gate passes → unblock Phase 4 (edge-exit scoring) AND Phase 2c (indicator lookback tuning + walk-forward optimizer per P3-20).
- If both single-strategy gates fail → debug per-strategy in isolation; the structural findings (Baseline long-only, ASIA losses, AUD cluster) become directly diagnosable rather than mixed.

**Brand action items (still open):**
- ~~Fill in `docs/planning/FTMO_RULES.md` §2 TBD values from FTMO live dashboard → `bh_ftmo_config.json` `ftmo` block~~ ✅ done 2026-04-25 (Free Trial variant: 14-day, $100k, static DD, $0 commission, Europe/Prague server tz).
- Run `bash /tmp/humanaction.sh` to install the every-4h incremental-update cron. (Note: the file has been repurposed several times for droplet provisioning / cleanup; the cron-install variant needs to be re-emitted when ready.)
- Install GitHub App before May 8 so the scheduled BH FTMO check-in routine (`trig_01RfvYoMo6V7bETCRBLn5WNT`) can run.

### BH FTMO follow-ups (added 2026-04-24 via /plan-eng-review; updated 2026-04-25)

- **Walk-forward optimization backport to BH equities backtest** — teach the equity `Backtester` and `WeightOptimizer` to run walk-forward 18mo-IS / 6mo-OOS / 6mo-roll splits. Why: BH FTMO proves walk-forward first; the equity side currently runs single-fold grid search and likely overfits. Pros: better equity weight robustness. Cons: requires equity backtest changes + regression testing; decoupled from FTMO scope per BH FTMO plan decision 9A. Context: decision made during `/plan-eng-review` to maintain scope hygiene. Depends on: BH FTMO Phase 3 entry-edge gate passing. **Status update 2026-04-25: Phase 3 framework ships, gate not yet run — start when gate verdict is produced and is a pass.**

- ~~**OANDA demo token health check**~~ (done 2026-04-24) — `OandaClient.health_check()` hits `/v3/accounts` and returns rich diagnostic; CLI via `python -m bh_ftmo.data.oanda_client`. Backfill installs the secret scrubber so 401 traces never leak token bytes.

- **BH FTMO cron outage monitoring** — email alert if Friday NY-afternoon cron run is missing (critical for weekend-flatten feature). Why: if Friday's cron fails silently, open positions stay through weekend gaps — pure operational risk, not a code bug. Pros: protects the whole weekend-flatten risk-exit feature. Cons: needs an alerting mechanism — the existing Brevo SMTP pipeline (used for equity reports) works. Context: during `/plan-eng-review`, this was elevated from TODO to mandatory Phase 6 deliverable. Depends on: BH FTMO Phase 6 cutover. **Note: already listed as mandatory in Phase 6 of `docs/planning/BH_FTMO_PLAN.md` — duplicating here for visibility only.**

- ~~**`bh_ftmo_config.json instruments` pip-value reconciliation**~~ (added 2026-04-25, done 2026-04-27 commit `1ea889c`) — investigation confirmed the field was never read; `pip_value.py` is the sole pip-mechanics source. Field deleted from all 40 instrument entries.

- **Reporter Sharpe/MaxDD mismatch** (added 2026-04-27) — in `bh_ftmo_gate_20260427_104629_5883064.html`, the per-strategy table shows Sharpe=0.20 / MaxDD=22.2%, while the verdict block shows Sharpe=-2.90 / MaxDD=14.6%. They're computing on different equity-curve bases (per-strategy vs. portfolio-aggregate, or per-fold vs. concatenated). Audit `metrics.py` and `reporter.py` to reconcile. Low-effort once spotted; high-value because the two views currently disagree about whether the gate even *should* fail.

- **`--strategies` CLI flag for per-strategy isolation** (added 2026-04-27, **deprioritized 2026-04-28** in light of the sandbox-track pivot — see "Sandbox-track signal validation outcome" priority block at top of file) — `cli.py:190` hardcodes `SignalGenerator(strategies=[BaselineStrategy(weights=weights), MeanReversionStrategy(weights=weights)])`. Add a flag so the gate can run Baseline-only, MR-only, or both (preserving today's behavior as default). Codex Next Action still drafted on branch `cli-strategies-flag`. Cheap to land for completeness but the per-strategy isolation question is largely moot — the sandbox track has already shown that both production strategies as composed are likely chasing wrong components.

- **Port sandbox-validated 2-signal portfolio into `bh_ftmo`** (added 2026-04-28, **pending user port-back decision**) — see top-of-file priority block for full detail. New `SandboxStrategy` class + active-risk-mgmt overlay + universe filter cutoff + new `--strategy sandbox_v1` gate option. Estimated ~3 Codex Next Actions to land cleanly.

- **Find a cost-survivable short signal** (added 2026-04-28) — all 4 shorts tested in `sandbox_combinations.py` failed the 18-pair filtered universe cost test (`rsi_overbought_cross`, `bb_upper_fade`, `shooting_star`, `bearish_engulfing`). Without a real short, the validated long-only portfolio is structurally exposed during USD-strength regimes. Worth testing: RSI/MACD divergence patterns, regime-conditional shorts (only when DXY trending up), short-only filtered universes (different cost economics for bearish trades).

- **Audit `relax_10` -10% total-fail tail** (added 2026-04-28) — 88 of 925 challenges (9.5%) still hit the hard -10% limit despite active risk management. Scan those specific challenges to see whether they share a regime/pair/timing pattern. If they're concentrated, a regime filter may be addable cheaply; if they're distributed, the buffer multiplier needs tightening (try 1.05 instead of 1.10).

- **Baseline appears long-only** (added 2026-04-27) — first gate CSV shows 0 short trades out of 3,652 baseline trades. Likely a strategy-implementation bug, not weights. Investigate after indicator validation passes (so we know it's not e.g. an inverted RSI).

- **Engine: weekend-flatten architecture** (added 2026-04-27, deferred; downgraded 2026-04-29) — the four engine fixes from that session all worked around the same root cause: FX week-end (Friday 21:00 UTC) creates data gaps that callers must handle. A proper architectural fix would be to flatten *all* open positions at the Friday-close bar before the gap rather than carrying them across. **Note 2026-04-29:** Brand purchased 2-Step Swing, which exempts overnight/weekend/news restrictions on the funded stage. This is no longer required for funded compliance — only useful for general gap-risk management. Priority drops from "should land before Phase 4" to "nice to have." Re-elevate if a future challenge switches to 2-Step Standard.

- **RSI/EMA-family seed-init mismatch with TA-Lib** (added 2026-04-27, low priority — full validation suite informs the recommendation) — momentum + trend + volatility validation (`5e962d8`, `ef31efc`) confirmed every Wilder-smoothed bh_ftmo indicator (RSI, EMA, ADX, ATR) converges to TA-Lib in steady state but diverges in warmup because TA-Lib seeds with SMA-of-first-period and pandas `ewm(alpha=1/p)` skips the SMA seed. **Magnitudes vary dramatically by indicator:** RSI(14) needed `period * 12` warmup at 1e-3 tolerance (max divergence 0.33 RSI points at `period * 5`); ATR(14) at the same warmup converges to 1.57e-09 (essentially perfect). The difference is that ATR's value range is ~1e-3 so absolute divergence at convergence is correspondingly tiny, while RSI lives on a [0,100] scale where the seed-mismatch shows. **Recommendation: close as wontfix.** Walk-forward IS windows are 18 months (>>200 bars warmup), incremental updates carry state in production, and changing the seed would invalidate all prior research. The "first 28 days are noisy" caveat applies only to a true cold-start, which we don't run.

- **Codex sandbox: design test-validation workaround** (added 2026-04-25) — Codex's command sandbox uses `--unshare-net` / `network_access:false`, blocking Docker network access. MongoDB at `127.0.0.1:27017` is unreachable from inside Codex, so any pytest run that hits MongoDB fixtures (e.g., the equity-side `SwingTrader()` fixture in `test_dynamic_entry.py`) fails deterministically with `[Errno 1] Operation not permitted`. Three options for future Codex Next Actions that need test validation: **(a)** Brand runs pytest from his shell (which has Docker access) and supplies the count to the Next Action — already used as the workaround for the 2026-04-25 doc-refresh sweep; **(b)** add pytest markers (e.g., `@pytest.mark.requires_mongo`) to MongoDB-dependent tests so Codex can run a Codex-runnable subset via `pytest -m "not requires_mongo"`; **(c)** reconfigure Codex's sandbox to allow Docker network access (out of scope for code changes — would need Codex setup work). Pick one before the next Next Action that needs a test gate.

- **Backward-looking risk circuit breakers** (added 2026-04-29 from FTMO research-paper review) — Add `daily_realized_loss_circuit_breaker` and `consecutive_loss_limit` parameters to `RiskOverlay`. The paper's most-repeated tactical advice ("stop after 2 bad trades", "stop at 1.5% daily realized loss") is genuinely absent from our design — the overlay's entry-restraint formula is purely *forward-looking* (asks "would adding this push us past 5%?"); it does NOT ask "have we already had a bad day, should we stand down?" Three small losses can stack to 2-3% realized without tripping entry restraint, while the regime is clearly hostile. **Validation gate (per `feedback_validate_incrementally.md`):** new sandbox script that adds the rules + sweeps thresholds (1.0%/1.5%/2.0% realized-loss cutoff × 2/3/4 consecutive losses); confirm decisive-outcome ratio improves vs. the validated `relax_10` baseline before porting to `RiskOverlay` as opt-in knobs. Estimated: 1 day sandbox sweep + 1 day port + tests if validated.

- **Risk-per-trade tightening sweep (1% → 0.5%)** (added 2026-04-29 from FTMO research-paper review) — Paper consistently recommends 0.25-0.5% per trade; sandbox config uses 1.0%. Prior half-risk sweep (`/tmp/sandbox_ftmo_sweep.py`) showed 0.5% kills the validated config via 99.7% timeout *with the current 0.5%/0.75% RR shape*, but a tighter risk + tighter target (e.g. 0.4% stop / 0.6% target) might trade off differently — paper's insight is that smaller risk per trade scales better psychologically and improves survivability when win rate dips. **Validation gate:** focused FTMO challenge sweep at 0.5% risk × 0.4%/0.6% RR vs. 0.3%/0.45% RR; compare decisive-outcome ratio + mean return to validated 0.5%/0.75% @ 1% risk baseline. Lower priority than the circuit breakers; only worth running if there's reason to believe the current 1% sizing is too aggressive in live execution.

- **OANDA demo forward-test rehearsal pre-activation** (added 2026-04-29 from FTMO research-paper review) — Brand purchased $99 unlimited-timeframe 2-Step Swing 10k. The challenge clock is not running until activation, so there's no pacing pressure. The production signal-emission CLI landed in commit `4797a57` (merged via `c80f057`); the next step is to install the every-4h cron via `humanaction.sh` and run live signals against the OANDA demo for at least 5 trading days. Validate: signal counts match backtest expectation (sandbox produced ~6-9 trades per 14-day window post-filter), scoring math is sane on live bars, the manual paste-to-MT5 workflow is smooth before money is at risk. Paper's most-repeated cheap-edge: rehearse exactly what you'll do live. **Done definition:** 5+ trading days of live signal output reviewed for sanity; any divergences from backtest expectation explained before Brand activates the paid challenge.

- **`src/bh_ftmo/main.py` Phase-0 stub refactor** (added 2026-04-29 evening) — `main.py` is a Phase-0 copy of `bh_lite.py` that imports from `bluehorseshoe.analysis.*` (equity!) and references equity index / yfinance tickers (`^GSPC`, `^DJI`, `^IXIC`, `GC=F`). When `bh_ftmo.predict` was added (commit `4797a57`), the obvious move was to delete the stub — but it's **NOT pure dead code:** three helpers are actively used by 38 tests in `src/tests/test_bh_ftmo.py`:
  - `_find_instrument_by_ftmo` (34 lines, has equity-ticker aliases)
  - `check_position_health` (86 lines, pure forex logic — *useful* for live position monitoring, would be the natural seed for a future `bh_ftmo.monitor` CLI)
  - `_calculate_position_pnl` (17 lines, pure logic)
  
  **Refactor plan when picked up:**
  1. Extract `check_position_health` and `_calculate_position_pnl` to a new clean module (`bh_ftmo/positions.py` or `bh_ftmo/monitor.py`).
  2. Decide what to do with `_find_instrument_by_ftmo` — it includes equity-ticker translation that isn't relevant for forex-only FTMO; might be partly deletable.
  3. Drop the broken `main()`, equity imports, and yfinance refs.
  4. Update test imports in `src/tests/test_bh_ftmo.py` to point at the new home.
  5. Delete the stub.
  
  **Estimate:** ~1 day. **Priority:** low — `predict.py` works without it; `main.py` just sits inert with the helpers tucked inside. Best done either as preparation for a `bh_ftmo.monitor` CLI (when live position state tracking becomes a need) OR after the OANDA demo forward-test settles whether BH FTMO is going to become the cutover system. No rush.
