# BH FTMO Plan

**Status:** `/plan-eng-review` + `/plan-ceo-review` complete (2026-04-24) — 19 decisions locked in reviews, ready to begin Phase 0
**Drafted:** 2026-04-24
**Owner:** Brand
**Strategic goal:** INCOME — BH FTMO generates transferable profit that feeds the BH equity IBKR account. Once FTMO is profitable, additional prop firms (MyForexFunds, FundedNext, etc.) will be added as parallel capital-generation tributaries. BH equity is the long-term alpha engine; BH FTMO is capital-generation for it. Framework-generalization is not the goal, but the architecture should remain cohesive enough to accept a second prop firm later without a rewrite.

---

## Motivation

BH Lite started as a weekend "pipe the BH scoring into FTMO-sized forex signals" experiment. It has earned first-class treatment:

- It runs on its own cron, drives real (paper) trading, and exposes design decisions that don't belong in the equities pipeline (cluster filtering, position health, FTMO risk math).
- FTMO-specific constraints (daily loss, max drawdown, profit targets, trailing DD) demand dedicated infrastructure that has no analogue in US equity swing trading.
- 4h forex is a fundamentally different instrument universe from daily US stocks — different sessions, different spread economics, different regime dynamics, different indicators.

This plan formalizes BH FTMO as a sibling system to BH equities: shared foundations where sensible (DuckDB, ML patterns, scoring framework), dedicated infrastructure where the domain demands it.

---

## Guiding Principles

1. **Reuse where it fits, split where it doesn't.** DuckDB, ML inference patterns, the indicator-registry pattern, the weight optimizer — all transfer. Market-regime logic, daily-bar assumptions, Alpha Vantage plumbing — don't.
2. **Data quality > indicator sophistication.** Everything downstream depends on clean 4h bars with spread data. Get that right first.
3. **Spread-aware everything.** In equities, spread is a rounding error. In retail forex on a 30-pip target, a 1.5-pip spread is 5% of the reward. Every backtest number is a lie without spread modeling.
4. **Exits on par with entries.** Retail systems over-invest in entry logic and ship with naive exits. A separately-trained, separately-weighted exit score is where quiet edge hides — treat it as a peer to entry work, not a tail deliverable.
5. **Plan on paper, code from the plan.** This document is the source of truth for architecture decisions until the code catches up to it.

---

## Phase 0: Copy & Stabilize (≤2 hours)

Low-risk warm-up. No behavior changes. **Starts as package from day one (decision 1A)** — avoids the Phase-2 package-graduation collision. **bh_lite.* files are COPIED, not renamed, per decision C-5** — they remain frozen as the parallel comparison system for Phase 6 paper trading, deleted only at final cutover.

- Create `src/bh_ftmo/` package by **copying** bh_lite content:
  - `src/bh_ftmo/__init__.py` (public API exports)
  - `src/bh_ftmo/main.py` (copy of `bh_lite.py`)
- `cp src/bh_lite_config.json src/bh_ftmo_config.json` (both exist)
- `cp src/bh_lite_positions.json src/bh_ftmo_positions.json` (both exist)
- `cp src/bh_lite_orders.json src/bh_ftmo_orders.json` (both exist)
- `cp src/tests/test_bh_lite.py src/tests/test_bh_ftmo.py` (adjust imports in copy)
- Internal `LiteTrader` class → `FTMOTrader` (in the copy only; bh_lite keeps `LiteTrader`)
- bh_lite.py itself stays FROZEN — no edits during Phases 1-5 (only critical bug fixes allowed)
- Cron: add a second entry for BH FTMO once Phase 6 parallel begins; keep BH Lite entry live until final cutover
- Grep for any "bh_lite" references in SESSION_HANDOFF.md, TODO.md, AGENTS.md → update forward-looking docs to point at bh_ftmo, leave historical references alone
- All 38 existing tests must still pass (in both test_bh_lite.py AND test_bh_ftmo.py)
- Single commit, clean diff

**Exit criterion:** `./run.sh pytest src/tests/test_bh_ftmo.py` AND `./run.sh pytest src/tests/test_bh_lite.py` both green. BH Lite cron still produces identical output.

---

## Phase 0.5: OANDA Validation Probe ✅ COMPLETED 2026-04-24

**Gated Phase 1.** Probe script `src/bh_ftmo/data/oanda_probe.py` ran against the OANDA v20 account.

### Environment note

Brand's token turned out to be scoped to the **live** environment (demo token would be separate; demo account `101-001-39154243-001` is dormant). Since v1 never places orders via OANDA (orders are manual paste to FTMO MT5), data-only access to live is zero-risk. Probe + future data code uses `api-fxtrade.oanda.com` with account `001-001-21321256-001`. Configurable via `OANDA_ENV=practice` for when we eventually need execution testing.

