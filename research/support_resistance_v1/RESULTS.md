# support_resistance_v1 — RESULTS (2026-06-18)

**Question.** Does proximity to / structure of horizontal support–resistance levels
carry tradeable or even just *predictive* edge on US equities?

**Verdict: NO — two independent nulls.**

## v1 — proximity selector (bracket harness)
Swing-pivot + volume-strength levels, distance-to-support as an entry signal on the
TP2:SL1 hold-10 bracket (clean_harness ruler). Newey-West full-pop:
- distance-to-support → forward R is **flat / non-monotonic** (nonbull: 0.197 at 0–0.25 ATR
  vs 0.196 at 2+ ATR). Opposite of deep-oversold depth-monotonicity.
- "strength" **anti-selects**: near-weak-support +0.020R vs near-strong-support −0.011R.
- Existing implicit proxies (Donchian-low, BB-%B) already dominate it (~+0.033R t≈5).
- As a conditioner on deep-oversold it is **subtractive** (0.140R → 0.061R).

## v2 — rejection-confirmed zones (respect-rate, matched random baseline)
Rebuilt to Brand's spec: a level = a RANGE, confirmed only after anchor → depart
≥D ATR → retest (wick), volume-weighted center, body-close invalidation, broken=dead.
Metric: respect_rate(confirmed real levels) − respect_rate(matched random lines).
**68-combo sweep**, 250 symbols, 2016+:
- max lift **+0.0065** (≈0.9σ, n=8009 — not significant); mean −0.0022; **0/68 above +0.02**.
- Tightening confirmation raises absolute respect to ~0.50 but the random baseline
  rises in lockstep → lift stays ~0.
- Both width modes, D, min_touches, min_bars, invalidation strictness, volume gate
  all swept. PIT-verified (a lookahead leak via the evolving vol-weighted center was
  caught and fixed). Real null, not an artifact.

**Conclusion.** A proven, rejected-and-retested level is respected no more often than
a random horizontal line. S/R "memory" is not measurable here. The v2 detector is,
however, a **faithful level-drawer** (Brand-verified that it kills single-touch junk) —
the detector succeeds; the predictive hypothesis fails.

## Reusable artifacts
- `detector.py` — v1 swing-pivot/volume detector + `level_snapshot`/`dump_levels`.
- `detector_v2.py` — rejection-confirmed zone machine (`detect_zones`, `active_levels`,
  `prepare`); a clean S/R annotation tool independent of any edge claim.
- `eval_sweep.py` / `gen_grid.py` — respect-rate sweep harness + matched random baseline.
- `results_all.csv` — all 68 combos.

## Doors NOT yet opened (ranked by prior, all lower than the campaign's open frontier)
1. Reaction *magnitude* (not hit-rate): is the bounce off a confirmed level bigger than
   off a random line? Distinct question; cheap reuse of the harness.
2. Confluence / multi-level stacking (note: confluence already died on forex).
3. Polarity flip (broken support → resistance) — Brand flagged to revisit later.
4. S/R as exit-target placement on the deep-oversold sleeve (weakened by the respect null).
