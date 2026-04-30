# TO-DO

## Near Term

### 🔥 PRIORITY — Investigate forecast-vs-gate gap on sandbox_v1 (added 2026-04-29 evening)

**Why this leads now:** The sandbox-track validation predicted 12-14% pass rate on full walk-forward. The production gate on `s-8vcpu-16gb` droplet (16 folds, 202 starts) returned 2.5% pass rate — statistically tied with random_baseline at 2.5%. Until we understand WHY they disagree, sandbox_v1 is **not deployable**, and any new strategy work risks repeating the same flaw.

**Hypotheses to test, cheap-to-expensive:**
1. **Methodology mismatch** — does the production gate's pass-rate calculator use the same definition as the sandbox notebook? (Daily-fail vs total-fail vs profit-target threshold semantics; bootstrap CI vs point estimate; cohort sampling vs all starts.) Diff the two scoring code paths first; could be a 1-line definition mismatch that explains everything.
2. **Lookahead leakage in sandbox notebook** — does the sandbox harness use any future information for entry timing, signal eligibility, or pair selection? Look at `/tmp/sandbox_*.py` for `shift(0)` / `iloc[:i+1]` patterns that subtly include the current bar's data in the previous bar's decision.
3. **Port introduced subtle differences** — diff `SandboxStrategy.score_pair` against the sandbox harness's signal generation. Particular focus: %K crossing semantics (cross-up THIS bar vs SETUP-on-previous-and-FILL-on-this), ATR window, RSI seed (Wilder vs simple), bar boundary rounding.
4. **Pair whitelist drift** — sandbox said 22 dropped, production drops 21. Confirm the 4-pair short whitelist actually applies in production runs.
5. **Active overlay misbehavior** — sandbox didn't have a production overlay to compare against; the `relax_10` config could be killing strategy edge in ways the sandbox harness wouldn't catch.

**Smoking-gun candidates to eyeball in the gate HTML/CSV first:**
- Per-pair P&L distribution — is one symbol responsible for most of the deficit?
- Trade duration histogram — many timeouts vs many stop-outs hint at different problems
- Win/loss clustering — long losing streaks could indicate regime-specific failure
- Compare gate trade ledger to a sandbox harness run on the same windows

Artifacts: `src/graphs/sandbox_v1_full_2026-04-29_2311.html`, `src/logs/sandbox_v1_full_2026-04-29_2311.csv`. Sandbox-side at `/tmp/sandbox_*.py` and `/tmp/sandbox_*.csv`.

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