### Results (report at `src/logs/oanda_probe_2026-04-24.md`, gitignored)

- **40/40 FTMO forex instruments** pass all checks: exist, bid+ask, 10y history (earliest bar ~2016-01-03), 5000-bar page fetch works
- **Rate-limit hits: 0** across ~120 probe requests (3 per instrument)
- **Runtime: 6.2s** for the full probe
- **68 total forex pairs** available on the account (beyond the 40 FTMO ones)

### Residuals

- **No `BTC_USD` / `ETH_USD` on this account** → crypto deferred for v1. Decision 11 said "crypto if available." It's not, so it's out. If FTMO crypto becomes strategically important, pull Binance public REST API (free, 4h klines back to 2017).
- **No `USD_DXY` index** → **synthesize** DXY from the 6 constituent pairs (EUR/USD 57.6%, USD/JPY 13.6%, GBP/USD 11.9%, USD/CAD 9.1%, USD/SEK 4.2%, USD/CHF 3.6%). All 6 are on OANDA. Synthetic DXY aligns to our 4h bar grid deterministically, which is actually better than a raw feed. Phase 2 `dxy_correlation.py` will compute this at read time.

### Verdict: **GO** — cleared for Phase 1.

---

## Phase 1: Data Foundation (~1 week)

The gating phase. Get the data right.

### Provider Selection

**Recommendation: OANDA v20 API** (primary), **HistData.com** (backup/bulk historical).

| Provider | Cost | 4h native? | History | API quality | Verdict |
|---|---|---|---|---|---|
| **OANDA v20** | Free with demo account | Yes | 20+ years | Good, Python SDK exists | **Primary** |
| **HistData.com** | Free | No (1m → resample) | Back to 2000 | Download-based, no live API | **Bulk historical only** |
| Yahoo | Free | No (cap ~730 days on 1h resample) | Thin | Brittle, rate-limited | **Retire for FTMO** |
| Polygon.io / TwelveData | Paid ($30+/mo) | Yes | Varies | Clean | **Fallback if OANDA misbehaves** |

OANDA is chosen because: (a) free, (b) native 4h, (c) 20+ years history, (d) same API powers live execution if we ever want to migrate off FTMO, (e) returns bid+ask separately — clean spread modeling built in.

### Storage Schema

**Recommendation: separate DuckDB file** (`data/fx_4h.duckdb`), not an extension of the equities store.

Reasoning: equity OHLCV has no bid/ask, no session concept, daily bars. Forex 4h has bid+ask, session alignment, 6× the row density per year. Co-locating them invites schema gymnastics. Cleanly separate.

Table schema (per symbol), **updated per decision 8A to include operational metadata**:
```sql
CREATE TABLE ohlcv_4h (
  symbol       VARCHAR NOT NULL,
  timestamp    TIMESTAMP NOT NULL,  -- NY 5pm-aligned bar close (UTC in storage)
  open_bid     DOUBLE,
  high_bid     DOUBLE,
  low_bid      DOUBLE,
  close_bid    DOUBLE,
  open_ask     DOUBLE,
  high_ask     DOUBLE,
  low_ask      DOUBLE,
  close_ask    DOUBLE,
  tick_volume  BIGINT,
  provider     VARCHAR NOT NULL,    -- 'oanda', 'histdata', 'binance', etc.
  ingested_at  TIMESTAMP NOT NULL,  -- when this row was persisted
  is_complete  BOOLEAN NOT NULL,    -- false for mid-formation bars
  PRIMARY KEY (symbol, timestamp)
);

-- Identical schema for ohlcv_1h (per decision 4A — intrabar stop/target resolution)
```

Mid-price is derived: `(bid + ask) / 2`. Spread in pips is derived: `(ask - bid) / pip_size`.

**1h bars stored alongside 4h** per decision 4A. Used during backtest to resolve intrabar stop-vs-target ambiguity when both sit inside the same 4h bar's H-L range.

### Session Alignment

4h bars anchored to **NY 5pm close** (22:00 UTC during US daylight time, 21:00 UTC during standard time).

Rationale: 5pm NY is the canonical "daily roll" in retail forex. A bar closing at 5pm, 9pm, 1am, 5am, 9am, 1pm NY gives natural session coverage (NY close / Tokyo open / Tokyo lunch / London open / London/NY overlap / NY open / NY lunch).

**Per decision 7A, time/DST handling uses the `exchange_calendars` library + a dedicated spec doc at `docs/planning/FX_TIME_SPEC.md` to be authored alongside Phase 1.** The spec codifies:

