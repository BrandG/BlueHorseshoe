# Relative-Value / Cointegration — BUD door #2 (v1)

**Status:** Phase 0 (screen). The one orthogonal edge door never opened across the BUD H4-forex
campaign. Confluence, dislocation-depth, and single-pair *selection* are dead
([[project_selection_layer_exhausted]]); vol-regime is a second-order risk trim; the first-order
exit lever is mined and shipped. Cointegration exploits a **relationship between two series**, not a
single series' internal dynamics — a structurally different edge source.

## Thesis

If two instruments A, B share a common stochastic driver, the spread `S = log(A) − β·log(B)` is
stationary (mean-reverting) even though A and B each wander. Trade the spread: when `z = (S − μ)/σ`
deviates, bet on reversion (short the rich leg, long the cheap leg). Edge = the spread's
mean-reversion, which is orthogonal to every per-pair signal already tested.

## The FX-specific trap: triangular arbitrage

`EUR/JPY ≡ EUR/USD × USD/JPY` by arithmetic ⇒ triangle legs are *mechanically* cointegrated with a
~zero-amplitude spread (just bid/ask/rounding) — statistically "cointegrated" but **un-tradeable**.
Any naive screen fills with this garbage. Defense (v1): an **amplitude-vs-cost gate** — keep a pair
only if its spread swing clears 2× round-trip cost. Mechanical spreads have ~0 amplitude → auto-
rejected, no pre-curation needed. (Phase 2 alternative: currency-strength decomposition.)

## Data

- Universe: the **40 FX pairs** from `bh_ftmo_config.json` (commodities/metals held out of v1).
- ~10.4 yr H4 (2016→present, ~16.25k bars), **bid/ask stored** ⇒ 2-leg cost modelled, not guessed.
- Loaders: `FxStore` + `ohlc_mid`; per-leg relative spread = median `(ask−bid)/mid`.
- Dep added: `statsmodels` (Engle–Granger `coint`, `adfuller`).

## Validation (standing BUD rules)

Per [[bud_validation_split_interleaved]]: reserve the **last 24 months as an untouched recent
holdout**; split the pre-holdout era into interleaved calendar-quarter blocks **A** and **B** (COVID
lands in both). Per [[bud_eval_objective_total_pnl]], later phases score by **per-trade total money**
(sum of R at constant risk) — not win rate, not portfolio drawdown.

## Phase 0 — the screen (cheap go/no-go)

For every unordered FX pair (780 combos), estimate on the pre-holdout era and gate:

| # | Test | Gate |
|---|---|---|
| 1 | Engle–Granger cointegration in block **A** and block **B** (independent) | both `p < 0.05` |
| 2 | OU half-life of the spread (`Δs = λ·s₋₁`) | **6–90 H4 bars** (~1–15 trading days) |
| 3 | **Amplitude vs cost**: `2·σ_S` vs round-trip cost `relspread_a + |β|·relspread_b` | ratio **≥ 1** (flag ≥2 = comfortable) |

Report a **funnel** (combos → cointegrated-both-halves → half-life-OK → amplitude-OK) and the survivor
list with `β`, half-life, `σ`, cost, amplitude-ratio. Inspect survivors: if they're all dollar-bloc
trios, suspect residual mechanics.

**Phase 0 is a fast yes/no.** RV pays **two** spreads, and spread was the #1 edge-killer of the whole
campaign — so the amplitude gate is the existential test, run first. If ~nothing clears it, the door
closes cheaply and BUD's edge story is "exits shipped, all else mined."

## Later phases (only if Phase 0 lives)

- **P1:** z-score backtest on survivors (enter |z|>2, exit z→0, stop |z|>3.5 or time-cap 2× half-life),
  full 2-leg bid/ask **+ swap/carry** netted in, scored by per-trade total money, both halves.
- **P2:** recent-holdout dress rehearsal + rolling-β stability. The classic pairs-trade death is a
  **structural break** (spread diverges instead of reverting; the stop-out is the worst trade) — the
  holdout is non-negotiable. Deploy decision gated by Brand.

## Named risks (honest, up front)

1. **Double spread** — existential; Phase-0 step 3 tests it directly.
2. **Relationship instability** — pairs break; require both-halves + holdout + rolling β.
3. **Carry/swap** — held RV legs accrue financing; a negative-carry pair bleeds while reverting.
   Netted in P1 (Swing account holds over weekends, which helps).
4. **Multiple testing** — 780 combos; gate on both-halves + holdout, never single-sample p.

## Artifacts

`research/relative_value_v1/rv_p0_screen.py` (+ `rv_p0_survivors.csv`).
