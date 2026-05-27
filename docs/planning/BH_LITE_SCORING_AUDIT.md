# BH Lite Scoring Audit & Remediation

**Status:** Audit complete 2026-05-26. **Track A shipped (A1–A3) 2026-05-26**; A4 pending (data/decision). Tracks B and C unstarted.
**Drafted:** 2026-05-26
**Owner:** Brand
**Scope:** The scoring path in `src/bh_lite.py` — `score_instrument()`, `rank_signals()`, the context bonus in `_build_signal()`, and everything it inherits from the equities `TechnicalAnalyzer`.

---

## TL;DR

BH Lite was built for expediency by piping the **equities** scoring engine onto a **forex** instrument universe. That shortcut is the root of most weaknesses below. The score is an unbounded additive sum of ~9 stock-tuned indicator categories, taken as `max(baseline, mean_reversion)` per instrument, then ranked across heterogeneous pairs. It is long-only, volume-dependent on a universe with no real volume, trend-biased toward a shape your own research falsified, and calibrated on NASDAQ percentiles.

None of this means BH Lite is worthless — it's a human-in-the-loop morning briefing tool, and a human filters its output. But the score it presents is not a measure of edge in this universe, and several components are silently dead or backwards.

---

## How the scoring actually works today

1. `score_instrument()` (`bh_lite.py:347`) calls the equities `TechnicalAnalyzer.calculate_baseline_score()` and `calculate_technical_score(strategy="mean_reversion")`. Each returns a `.total` that is an **additive sum** of indicator-category scores (trend, volume, candlestick, momentum, moving_average, mean_reversion_specific, curve, price_action, limit) plus penalty/bonus modifiers.
2. `_build_signal()` (`bh_lite.py:775`) adds an intraday-context bonus: `context_score * 3.0` to baseline, `context_score * 3.0 * 0.67` to mean reversion.
3. `rank_signals()` (`bh_lite.py:529`) picks, per instrument, `max(baseline_score, mean_reversion_score)` among setups that pass `is_realistic` and `rr_ratio >= 0.5`, then sorts all instruments by that single number.
4. The score also drives the dynamic entry discount via `SIGNAL_STRENGTH_THRESHOLDS` → `ENTRY_DISCOUNT_BY_SIGNAL`.

---

## Findings

Severity: **S1** = trades on a falsified/structurally-wrong premise; **S2** = dead/meaningless component silently in the score; **S3** = calibration/comparability defect.

### S1-1 — The "baseline" half is the shape the FTMO research falsified
bh_lite's baseline score is trend-following (ADX, breakouts, SuperTrend-style, momentum). The BH FTMO research record is emphatic that this shape is NULL in this universe:
> Donchian NULL, SuperTrend NULL — "H4 forex breakouts can't extend to 1%/1% TP after spread; mean-reversion is the winning shape in this universe."

`rank_signals` takes `max(baseline, mean_reversion)`, so on any given day the trend-following score can win the slot and place a trade in the shape proven not to survive spread. Compounding this: **the scorer applies no spread / transaction-cost haircut at all**, which is exactly the cost that kills trend-following in forex.

- Code: `rank_signals` `bh_lite.py:529`; baseline scoring `technical_analyzer.py:323`.
- Cross-ref: memory `project_donchian_strategy_v1`, `project_supertrend_strategy_v1`, `project_limit_entry_sweep`.

### S1-2 — Long-only on a universe that is half shorts
Every code path produces buys. `rank_signals` only considers baseline (trend-up) and mean-reversion (dip-buy); `_write_orders` hardcodes `"side": "buy"` (`bh_lite.py:826`). The validated v2 portfolio is directional and short-heavy (CAD_CHF short, EUR_USD short, NZD_CHF short, EUR_GBP varies, etc.). bh_lite structurally cannot express any short cell and is silently biased toward USD-weakness / risk-on regimes.

- Code: `_candidate_for_strategy` `bh_lite.py:515`, `_write_orders` `bh_lite.py:817`.
- Cross-ref: memory `feedback_side_column_for_live_orders` (SIDE must be a first-class column — implies SIDE must be a first-class *decision*).

### S2-1 — Volume is faked to 1, which silently breaks a whole category and several modifiers
`fetch_ohlcv` floors forex volume to 1 (`bh_lite.py:128`) because Yahoo returns 0. Downstream in the borrowed engine:
- `VolumeIndicator` (RVOL, OBV, etc.) contributes constant/neutral noise to every forex score — a full category of dead weight.
- `vol_ratio = volume / avg_volume_20` is **always ≈ 1.0**, so:
  - the selling-climax bonus (`vol_ratio > 2.0`, `technical_analyzer.py:237`) can **never** fire;
  - the volume-exhaustion penalty (`vol_ratio > 3.0`, `technical_analyzer.py:240`) can **never** fire.
- `vol_ratio` is still surfaced in setup output as if it carried information.

### S3-1 — Cross-instrument ranking of an unnormalized sum
The score is an additive, unbounded sum with no normalization, then ranked across EUR/USD, USD/JPY, EUR/CZK, USD/HUF, etc. simultaneously (`rank_signals` sort `bh_lite.py:543`). Different pairs have different volatility and the modifiers mix relative (RSI, BB%) with quasi-absolute terms, so a score of 12 on one pair is not comparable to 12 on another — yet that ranking selects which 3 trades get taken.

### S3-2 — `max(baseline, mean_reversion)` compares two incompatible scales
Baseline and mean-reversion use different weight tables (`weights.json` baseline vs `mr_`-prefixed) and different philosophies. Picking the numerically larger total (`bh_lite.py:542`) selects whichever strategy's weights happen to sum larger, not whichever has the real edge.