- UTC as canonical storage; timezone conversions applied at read time
- Sunday open handling (first forex bar of week = NY Sun 5pm close)
- DST spring-forward (bar skip from 13:00→14:00 EDT) and fall-back (duplicate 01:00 EDT) rules
- Holiday-shortened weeks (US Thanksgiving, Christmas, UK bank holidays)
- Missing-bar detection (distinguish "no trading that hour" from "data gap")
- Daily-pivot calendar-day derivation (pivots use NY-calendar-day OHLC from prior day)

### Deliverables

- `src/bh_ftmo/data/oanda_client.py` — v20 API client with rate limiting, exp backoff, token health check
- `src/bh_ftmo/data/fx_store.py` — DuckDB wrapper for 4h + 1h forex store
- `src/bh_ftmo/data/fx_time_utils.py` — exchange_calendars wrapper + NY 5pm alignment + DST rules
- `src/bh_ftmo/data/backfill.py` — **10-year** backfill script, idempotent, resumable, checkpointed per symbol per year-chunk
- `src/bh_ftmo/data/validate.py` — gap/outlier/duplicate/out-of-order detection
- `src/bh_ftmo/data/oanda_probe.py` — reused from Phase 0.5 as a health check
- **DXY added to backfill target list** (needed for Phase 2 currency strength + correlation indicators)
- **`docs/planning/FX_TIME_SPEC.md`** — canonical time/DST/holiday rules
- **`docs/planning/FTMO_RULES.md`** — precise FTMO rule spec per decision 5A (reset timezone, equity-vs-balance, swap timing, commission, rule interactions). Includes "rotate OANDA API token quarterly" reminder per decision C-2.
- **`src/bh_ftmo/logging/scrubber.py`** — log filter redacting OANDA tokens + FTMO account IDs per decision C-2
- **DuckDB weekly backup** — integrate `data/fx_4h.duckdb` into existing `backup.sh` pipeline
- Config: `.env` entries for `OANDA_API_TOKEN` and `OANDA_ACCOUNT_ID` (account ID already in memory)
- Tests: mocked OANDA responses, storage round-trip, DST/Sunday-open/holiday edge cases, duplicate/out-of-order bar handling, backfill mid-chunk recovery

**Exit criterion:** **10 years** of clean 4h + 1h bars for all 40 FTMO instruments + DXY, validated end-to-end. Phase 0.5 probe report is the go-ahead gate.

**Crypto sub-question:** FTMO typically offers BTCUSD.sim / ETHUSD.sim. OANDA's crypto coverage is jurisdiction-dependent (limited on OANDA US; BTCUSD/ETHUSD on OANDA international). If we need crypto and OANDA can't supply, fall back to a free exchange API (Binance public REST has 4h klines back to 2017 for major pairs) as a secondary store. Decide during Phase 1 after confirming OANDA's actual instrument list against the FTMO symbol list.

---

## Phase 2a: Indicator Port (~4-5 days)

**Split from original Phase 2 per decision 14A — lookback tuning moved to Phase 2c after the backtest exists.**

### Indicator isolation (decision 15D, supersedes 15C)

**Decision reversal 2026-04-24.** During Phase 2a kickoff, investigation showed the equity-side indicators import `bluehorseshoe.core.config.weights_config` (global singleton), `bluehorseshoe.reporting.report_generator`, `bluehorseshoe.analysis.curves.*`, and `bluehorseshoe.analysis.constants` — a naive physical move to `src/shared/indicators/` would leave the new package reaching back into the equity side, and FTMO code would read the equity `weights_config` by accident. Properly extracting all four coupling surfaces is ~1 week of work on production equity code ("the single most important regression event in the whole project" per the original 15C framing).

Brand's call: **skip the extraction. Let BH FTMO have fully independent indicators at `src/bh_ftmo/indicators/`**. Zero shared code between the two systems. Intentional duplication is preferred over refactor risk to the live equity pipeline. A bug in the FTMO indicators can never affect the equity system, and vice versa.

**Consequences:**
- No `src/shared/` package is created.
- BH FTMO indicator implementations are written fresh (informed by equity versions, but independent code).
- Equity code is NOT touched during Phase 2a.
- Any future "refactor to share" is a separate project, explicitly out of scope.

### Port with defaults

Port the shared indicators as-is with **BH equity default lookbacks as starting values**. No tuning yet — that's Phase 2c. Rationale: decouples "does the math work on 4h data" from "are the parameters right for 4h." The first is Phase 2a; the second needs the backtest from Phase 3.



### Triage Existing BH Indicators

| Category | Disposition |
|---|---|
| Momentum (RSI, MACD, Stoch, Williams %R, CCI) | Port, re-parameterize lookbacks |
| Trend (ADX, EMA, SMA, SuperTrend, Donchian, Ichimoku) | Port, re-parameterize |
| Volatility (ATR, Bollinger Bands) | Port as-is |
| Volume-based (OBV, VWAP, MFI, RVOL) | **Drop or reinterpret.** Retail forex "volume" is tick volume — directionally useful as a relative signal, useless as absolute liquidity. Keep tick-volume variants flagged explicitly. |
| Candlestick (Hammer, Engulfing, etc.) | Port as-is |
| Pivots | Port, but **add daily pivots** — heavily watched in FX, rarely referenced in equity swing trading |

