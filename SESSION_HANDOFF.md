# Session Handoff

**Date:** April 27, 2026
**Status:** Phase 3 framework ran end-to-end on a research droplet for the first time. Gate verdict: **FAILED across all criteria** (13,538 trades, 30 walk-forward folds, ~30 min on a c2-48vcpu-96gb). Surfaced and fixed four lurking engine bugs before getting a clean run. The verdict is *informational, not actionable* — the real next blocker is **indicator validation**: `src/bh_ftmo/indicators/` has zero unit tests and the implementations are hand-rolled pandas/numpy (NOT ports of equity-side `talib.*` calls). Until each indicator is verified against TA-Lib reference output, no weight tuning or strategy fix is meaningful.

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

- **Indicator Validation Suite (NEW — top priority).** Build `src/tests/bh_ftmo/indicators/test_*.py` files that compare each BH FTMO indicator (RSI, MACD, ADX, Stochastic, CCI, Williams %R, SMA, EMA, SuperTrend, Donchian, Ichimoku, ATR, Bollinger, candlestick patterns) to TA-Lib output on a shared OHLC fixture. Where they diverge in the warmup window only, document it. Where they diverge after warmup, that's a bug and gets fixed. No further weight tuning, strategy patching, or gate re-runs are meaningful until this is done.
- Phase 3 framework otherwise complete and battle-tested (four engine bugs found and fixed during the first end-to-end gate run).

## Next Steps

1. **Build the indicator validation suite.** Will be a Codex Next Action. Likely 2-3 actions: (a) `momentum.py` → `test_momentum.py`, (b) `trend.py` + `volatility.py` → `test_trend.py` + `test_volatility.py`, (c) `candlestick.py` + `pivots.py` + `strength.py`. Compare each function's output to `talib.RSI` etc. on a fixture; assert near-equality after warmup. Document divergences.
2. **Add `--strategies` CLI flag to `bh_ftmo.backtest.cli`** for per-strategy isolation. Currently `cli.py:190` hardcodes `SignalGenerator(strategies=[BaselineStrategy(...), MeanReversionStrategy(...)])`. Add a flag that lets the gate run Baseline alone, MR alone, or both. Pair with `--limit-folds N` for fast iteration. Subordinate to indicator validation.
3. **After indicators are trusted** — re-run the Phase 3 gate (Baseline-only first, then MR-only, then composite). The four engine fixes from this session may have already moved the needle; if not, the structural findings (Baseline long-only, ASIA losses, AUD cluster) become actionable.
4. **Investigate Sharpe/MaxDD mismatch in reporter** — per-strategy table shows 0.20 Sharpe, 22.2% MaxDD; verdict block shows -2.90, 14.6%. They're computing on different equity-curve bases. Low-effort fix once spotted.
5. **Brand action items still open from prior sessions:**
   - Run `bash /tmp/humanaction.sh` to install every-4h incremental-update cron (when re-emitted; the slot has been used for droplet provisioning lately)
   - Install GitHub App before May 8 so `trig_01RfvYoMo6V7bETCRBLn5WNT` (BH FTMO check-in routine) can run
   - SMTP from Claude Code sandbox is blocked — Brand runs `send_report_email.py` manually for equity reports
6. **Phase 2c — Indicator Tuning** kicks off only after (a) indicator validation passes AND (b) the Phase 3 gate produces a *passing* verdict on validated indicators.
7. See `TODO.md` for full backlog and `docs/planning/BH_FTMO_PLAN.md` for the locked plan.

## Blockers / Open Questions

- **Indicator correctness is unverified** (newly recognized this session) — see In Progress above. This blocks all weight tuning and strategy debugging downstream.
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
**Working tree:** clean (one stray duplicate `bh_ftmo_gate_*.html` at repo root from manual scp; identical to the canonical copy in `src/graphs/` — safe to delete)
**Active feature branches:** `docs-refresh-indicator-validation` (this branch, awaiting merge)
**This session's commits:** `5f7fc3b`, `4ce0070`, `f328161`, `d595c2b` (doc-refresh sweep), `c2577e5` (merge_branch.sh), `94f3885`, `c20f244` (.gitignore), `1ea889c` (dead-field cleanup), `9f321e3`, `384f084`, `eeb2225`, `b34db4f` (engine bug fixes)
**Phase 3 commits (April 25):** `02d3234`, `68a169c`, `e7e1503`, `7541516`, `c49ab49`, `418d214`, `d2052bd`, `1d93201`, `9844244`, `5b50d57`, `e3af17a`, `e842d9a`
**Tests:** 1396 passing, 3 skipped (verified prior to this session; engine bug fixes carry their own pytest validation per Codex Next Action protocol)

---

**Last Updated:** April 27, 2026