### S3-3 — Signal-strength tiers are NASDAQ percentiles
`SIGNAL_STRENGTH_THRESHOLDS` (`constants.py:67`) is annotated "top 1% / 5% / 20% / 40% of signals" — percentiles measured on US stocks. Applied to forex scores those buckets are meaningless, yet they drive `ENTRY_DISCOUNT_BY_SIGNAL`. Separately, per the contrarian-short work, that score→entry-distance map is **backwards** (the edge lives at *wider* entry distance, but EXTREME maps to 0.05 ATR / near-market).

- Cross-ref: memory `project_contrarian_short_v1` (ADDENDUM 5: `ENTRY_DISCOUNT_BY_SIGNAL` calibration is backwards).

### S3-4 — Context bonus is unvalidated magic numbers
`context_score * 3.0` (baseline) and `* 0.67` (MR) in `_build_signal` (`bh_lite.py:781-783`) are arbitrary multipliers stacked on an already-unnormalized, un-validated sum. No backtest justifies the 3.0 or the 0.67.

### S3-5 — `_is_dead_or_flat` is an equity-volatility filter
It zeroes scores on "extremely low volatility over 5 days" (`technical_analyzer.py` `_is_dead_or_flat`), tuned to catch halted / pending-acquisition stocks. Pegged and exotic pairs (EUR/CZK, USD/HUF, EUR/HUF) have structurally tiny daily ranges and may be falsely zeroed — or the threshold is so loose it never fires on forex. Either way it is unvalidated here.

### Meta — One generic recipe instead of the validated edge map
The deepest issue: bh_lite scores all ~40 pairs with a single generic equities recipe, while months of BH FTMO research produced a specific per-`(pair, direction, indicator, entry-mechanic)` edge map. The expedient choice ("reuse the stock scorer") discards that map and substitutes a trend-biased, long-only, volume-dependent stock model.

---

## Remediation plan

Ordered by leverage-per-risk. Items are independent unless noted.

### Track A — Stop the bleeding (low risk, fast, no edge claims)
- **A1 (S2-1) ✅ shipped 2026-05-26:** `TechnicalAnalyzer` scoring gained a defaulted `asset_class="equity"` param; `"forex"` skips the `volume` category in `_score_indicators` and the vol-ratio branches in `_calculate_baseline_modifiers`. bh_lite derives it per instrument via `asset_class_for_instrument()` (forex → "forex"; indices/metals/crypto keep real volume → "equity"). Equities and `bh_ftmo` callers unchanged (default). Tests in `test_technical_scenarios.py`.
- **A2 (S3-5) ✅ shipped 2026-05-26:** `_is_dead_or_flat(days, asset_class=...)` now uses a forex floor (0.08% range / 0.03% std) vs the equity floor (0.5% / 0.2%). The old equity floor was silently zeroing normal-volatility FX pairs. Tested both directions (0.2% range live for forex / dead for equity; 0.02% frozen still caught).
- **A3 (S3-4) ✅ shipped 2026-05-26:** context multipliers moved out of inline magic into `bh_lite_config.json` → `context: {baseline_weight: 3.0, mr_weight_ratio: 0.67}`, read in `_build_signal` with documented defaults. Values unchanged (no edge claim) — now tunable/visible.
- **A4 (S3-3) — pending (data + decision):** Recalibrate `SIGNAL_STRENGTH_THRESHOLDS` against the forex score distribution (needs a distribution-gathering run across the ~40-pair universe), or decouple bh_lite from the equities constant. **The `ENTRY_DISCOUNT_BY_SIGNAL` "backwards" flip is BLOCKED** by the volatility-confound open blocker in `project_contrarian_short_v1` — do not flip until within-volatility-quintile decomposition is done.

### Track B — Make the score honest (medium)
- **B1 (S3-1):** Normalize per-instrument before cross-instrument ranking (e.g. z-score or percentile against that pair's own recent score history) so the top-3 selection compares like with like.
- **B2 (S3-2):** Stop using `max(baseline, mean_reversion)` as a cross-strategy selector. Either keep the two streams separate with their own slots, or rank within a strategy and never compare raw totals across strategies.

### Track C — Align with the research edge (high value, larger build)
- **C1 (S1-2):** Add short signals. At minimum, generate mean-reversion shorts; ideally drive direction from the validated per-pair cells.
- **C2 (S1-1):** De-emphasize or gate out the trend-following baseline in the forex universe, or add a spread/cost haircut to the score so trend setups must clear the cost the research says they can't.
- **C3 (Meta):** Replace (or overlay) the generic recipe with the per-`(pair, direction, indicator, entry)` edge map from the v2 graduation work, so bh_lite scores what was actually validated rather than a generic stock model. This is effectively converging bh_lite toward the BH FTMO autonomous-trader scoring — coordinate with `BH_FTMO_PLAN.md` so we don't build it twice.

---

## Notes & caveats
- BH Lite is a **human-in-the-loop morning briefing tool** (per the two-track pivot, memory `project_two_track_plan`). A human filters its output, which bounds the real-world risk of these defects. The autonomous trader is where edge correctness is non-negotiable.
- Tracks A and B improve signal quality without claiming new edge and are safe to ship incrementally. Track C overlaps heavily with the BH FTMO autonomous-trader scoring layer — decide whether to invest in bh_lite-specific work or fold it into the FTMO plan before starting C3.
- Anything touching live FTMO signal generation should be eyeballed against real output before deploy (memory `feedback_validate_before_deploy`).