**Lookback re-parameterization is the real work here.** RSI 14 on daily = 14 days of context. RSI 14 on 4h = 56 hours (~2.3 days) of context — a very different instrument. Every indicator with a period parameter needs its forex-appropriate lookback determined empirically via backtest, not inherited.

### New Forex-Specific Indicators

- **Currency Strength Meter** — aggregate one currency's strength across all pairs it appears in. If USD is strong in 6/7 pairs, that's a dominant regime signal. Multi-pair indicator — needs a different compute path than single-series indicators.
- **Session Breakout** — London open (3am NY) and NY open (8am NY) produce characteristic volatility expansions. Flag breakouts of the Asian session range.
- **Daily Pivot Levels** — S1/S2/S3, R1/R2/R3 computed from prior daily OHLC. Used as scoring inputs (price near pivot → reversion setup; price breaking pivot → trend setup).
- **DXY Correlation** — for USD pairs, rolling correlation with DXY to confirm/deny USD-driven moves.
- **Carry Differential** (optional, lower priority) — interest rate differentials as a slow drift signal.
- **COT Positioning** (optional, weekly cadence) — CFTC Commitment of Traders data as a contrarian extreme indicator.

### Deliverables

- `src/bh_ftmo/indicators/` — **all** indicator implementations (per decision 15D, fresh/independent; not extracted from equity). Ports of equity logic (RSI, MACD, ADX, ATR, Bollinger Bands, EMA/SMA, Ichimoku, SuperTrend, Donchian, candlestick patterns, pivots) plus forex-specific additions (currency_strength, sessions, pivots, dxy_correlation)
- Registry pattern for indicator lookup
- Per-indicator unit tests on synthetic 4h data
- **Mandatory: no-lookahead property tests for multi-pair indicators** (per review decision — elevated from TODO). Pattern: feed data up to bar T, snapshot output, add bars > T, verify T's output is unchanged. Catches silent edge-inflation bugs in currency strength, DXY correlation, and similar aggregators.
- Config: `bh_ftmo_weights.json` (separate from equity weights)

### Exit criterion

All equity tests still pass (shared refactor is backward-compat). All forex-specific indicators have unit tests. Multi-pair indicators have no-lookahead property tests.

---

## Phase 2c: Indicator Tuning (~3 days, runs after Phase 3)

**Runs after Phase 3 backtest exists.** Walk-forward grid search over per-indicator lookback periods, finds the 4h-optimal value for each. Weights produced here become `bh_ftmo_weights.json` v1.

---

## Phase 3: Backtesting Framework (~1–2 weeks)

### Extensions Over Existing `Backtester`

- **Spread modeling.** Entry at ask (buy) / bid (sell); exit inverse. Stop-loss triggers at the unfavorable side of the spread. Load spread from stored ask-bid.
- **Swap/rollover.** Daily carry charge per open position. Configurable per-symbol (OANDA publishes these).
- **Session-aware entries.** Optional no-entry window during thin Asian liquidity (configurable).
- **FTMO rule simulation:**
  - Daily loss limit → hard close all positions, flag day as failed
  - Max drawdown → hard close all positions, flag challenge failed
  - Profit target → flag challenge passed
  - Trailing drawdown → track peak equity, enforce
- **Economic calendar blackouts.** Config-driven no-trade windows around high-impact events (Phase 5 dependency; stub the interface now).

### Walk-Forward Optimization

Split 10 years into overlapping in-sample/out-of-sample windows:
- IS: 18 months → optimize weights
- OOS: 6 months → evaluate (no optimization)
- Roll forward 6 months, repeat

Robust weights are weights that perform consistently across OOS windows, not weights that won a single in-sample grid search.

**Equity-side walk-forward backport removed from this plan per decision 9A** — tracked as separate TODO to maintain scope hygiene.

**OOS-contamination assertion** required: after split, shuffling OOS data should not change IS scores. If it does, the split is leaking.

### Reporting

- Win rate, R-expectancy, profit factor, max DD, Sharpe, Sortino
- FTMO pass/fail simulation across randomized start dates
- Worst drawdown sequence (the specific chain of trades that caused peak DD)
- Per-cluster performance breakdown
- Per-session performance breakdown

### Baselines (per decision 17B — three required)

Backtest must compare the BH FTMO strategy to all three baselines over the same out-of-sample windows:

1. **Random-entry + fixed-ATR-exit** — true null hypothesis (luck test)
2. **Fixed-schedule** — Monday-open in, Friday-close out (time-in-market test)
3. **Simple RSI(14)** — oversold/overbought rule (complexity-justification test)

