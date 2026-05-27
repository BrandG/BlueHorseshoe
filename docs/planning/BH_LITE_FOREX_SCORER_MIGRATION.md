# BH Lite → Forex Scorer Migration

**Status:** ⚠️ SUPERSEDED 2026-05-27 by investigation findings — DO NOT EXECUTE AS WRITTEN. Resolving the timeframe risk (#1 below) showed: (a) the H4 edge does not transfer to daily bars, and (b) the H4-native, cell-based, directional, human-in-the-loop briefing this plan wanted **already exists in production** — `src/bh_briefing.py` + `src/bh_briefing_ftmo.py` (run on the H4 cron + daily summary; the latter's docstring says it "replaces/companions bh_lite"). bh_lite is unscheduled and log-dormant since 2026-05-12. The real decision is bh_lite's disposition vs bh_briefing_ftmo, not a daily-bar scorer swap. See memory `project_bh_lite_vs_briefing`. Kept below for the interface analysis, which is still accurate.

---

**(original plan, drafted 2026-05-27. No code written.)**
**Owner:** Brand
**Direction (Brand, 2026-05-27):** OK to split FTMO scoring from equity scoring altogether. Near-term data source: **keep Yahoo**, feed the engine's `generate(pair_dfs)`.
**Goal:** Stop scoring bh_lite's forex universe with the equities `TechnicalAnalyzer`. Route it through the already-isolated forex scorer in `bh_ftmo/analysis/`, which is directional (shorts), volume-free, and DXY/strength-aware.

---

## Key realization

The split we want **already exists**. `bh_ftmo/analysis/` is a complete, isolated, forex-native scorer (Phase 2a/2b of `BH_FTMO_PLAN.md`):

- `SignalGenerator` (`signal_generator.py`) — builds a shared per-run context (synthesized DXY from the 6 ICE constituents + currency-strength frame across the majors) and runs strategies across a multi-pair universe.
- `BaselineStrategy` and `MeanReversionStrategy` (`strategy.py`, `mean_reversion.py`) — `score_pair(df, symbol, dxy, strengths) -> list[Signal]`, one `Signal` per bar.
- `Signal` carries `direction` (+1/-1/0), `score`, `components`, `above_threshold` — **shorts are first-class**.
- Forex-only indicators the equity scorer lacks: `sessions`, `strength`, `dxy_correlation`, `volatility` (`bh_ftmo/indicators/`).
- Its own weights file, fully decoupled: `src/bh_ftmo_weights.json`.

What never happened: migrating the **live briefing tool** onto it. Both `bh_lite.py` and `bh_ftmo/main.py` (a frozen Phase-0 copy of bh_lite) still call the equities `TechnicalAnalyzer`. This migration is that last mile — **a wiring/adapter job, not a green-field build.** It resolves audit findings S1-1, S1-2, S2-1, S3-2, S3-3 in one move.

---

## Interface contract (verified against current code)

**Engine input** — `SignalGenerator.generate(pair_dfs, symbols=None)`:
- `pair_dfs: dict[str, pd.DataFrame]` keyed by OANDA-style names (`"EUR_USD"`).
- Each df needs a `timestamp` column and **bid/ask OHLC columns** (`open_bid`/`open_ask`/…): `score_pair` calls `ohlc_mid()`, which has **no plain-OHLC fallback** — it KeyErrors on Yahoo's `open/high/low/close`.
- DXY context is built only if **all** `DXY_CONSTITUENTS` are present (else `dxy=None`). Strength needs **≥4** of `DEFAULT_STRENGTH_PAIRS` (else `strengths=None`). Strategies degrade gracefully when context is absent (those rules just don't fire).

**Engine output** — `list[Signal]` (one per bar). bh_lite wants the **last bar's** Signal per (pair, strategy).

**Current weights state** (`bh_ftmo_weights.json`): `baseline` long threshold = 8.0, **short disabled** (null); `mean_reversion` two-sided at 3.0; `sandbox_v1` at 0.5. So out of the box, shorts come from `mean_reversion`; baseline shorts are a config toggle.

**Downstream (unchanged) bh_lite machinery:** setup/sizing (`calculate_*_setup`, `calculate_position_size`), cluster filter, position-health, orders JSON, console/CSV output. Only the **scoring call** swaps.

---

## Adapters required

1. **`yahoo_df_to_engine_df(df)`** — rename `date` → `timestamp` (datetime), synthesize zero-spread bid/ask (`open_bid = open_ask = open`, etc.). One small pure function; unit-testable.
2. **Symbol mapping** — bh_lite config has `symbol` (`EURUSD=X`), `name` (`EUR/USD`), `ftmo` (`EURUSD.sim`). Engine wants `EUR_USD`. Add an `engine_symbol` field to each instrument in `bh_lite_config.json` (explicit > derived), or derive once.
3. **`Signal` → bh_lite candidate shape** — either map each last-bar `Signal` into the `{score, components, direction, strategy}` rank_signals consumes, or refactor `rank_signals` to consume `Signal` directly (preferred — carries `direction`).

---

## Phased plan

### Phase 0 — Get the engine green (prerequisite)
The bh_ftmo scoring tests are currently **red**, but it's stale-assertion drift, not breakage: e.g. `test_baseline_picks_up_threshold` expects `min_score_threshold == 3.0` while the tuned config is `8.0`. Confirm the config changes were intentional (they are — direction-specific thresholds were added), update the 8 failing assertions in `test_strategy.py` / `test_signal_generator.py`, get the suite green. **Do not migrate onto a red engine.**

### Phase 1 — Data adapter + run-wide context
- Implement adapters (1) and (2) above.
- Restructure `bh_lite.main()` so it fetches **all** configured pairs first into `pair_dfs` (it already loops over every instrument), then builds context once. Today it scores pair-by-pair; the engine needs the universe together for DXY/strength.
- Add a coverage guard + log: report whether DXY (all 6 constituents) and strength (≥4) context were actually built from the Yahoo universe.

### Phase 2 — Scoring swap (long-only parity first)
- New scoring path: `SignalGenerator([BaselineStrategy(), MeanReversionStrategy()]).generate(pair_dfs)`; index the last-bar Signal per pair/strategy.
- Feed `rank_signals` from Signals. **Keep long-only for this phase** to isolate "did the scorer swap change rankings" from "did adding shorts change behavior."
- Eyeball output against the current equity-scorer run before going further (per `feedback_validate_before_deploy`).

### Phase 3 — Enable shorts (the actual edge unlock)
- Add short variants to the setup calculators: mirror entry/stop/target for `direction == -1` (short entry above market, stop above, target below).
- Drive `side` in `_write_orders` and the orders JSON from `Signal.direction`; **surface a prominent SIDE column** in console/CSV (per `feedback_side_column_for_live_orders`).
- Position-sizing and R/R math must be sign-correct for shorts.

### Phase 4 — Position health + cluster reconciliation
- Re-score open positions through the engine in `check_position_health` (respect the concurrent `drop_forming_bar` work — score the last *closed* bar).
- Decide cluster filtering: bh_lite has its own `apply_cluster_filter`; bh_ftmo has `analysis/cluster_filter.py`. Pick one; don't run two.

### Phase 5 — Cleanup
- **Revert the Track A `asset_class` patch** from the equities `TechnicalAnalyzer` once bh_lite no longer calls it (it was a stopgap; the A3 config-context block stays). Confirm no other forex caller depends on it first.
- Decide the fate of `bh_ftmo/main.py` (frozen bh_lite copy): deprecate, or migrate it the same way. Don't dual-maintain two equity-scorer briefing tools.

---

## Open risks / decisions (need answers before/within planning)

1. **TIMEFRAME MISMATCH (biggest).** The bh_ftmo edge research is **H4** forex; bh_lite scores **daily** bars. The engine's weights/thresholds (`min_score_threshold_long=8.0`, DXY 20-bar lookback, session-overlap bonus) were validated on H4, not D1. Scoring daily bars with an H4-tuned engine is a regime mismatch — the validated edge may not transfer, and `session_label` on a daily timestamp is close to meaningless (a daily bar isn't a session). **Options:** (a) accept the engine as a *better-shaped* scorer than the equity one even un-retuned for D1; (b) re-tune a D1 weights profile; (c) move bh_lite itself to H4. This may be the deciding question for the whole migration.
2. **Yahoo context coverage.** Does the Yahoo universe actually contain all 6 DXY constituents and ≥4 strength pairs as daily bars with aligned timestamps? If not, DXY/strength rules silently never fire and we lose the engine's main advantage over the equity scorer.
3. **Mean-reversion strategy parity.** Confirm `MeanReversionStrategy.score_pair` has the same signature/behavior assumptions as baseline (it does by inspection — verify in tests).
4. **Ranking comparability.** The audit's S3-1/S3-2 (unnormalized cross-instrument ranking, `max()` across strategies) still apply to `Signal.score` unless addressed. Decide whether to fold the Track B normalization in here or defer.

---

## What this resolves (audit cross-ref)
- **S1-1 (trend bias):** engine has the validated forex strategy shape + DXY/strength; trend-following is no longer the default long-only half.
- **S1-2 (long-only):** `Signal.direction` gives shorts (Phase 3).
- **S2-1 (dead volume):** forex indicators don't depend on equity volume at all.
- **S3-2 / S3-3 (incompatible scales / NASDAQ percentiles):** replaced by forex weights + direction-specific thresholds in `bh_ftmo_weights.json`.
- **Meta (generic recipe):** bh_lite scores the validated research engine, not a stock model.
