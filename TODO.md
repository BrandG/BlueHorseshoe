# TO-DO

## Near Term

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

- **`--strategies` CLI flag for per-strategy isolation** (added 2026-04-27, **promoted to top of next-up queue 2026-04-27**) — `cli.py:190` hardcodes `SignalGenerator(strategies=[BaselineStrategy(weights=weights), MeanReversionStrategy(weights=weights)])`. Add a flag so the gate can run Baseline-only, MR-only, or both (preserving today's behavior as default). The CLI already has `--limit-folds` and `--limit-starts`, so combining them gives a quick per-strategy verdict. Codex Next Action drafted on branch `cli-strategies-flag`.

- **Baseline appears long-only** (added 2026-04-27) — first gate CSV shows 0 short trades out of 3,652 baseline trades. Likely a strategy-implementation bug, not weights. Investigate after indicator validation passes (so we know it's not e.g. an inverted RSI).

- **Engine: weekend-flatten architecture** (added 2026-04-27, deferred) — the four engine fixes this session all worked around the same root cause: FX week-end (Friday 21:00 UTC) creates data gaps that callers must handle. A proper architectural fix would be to flatten *all* open positions at the Friday-close bar before the gap rather than carrying them across. Out of scope for the bug-fix sweep, but should land before Phase 4.

- **RSI/EMA-family seed-init mismatch with TA-Lib** (added 2026-04-27, low priority — full validation suite informs the recommendation) — momentum + trend + volatility validation (`5e962d8`, `ef31efc`) confirmed every Wilder-smoothed bh_ftmo indicator (RSI, EMA, ADX, ATR) converges to TA-Lib in steady state but diverges in warmup because TA-Lib seeds with SMA-of-first-period and pandas `ewm(alpha=1/p)` skips the SMA seed. **Magnitudes vary dramatically by indicator:** RSI(14) needed `period * 12` warmup at 1e-3 tolerance (max divergence 0.33 RSI points at `period * 5`); ATR(14) at the same warmup converges to 1.57e-09 (essentially perfect). The difference is that ATR's value range is ~1e-3 so absolute divergence at convergence is correspondingly tiny, while RSI lives on a [0,100] scale where the seed-mismatch shows. **Recommendation: close as wontfix.** Walk-forward IS windows are 18 months (>>200 bars warmup), incremental updates carry state in production, and changing the seed would invalidate all prior research. The "first 28 days are noisy" caveat applies only to a true cold-start, which we don't run.

- **Codex sandbox: design test-validation workaround** (added 2026-04-25) — Codex's command sandbox uses `--unshare-net` / `network_access:false`, blocking Docker network access. MongoDB at `127.0.0.1:27017` is unreachable from inside Codex, so any pytest run that hits MongoDB fixtures (e.g., the equity-side `SwingTrader()` fixture in `test_dynamic_entry.py`) fails deterministically with `[Errno 1] Operation not permitted`. Three options for future Codex Next Actions that need test validation: **(a)** Brand runs pytest from his shell (which has Docker access) and supplies the count to the Next Action — already used as the workaround for the 2026-04-25 doc-refresh sweep; **(b)** add pytest markers (e.g., `@pytest.mark.requires_mongo`) to MongoDB-dependent tests so Codex can run a Codex-runnable subset via `pytest -m "not requires_mongo"`; **(c)** reconfigure Codex's sandbox to allow Docker network access (out of scope for code changes — would need Codex setup work). Pick one before the next Next Action that needs a test gate.