If BH FTMO doesn't beat all three materially, we don't have edge.

### Entry-Edge Gate (per decision 16A — strict criteria)

**Phase 3 exit gate** — all must pass before proceeding to Phase 4 edge-exits:

| Criterion | Threshold |
|---|---|
| Sharpe ratio | ≥ 1.0 |
| Profit factor | ≥ 1.3 |
| Win rate | ≥ 45% |
| Max drawdown | ≤ 10% |
| FTMO challenge pass rate | ≥ 70% across randomized start dates |

If any criterion fails, **stop and debug**. Don't invest in sophisticated exits on top of a weak entry signal.

### Deliverables

- `src/bh_ftmo/backtest/engine.py`
- `src/bh_ftmo/backtest/optimizer.py` (walk-forward grid/Bayesian search)
- `src/bh_ftmo/backtest/reporter.py` (HTML + CSV output)
- Tests: known-outcome sample trades, walk-forward fold correctness, FTMO rule trigger cases

---

## Phase 4: Edge-Exit Scoring (~1–2 weeks) — **gated on Phase 3 passing**

**Per decision 6A, exits split into two tiers:**

- **Risk-exits** (weekend flatten, challenge deadline, hard stops) ship earlier, alongside Phase 2/3 work. They protect capital and are strategy-agnostic.
- **Edge-exits** (trend break, momentum fade, partial closes, dynamic targets, opposing signals, exit scorer) live in Phase 4 and **only get built if Phase 3's entry-edge gate passes**. No point optimizing exits on a strategy that doesn't have edge.

If Phase 3 gate fails: halt, debug entries, don't enter Phase 4. Skip to re-running Phase 3 after fixes.

### Architecture

- **Separate score, separate weights.** Entry scoring answers "should I enter?"; exit scoring answers "should I close *this specific position*?" They share indicators but weight them differently.
- **Context-aware.** Exit score takes the position (entry price, direction, time held, current P&L in R multiples) as input alongside market state.
- **Graduated actions, not binary.** Exit score thresholds → (hold, trail, partial close, full close). Existing BH Lite position health system is the seed of this.

### Exit Indicators

- **Trend break** — close below 20-EMA on 4h for longs (direction-inverted for shorts)
- **Momentum fade** — RSI divergence (price higher high, RSI lower high), MACD histogram rollover
- **Volatility exhaustion** — ATR spike > 2σ from recent mean (reversal risk)
- **Time stop** — position open > N bars with < 0.5R progress → close (configurable)
- **Target proximity dynamic targets** — T1/T2 adjusted to nearby pivots/S-R, not fixed ATR multiples
- **Opposing signal** — if a fresh entry signal for the *opposite direction* on the same pair exceeds threshold X, exit
- **End-of-week flatten** — first-class feature per Brand's Q3 note. Config keys: `flatten_before_weekend: true`, `weekend_flatten_hours_before_close: 4` (default; configurable per risk appetite). Runs as a dedicated cron check Friday afternoon NY time. Applies regardless of position health score — this is about gap risk, not signal quality.
- **Challenge-deadline awareness** — env var `FTMO_CHALLENGE_END_DATE` (ISO date). As deadline approaches, behavior shifts:
  - >7 days out: normal operation
  - 3–7 days out: raise minimum entry score threshold by X (fewer, higher-quality entries)
  - <3 days out: no new entries; manage existing only
  - On deadline date: hard-flatten all positions
  - If unset: treat as "no deadline" (normal operation always)
  - Design discussion still open: what should "more conservative" specifically look like? Candidates: smaller lot sizes, tighter stops, reject signals below cluster leader by X%. Pick during Phase 4 design.

### Backtest Exit Scoring Independently

Given fixed entry logic (current BH Lite behavior), which exit rules produce best risk-adjusted return on the same trade population? Isolate the variable.

### Deliverables

- `src/bh_ftmo/analysis/exit_scorer.py`
- `src/bh_ftmo/analysis/exit_indicators.py`
- Integration into `check_position_health()` or its successor
- Per-exit-rule A/B backtest results

---

## Phase 5: Economic Calendar Integration (~2–3 days)

- Data source: ForexFactory calendar (scrape) or TradingEconomics API (paid tier). Start with ForexFactory scrape.
- Store events with: timestamp, currency, impact rating (low/med/high), event name, forecast/previous values
- Config:
  - `no_trade_before_high_impact_minutes: 30`
  - `no_trade_after_high_impact_minutes: 15`
  - `no_trade_before_medium_impact_minutes: 0` (default off; configurable)
- Signal generator skips during blackouts
- Open positions: config-driven behavior — `close_before_high_impact: true` flattens, `hold_through: true` does nothing
- Backtest honors the same rules (critical for realistic numbers)

