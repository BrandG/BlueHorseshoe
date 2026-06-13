# BH FTMO — ATR / Volatility-Regime Conditioner v1 (Design)

**Status:** Design locked — not yet run. Build spec; results appended (or in
`research/atr_regime_v1/`) once executed.

**Date locked:** 2026-06-13

**Owner / product:** BUD (forex/FTMO). Lab = `bh_ftmo/`; cells via `bud.briefing` + the v2 CI gate.

---

## 1. Motivation

Dislocation-depth is null ([`DISLOCATION_DEPTH_v1.md`](DISLOCATION_DEPTH_v1.md) §13), but its
ATR-stratification sanity check surfaced a clean, *repeated* signal: across **five independent
long MR cells**, per-trade R is significantly positive in low/mid volatility and ≈0/negative in
high ATR — the opposite of depth. The equity deep-oversold edge was *regime*-gated; what transfers
to forex is the **volatility** regime, not depth. This scope tests and (if it holds) deploys that.

## 2. Hypothesis

**H:** Per-trade R of the deployed mean-reversion cells is monotonically higher in lower
volatility regimes; gating or down-sizing high-ATR entries lifts book-level expectancy without
materially cutting throughput.

**Falsified if:** the low/mid > high ATR R-gradient does not survive Newey-West both-halves /
de-overlap, isn't robust across pairs, is purely a per-pair/era selection effect, or is just
generic "forex is hard in high vol" beta-regime that any position shares (§5).

## 3. Scope

The deployed mean-reversion cells (start with the 6 dislocation-family cells bb/rsi/cci/sma/ema/
stoch; extend to all deployed v2 cells in P2). The P1 signal is cleaner on the **long** side —
test long and short separately, do not assume symmetry.

## 4. Regime metric

Primary: **ATR percentile**, rolling 252-bar, **per-pair**, strictly causal/PIT (already computed
as `ATR_percentile` in `research/dislocation_depth_v1/depth_fires.csv` — confirm the rolling window
uses only past bars). Buckets low 0–33 / mid 33–67 / high 67–100. Secondary formulations to test
in P2: absolute ATR, ATR/price (vol-as-fraction), and a 2-state low-vs-high split.

## 5. The two controls that decide whether this is real

1. **Selection vs regime.** Is "low ATR good" actually "certain pairs / certain eras good"? Control
   with **per-pair** within-pair percentile (already), split **both halves**, and check the
   gradient isn't concentrated in one volatility era (e.g. calm 2017 vs 2020 spike).
2. **Alpha vs beta-regime.** Is high-ATR bad for *these MR cells* specifically, or for *any* forex
   exposure? Compare the regime-R gradient of the cells against a baseline (always-in MR / random
   entry) over the same bars. If a flat baseline shows the same low>high gradient, the conditioner
   is generic vol-beta, not cell alpha — still possibly usable, but characterize it honestly.

## 6. Method

1. Reuse `depth_fires.csv` (entry_ATR, ATR_percentile per fire) and the P1 per-fire R machinery
   (`p1_depth_r.py` / `_lib.py`, deployed 1%/1% RR, mid entry, fixed `MAX_HOLD=84`).
2. Per (cell, direction, ATR-regime bucket): mean_R / SE / CI, pooled across 17 pairs + per-pair.
3. Monotonicity low→mid→high (Spearman / slope) and the **cross-cell consistency** test — is the
   low>high gradient shared across cells that don't share signal logic? (That consistency is the
   strongest evidence it's a market-regime property, not per-cell noise.)

## 7. Gate stack (staged)

- **P1 (rigor on the existing signal):** Newey-West (L = hold−1, both halves; de-overlap is biased
  → [project_deoverlap_signflip_newey_west]), per-pair robustness, cross-cell consistency. Plus the
  §5 selection control. Kill-or-advance.
- **P2 (characterize):** the §5 alpha-vs-beta-regime baseline; long/short asymmetry; regime-metric
  formulations (absolute ATR vs percentile vs ATR/price); extend to all deployed v2 cells.
- **P3 (deploy):** book-level sim of three conditioner forms — (a) hard gate (skip high-ATR), (b)
  size-down high-ATR, (c) size-up low-ATR — measuring book expectancy, **throughput** ($/day per
  slot, [project_tp_throughput_analysis]) and max-DD vs the unconditioned book. Prefer a sizing
  tilt over a hard skip unless high-ATR R is clearly ≤ 0.

## 8. Deployment form (if it survives)

A **volatility-regime risk multiplier** in the v2 sizing path (≤1 in high ATR, ≥1 in low ATR),
analogous to the conviction-sizing tilt — preserves throughput vs a hard filter. FTMO note: high-
ATR periods cluster around news/gaps; the Swing account exempts news/weekend holds, so a vol gate
also has a risk-control read, not just expectancy.

## 9. Harness reuse / new code

**Reuse:** `depth_fires.csv`, `p1_depth_r.py` (R-sim), `_lib.py`, `seed/nw_regate.py` (Newey-West),
the v2 book sim for P3. **New:** a regime-bucketed R analyzer + the §5 baseline comparison in
`research/atr_regime_v1/`. **No production changes** until the conditioner survives P3.

## 10. Phasing

- **P1** — regime-R curves + NW both-halves + per-pair + cross-cell consistency + selection control.
- **P2** — alpha-vs-beta-regime baseline; long/short; metric formulations; all deployed cells.
- **P3** — book-level gate/size sim (throughput + DD); sizing-tilt design + deploy call.

## 11. Deliverables

- `research/atr_regime_v1/` — analyzer + baseline scripts, regime-R curves CSV, verdict MD.
- Memory rollup either way: survivors → vol-regime sizing conditioner spec; or a documented null
  routing to relative-value / cointegration.

## 12. Success criteria

- **Positive:** the low/mid > high ATR R-gradient survives NW both-halves **and** per-pair
  robustness **and** is distinguishable from generic vol-beta → a vol-regime sizing conditioner on
  the v2 book, validated at book level.
- **Null (still a win):** gradient vanishes under NW/both-halves or is pure beta-regime → not a
  cell-level lever; route to relative-value / cointegration (door #2).
