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
  *(Done 2026-06-13 — see §13. Verdict: borderline-positive, not the strict 0/12 null Codex reported;
  re-gate at correct altitude before deciding.)*
- **P1b (re-gate)** — fix the NW lag (L = realized-hold−1, not MAX_HOLD−1) and judge the **pooled
  long-MR sleeve** under NW both-halves, not per-cell-per-half. The per-cell strict gate was
  underpowered (half-n NW) — the v2 NW lesson: per-cell collapses, the book survives.
- **P2** — alpha-vs-beta-regime baseline; long/short; metric formulations; all deployed cells.
  *(Done 2026-06-14 — see §14. Alpha CONFIRMED (sleeve ≫ all-bars baseline, survives date-cluster
  SE), but the gradient is metric-specific: holds under rolling ATR percentile, inverts under
  per-pair level metrics → robustness OPEN.)*
- **P2b (metric-robustness probe)** — is the edge "calm relative to recent" (real, time-local) or an
  artifact of the 252-bar percentile construction? Test alternative TIME-LOCAL vol metrics
  (`ATR/SMA(ATR,50)`, percentile at 60/500-bar windows). Corroborate → P3; only-the-252-rank →
  artifact → relative-value. **Gates P3.**
  *(Done 2026-06-14 — see §15. GRADIENT is window-robust (not a 252-artifact) → advance; but the
  alpha-vs-beta EXCESS is metric-sensitive (significant only on w252), so deploy on w252 and let
  P3's book-level baseline be the final arbiter.)*
- **P3** — book-level gate/size sim (throughput + DD); sizing-tilt design + deploy call. Deploy on
  the causal/PIT **w252** rolling percentile. Frame as a vol-regime risk/sizing lever (the alpha is
  real-but-metric-sensitive); the **book-level baseline** (conditioned vs unconditioned vs
  random-entry, in $/throughput/DD) is the deployable-value arbiter. **Max-DD reduction is itself
  deployable for FTMO** (hard drawdown constraint) even if expectancy uplift is modest.

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

---

## 13. P1b result — sleeve SURVIVES book-level re-gate; alpha-vs-beta (P2) is the decider (2026-06-13)

P1's strict per-cell-per-half null was a gating artifact (§ ATR_REGIME_P1.md audit). P1b
(`atr_regime_p1b.py`, `ATR_REGIME_P1B.md`, `atr_regime_sleeve_curves.csv`) re-gated at the right
altitude — corrected NW lag (median realized hold 23 → **L=22**, not MAX_HOLD−1=83) and a **pooled,
deduped long-MR sleeve** (one trade per pair-bar-direction).

**It holds.** Strong-4 long sleeve (bb/rsi/ema/stoch, n=40,153): low/mid **+0.051R (NW_CI_low
+0.027)** — an absolute tradeable +R; low/mid−high uplift **+0.062 (NW_CI_low +0.022)**; **NW-positive
in BOTH halves** (h1 CI_low +0.003, h2 +0.007); per-pair 12/17. Full-6 sleeve also holds (+0.053,
CI +0.016). Crucially it survives **even at L=83** (CI_low +0.010) — so the rescue was the
book-level pooling (the v2 NW lesson: per-cell collapses, the book survives), not the L choice.
**Short side null** → long-only conditioner.

**Not yet a validated edge.** "Survives rigor" ≠ "is alpha." The decisive test is **P2's
alpha-vs-beta-regime baseline:** is low-ATR-good specific to these MR cells, or would any forex long
(random-entry baseline) show the same gradient? If the latter, it's generic vol-beta (risk-control,
not selection edge). Secondary caveat: the pooled NW is time-series only; contemporaneous cross-pair
correlation makes the pooled CI somewhat optimistic (12/17 per-pair mitigates; a date-clustered SE
would be more honest) — fold into P2.

---

## 14. P2 result — ALPHA confirmed, but the regime metric's robustness is OPEN (2026-06-14)

`atr_regime_p2.py` / `ATR_REGIME_P2.md` / `atr_regime_p2_baseline.csv`.

**Alpha vs beta: PASS.** Strong-4 long sleeve regime uplift +0.062 vs the all-bars long baseline
+0.009 (baseline n.s., NW_CI_low −0.017). Excess (sleeve−baseline) uplift **+0.053 (NW_CI_low
+0.005, date-cluster_CI_low +0.032)**; excess low/mid R **+0.034 (NW +0.005, cluster +0.021)**. The
MR cells' regime benefit is ~6× the random-long baseline and survives the date-clustered SE → this
is **cell selection alpha, not generic vol-beta** (conditioned on the percentile metric).

**Open flag — metric specificity.** The gradient holds only under the **rolling (time-local) ATR
percentile** and *inverts* under two per-pair *level* metrics (absolute_atr −0.024, atr_over_price
−0.036). All three are bucketed per-pair (checked the code), so this is NOT a cross-pair
comparability artifact — the real axis is **time-local ("calm vs this pair's recent 6-week normal")
vs time-global (full-sample level)**. Two points argue real-not-artifact: (1) the gradient is
specific to MR-selected entries — under the *same* percentile metric the all-bars baseline is flat;
(2) "calm-relative-to-recent" is a coherent adaptive regime and the rolling percentile is the
causal/PIT metric we'd deploy. But two reasonable per-pair metrics disagreeing is a legitimate
robustness concern.

**Decision:** do NOT jump to P3, but it's premature to route to relative-value. **P2b** (§10)
resolves it cheaply — corroborate the time-local edge with alternative adaptive metrics. Codex's
`advance_to_p3=False` is right to pause; its implicit "route away" is premature.

---

## 15. P2b result — GRADIENT robust, ALPHA metric-sensitive → advance to P3 (reframed, 2026-06-14)

`atr_regime_p2b.py` / `ATR_REGIME_P2B.md` / `atr_regime_p2b_metrics.csv`. Two distinct questions:

**Q1 — is the gradient a 252-rank artifact? NO, window-robust.** NW-positive low>high uplift at
w252 (+0.062/NW +0.022), w60 (+0.041/+0.002), w500 (+0.046/+0.005); only `ATR/SMA(ATR,50)` is weak
(+0.031/NW −0.009). 3/4 → the edge survives the metric construction. P2's artifact worry is resolved.

**Q2 — alpha or beta? Metric-sensitive.** The excess-over-baseline is significant **only on w252**
(NW +0.005, cluster +0.032); w500 cluster-only (+0.022); w60 and the ratio are not significant
(NW −0.030/−0.036). Codex's "2/3 corroborate" used a lenient *point-estimate* excess; by the
significance bar the alpha is fragile. Tell: under the short w60 window the **baseline itself** gains
a gradient (~+0.025 vs +0.009 at w252) — at short horizons "recent calm" helps any long → more beta.

**Reframed verdict (corrects Codex's clean "corroborated"):** the vol-regime gradient is real and
window-robust, so **advance to P3** — but deploy on the causal/PIT **w252** percentile (the metric
where the alpha is significant), frame it as a **vol-regime risk/sizing lever** (real-but-metric-
sensitive alpha, not pure selection), and make **P3's book-level baseline the final arbiter** of
deployable value. Max-DD reduction is itself FTMO-deployable even if expectancy uplift is modest.

*(Process note: Codex parked itself ~2.5h on the "nothing heavy 00:30–03:30 UTC" note; today is
Sunday and the heavy pipeline is cron'd Tue–Sat 01:00, so nothing was running — Bubo ran the
analyzer directly. Future contracts should pgrep-gate, not blind-wait on the window.)*