**Deliverables:**
- `src/bh_ftmo/data/calendar.py`
- Tests with fixed-date sample events

---

## Phase 6: Live Integration & Cutover (~2–3 **weeks**, including 2+ weeks parallel paper trading)

- Paper-trade on OANDA demo in parallel with BH Lite cron for 2+ weeks
- Regression test: on historical days where BH Lite produced signals, verify BH FTMO produces rational output **with explicit numeric acceptance criteria** — not "rational" as narrative. Criteria: same top-N signals ≥ 60% overlap, ranked-list Spearman correlation ≥ 0.7, no cluster violations.
- **Mandatory: cron outage alerting** — email alert if Friday cron run is missing (critical for weekend flatten). Use existing Brevo SMTP pipeline. **No cutover without this.**
- **Observability v1 (per decision C-4):** structured cron digest line per run, daily FTMO headroom email (daily loss + max DD headroom in USD), weekly score-drift alert (median top-N score drifted >2σ from 30-day baseline), terminal equity curve view
- **Position/FTMO reconciliation ritual (per decision C-3):** v1 prints "current positions: X. Match FTMO? [y/N]" at end of each cron run. New signals paused until confirmed for the day.
- **Phase 6.5: Auto-reconciliation (post-cutover):** extend to OANDA `/openPositions` endpoint reconciliation once shadow-trading on OANDA demo is in place
- **Deadline-expiry behavior (per decision C-6):** first cron run after `FTMO_CHALLENGE_END_DATE` passes prints loud warning, pauses new entries until `FTMO_CHALLENGE_END_DATE` is unset or updated (state tracked in a small `.ftmo_deadline_ack` file)
- Swap cron from `bh_lite` → `bh_ftmo` (add bh_ftmo entry during parallel period; remove bh_lite entry at cutover)
- bh_lite.* files remain in repo for 30 days post-cutover (rollback safety); then archived/deleted
- Update SESSION_HANDOFF.md, TODO.md
- Update CLAUDE.md with BH FTMO entry

---

## Phase 7: Interactive Dashboard (~3–5 days, post-cutover)

Terminal output remains primary (Brand runs it "several times a day"). Dashboard is a polish layer, not a replacement.

- HTML report generator modeled on `bluehorseshoe/reporting/html_reporter.py`
- Per-day snapshot: current open positions, today's signals, suppressed-by-cluster list, P&L curve, daily risk committed vs. budget
- Historical view: backtest equity curve, per-cluster performance, per-session performance
- Scoring breakdown drill-down: click a signal → see its indicator components
- Challenge countdown widget (if `FTMO_CHALLENGE_END_DATE` set): days remaining, current P&L vs. profit target, DD headroom
- Static HTML (no server required) — regenerated on each cron run, viewable by opening the file

**Deliverables:**
- `src/bh_ftmo/reporting/html_reporter.py`
- `src/bh_ftmo/reporting/templates/`

---

## Package Structure

**Phase 0:** single file `src/bh_ftmo.py` (minimal disruption)

**Phase 2+:** graduate to a package when indicator code arrives:
```
src/bh_ftmo/
├── __init__.py             # public API
├── main.py                 # CLI entry
├── config.py
├── data/
│   ├── oanda_client.py
│   ├── fx_store.py
│   ├── backfill.py
│   ├── validate.py
│   └── calendar.py
├── indicators/             # fully independent of bluehorseshoe/ per decision 15D
│   ├── momentum.py
│   ├── trend.py
│   ├── volatility.py
│   ├── candlestick.py
│   ├── sessions.py
│   ├── strength.py
│   └── pivots.py
├── analysis/
│   ├── signal_generator.py
│   ├── cluster_filter.py
│   ├── exit_scorer.py
│   └── exit_indicators.py
└── backtest/
    ├── engine.py
    ├── optimizer.py
    └── reporter.py
```

Tests mirror this structure in `src/tests/bh_ftmo/`.

---

## Architecture Decisions (LOCKED 2026-04-24 via Open Questions + `/plan-eng-review`)

| # | Decision | Resolution | Status |
|---|---|---|---|
| 1 | Primary data provider | OANDA v20 (Brand confirmed; willing to add $30/mo Polygon/TwelveData fallback) | **Locked** |
| 2 | Primary timeframe | 4h | **Locked** |
| 3 | Session anchor | NY 5pm close | **Locked** |
| 4 | Storage | Separate `data/fx_4h.duckdb` (with `ohlcv_4h` + `ohlcv_1h` tables) | **Locked** |
| 5 | Store spread as | Separate bid+ask columns | **Locked** |
| 6 | Exit scoring model | Weighted indicator score, parallel to entry; ML variant later | **Locked** |
| 7 | FTMO rule enforcement | Hard-stop simulation in backtest, **per precise spec in `docs/planning/FTMO_RULES.md`** | **Locked** |
| 8 | Walk-forward windows | 18mo IS / 6mo OOS / 6mo roll | **Locked** |
| 9 | Package promotion timing | **Start of Phase 0** (revised from Phase 2 — see 1A below) | **Locked** |
| 10 | History depth | 10 years (baseline; extend if OANDA supplies more cleanly) | **Locked** |
| 11 | Instrument scope | All 40 current + crypto if available | **Locked** (crypto source TBD in Phase 0.5) |
| 12 | Dashboard | Phase 7 deliverable, post-cutover | **Locked** |
| 13 | Live execution | Future work, not v1 | **Locked** |
| 14 | End-of-week flatten | First-class **risk-exit** feature (Phase 3, ships early), config-driven hours before Friday close | **Locked** |
| 15 | Challenge-deadline awareness | `FTMO_CHALLENGE_END_DATE` env var, graduated behavior — specific behavior TBD | **Locked on existence, design open** |

### Added by `/plan-ceo-review` (2026-04-24, HOLD SCOPE mode)

| # | Decision | Resolution | Status |
|---|---|---|---|
| C-1 | 1h-bar fallback in backtest | When 1h missing for intrabar resolution: exclude trade from P&L stats, track as "unresolved" count in report | **Locked** |
| C-2 | Log scrubbing | Dedicated Python logging filter redacting OANDA tokens + account IDs; Phase 1 deliverable | **Locked** |
| C-3 | Position/FTMO sync | v1: daily cron confirm-ritual ("positions match FTMO? y/N"). Post-Phase-6.5: auto-reconcile via OANDA API for shadow-traded positions | **Locked** |
| C-4 | Observability v1 | Ship with structured cron digest + FTMO headroom email + score-drift alert (2σ) + terminal equity curve | **Locked** |
| C-5 | Phase 0 rename semantics | **Copy** bh_lite.py → bh_ftmo/main.py (don't rename). bh_lite.* stays frozen for Phase 6 parallel paper trading. Deleted at cutover. | **Locked** |
| C-6 | Deadline-expiry behavior | On first cron run after `FTMO_CHALLENGE_END_DATE` passes: loud warning, pause new entries until Brand confirms or clears | **Locked** |

### Added by `/plan-eng-review` (2026-04-24)

| # | Decision | Resolution | Status |
|---|---|---|---|
| 1A | Packaging path | Start as `src/bh_ftmo/` package from Phase 0 (no mid-project restructure) | **Locked** |
| 3A | OANDA validation | Add Phase 0.5: OANDA Probe before committing to Phase 1 | **Locked** |
| 4A | Intrabar resolution | Store 1h bars alongside 4h; backtest uses 1h path when stop+target inside same 4h bar | **Locked** |
| 5A | FTMO rules | Spec precisely in `docs/planning/FTMO_RULES.md` for Brand's specific challenge (CE(S)T reset, equity basis, Wed swap triple, etc.) | **Locked** |
| 6A | Exit sequencing | Split: risk-exits ship early, edge-exits gated on Phase 3 passing entry-edge criteria | **Locked** |
| 7A | Time/DST | Use `exchange_calendars` library + `docs/planning/FX_TIME_SPEC.md` | **Locked** |
| 8A | Schema metadata | Add `provider`, `ingested_at`, `is_complete` columns | **Locked** |
| 9A | Walk-forward backport | Remove from this plan; track equity-side backport as separate TODO | **Locked** |
| 14A | Phase 2/3 circularity | Split Phase 2 into 2a (port with defaults) + 2c (tune after backtest) | **Locked** |
| 15C | Indicator reuse | Extract `bluehorseshoe/analysis/indicators/` → `src/shared/indicators/`; equity imports from shared; FTMO-specific adds in `bh_ftmo/indicators/` | **Superseded by 15D (2026-04-24)** |
| 15D | Indicator isolation | **Reversed 15C.** Equity indicators are deeply coupled to `weights_config` / `reporting` / `curves` / `constants`; extracting cleanly would require ~1 week of regression-risky refactoring on live equity code. Instead: BH FTMO has fully independent indicators in `src/bh_ftmo/indicators/`. Zero shared code. Intentional duplication over risk to the equity pipeline. | **Locked 2026-04-24** |
| 16A | Entry-edge gate | Strict: Sharpe ≥ 1.0, PF ≥ 1.3, WR ≥ 45%, Max DD ≤ 10%, FTMO pass ≥ 70% | **Locked** |
| 17B | Backtest baselines | Beat three: random-entry, fixed-schedule (Mon/Fri), simple RSI(14) | **Locked** |
| R-1 | No-lookahead tests | Mandatory Phase 2 requirement (not TODO) for multi-pair indicators | **Locked** |
| R-2 | Cron outage alerting | Mandatory Phase 6 deliverable (not TODO) — no cutover without Friday-cron alerts | **Locked** |

---

## Open Questions — RESOLVED 2026-04-24

1. **OANDA account.** ✅ Brand to register at https://www.oanda.com/demo-account/ — demo sufficient.
2. **Fallback budget.** ✅ $30/mo acceptable for Polygon/TwelveData if OANDA misbehaves.
3. **Project timeline.** ✅ "Take the time to do it right." The "end of week" and "14-day trial" concerns surfaced are *trading-behavior features*, not project deadlines — folded into Phase 4 as `weekend flatten` and `FTMO_CHALLENGE_END_DATE`.
4. **Instrument scope.** ✅ All 40 + crypto if available. Cluster filter mitigates correlation risk. Crypto source confirmation is a Phase 1 task.
5. **Dashboard.** ✅ Terminal-first (primary); HTML dashboard is Phase 7 polish.
6. **Live execution someday.** ✅ Future work. OANDA's dual use (data + execution) noted as a tailwind.

### Remaining Design Questions (resolve during phase work, not blocking)

- **Challenge-deadline behavior specifics** — what exactly does "become more conservative" mean numerically? Decide during Phase 4 design review.
- **Crypto data source** — OANDA vs. Binance/Coinbase API. Decide during Phase 1 after confirming OANDA's instrument list.

---

## Risk Gates

- **End of Phase 1:** can we reliably pull 4h bars? If no → pivot to HistData.com bulk + weekly delta updates.
- **End of Phase 3:** does backtest sanity-check against naive buy-and-hold (e.g., EURUSD over 5 years)? If no → stop adding features, debug.
- **End of Phase 4:** does exit scoring measurably improve risk-adjusted return vs. fixed-ratio exits on the same trade set? If no → simpler exit logic, don't ship complexity for complexity's sake.
- **Before cron cutover:** 2+ weeks of parallel paper trading with acceptable regression delta vs. BH Lite.

---

## Test Strategy

- **Unit tests** per new indicator (synthetic 4h data)
- **Integration tests** — full signal pipeline from cached bars → ranked + filtered signals
- **Backtest tests** — known-outcome sample trades (verify P&L arithmetic)
- **Golden tests** — freeze one known backtest run's output; future changes flag diffs for human review
- **DST / session edge cases** — explicit tests for DST shifts, weekend gaps, 23:00 UTC vs 22:00 UTC boundary
- **FTMO rule tests** — synthetic trade sequences that should fail daily-loss, max-DD, trailing-DD

---

## Not In Scope (Explicitly)

- Automated trade execution via FTMO — manual paste from `bh_ftmo_orders.json` is acceptable through v1
- Multiple account management
- Multi-timeframe confirmation (1h context for 4h signals) — consider for v2
- Machine-learning-based exit scoring — start with weighted indicators, graduate to ML only if weights plateau
- Portfolio-level correlation optimization beyond the existing cluster filter
- Tax accounting or trade journaling UI

---

## Next Step

1. ~~User reviews this plan, redlines anything they disagree with~~ ✅ Done 2026-04-24
2. ~~Answer the six Open Questions~~ ✅ Done 2026-04-24
3. ~~Run `/plan-eng-review` to stress-test the architecture~~ ✅ Done 2026-04-24 — 14 decisions locked, 3 TODOs filed, 2 items elevated to mandatory phase requirements
4. ~~Run `/plan-ceo-review` for strategic cross-check~~ ✅ Done 2026-04-24 — HOLD SCOPE mode, 6 additional decisions locked (C-1..C-6), no scope changes
5. ~~Begin Phase 0 (copy bh_lite → bh_ftmo package; bh_lite stays frozen)~~ ✅ Done 2026-04-24 (commit `1bf7f9f`)
6. ~~Phase 0.5 (OANDA probe)~~ ✅ Done 2026-04-24 — 40/40 OK, synthesize DXY, defer crypto
7. **Begin Phase 1** (data foundation) ← current step

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | CLEAR | HOLD SCOPE mode, 6 decisions locked (C-1..C-6), 0 critical gaps |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 14 decisions locked (1A..17B, R-1, R-2), 18 Codex findings addressed, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | n/a (no UI scope v1) |
| Codex Review | `codex exec` (inline, eng Step 0.5) | Independent 2nd opinion | 1 | — | 18 findings, all addressed or deferred |

- **CROSS-MODEL:** Claude eng review + Codex inline critique overlapped on ~10 findings (packaging collision, history depth, schema thinness, FTMO rule vagueness, ForexFactory brittleness, Phase 6 duration). High consensus signal.
- **UNRESOLVED:** 0 across all reviews
- **VERDICT:** ENG + CEO CLEARED — ready to implement Phase 0