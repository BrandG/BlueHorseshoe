# BH FTMO — Dislocation-Depth Conditioning v1 (Design)

**Status:** Design locked — not yet run. Build spec; results + verdict appended (or in
`research/dislocation_depth_v1/`) once executed.

**Date locked:** 2026-06-13

**Owner / product:** BUD (forex/FTMO). Lab = `bh_ftmo/`; cells via `bud.briefing` + the v2 CI gate.

---

## 1. Motivation

Confluence is closed ([`CONFLUENCE_SWEEP_v1.md`](CONFLUENCE_SWEEP_v1.md) §14): combining two
signals adds nothing on H4 forex. The *only* thing that ticked up in P1a was `bb+ema` — two
"stretched-below" signals — i.e. **deeper dislocation**, not signal combination. That echoes the
validated **equity** deep-oversold edge (RSI<30 ≥3 bars, monotonic in depth, +0.142R/trade,
nonbull-gated). So the lever to test is **how far past its trigger threshold a single
mean-reversion cell entered** — a *within-cell* conditioner, no new universe, no combination.

## 2. Hypothesis

**H:** Within a deployed dislocation cell, deeper dislocation at entry → monotonically higher
per-trade R. If real, deploy depth as a **conviction-sizing / selection conditioner** (size up
deep entries; do *not* skip shallow ones) so throughput is preserved.

**Falsified if:** no monotonic depth→R relation survives, or the deepest bucket fails to beat the
cell's own baseline expectancy under the gate stack, or the effect is an artifact of volatility
(§5) or one pair. A clean null says depth is not a forex H4 lever and the equity edge does not
transfer → route to relative-value (door #2).

## 3. Scope

The **6 dislocation-family evaluators** (per `factor_grouping.DISLOCATION_FAMILY`): `bb, rsi, cci,
sma, ema, stoch`. **Exclude** macd / atr / ichimoku (trend / volatility / structure — not
dislocation; atr is also a near-pass-through per P0). Use the deployed cells and modal-deployed
params (reuse `deployed_cells()` + `choose_params()`); this conditions *existing* fires, it does
not introduce new signals.

## 4. Depth metric (per signal, two normalizations)

At each trigger bar, record a continuous **depth past threshold**, computed two ways so we can
separate "deep" from "merely volatile" (§5):
- **rsi / stoch / cci:** `threshold − base_value` (oscillator units; deeper = more oversold than
  the cell's trigger needed). For shorts, mirror.
- **bb:** `(lower_band − close)` expressed in (a) band-widths and (b) ATR units.
- **sma / ema:** `(MA − close) − k·ATR` overshoot beyond the cell's band, in ATR units.

Every depth is recorded in **raw** and **ATR-normalized** form. ATR-normalized is the primary
(comparable across pairs); raw is the volatility-confound control.

## 5. The central risk — volatility confound

Deeper dislocations cluster in higher-volatility conditions, and "contrarian short v1" was blocked
precisely by this confound ([project_contrarian_short_v1]). So depth and ATR move together. The
study must separate them:
- Bucket by **ATR-normalized** depth (depth per unit vol) as primary — this is already
  vol-controlled by construction.
- Regress per-trade R on depth **controlling for entry ATR / ATR-percentile**; report the partial
  effect of depth holding vol fixed.
- Report raw-depth buckets too; if raw-depth R-lift vanishes under ATR-normalization, the "edge"
  is volatility, not dislocation — a null, stated as such.

## 6. Method

1. For each deployed dislocation cell, collect all trigger-bar fires (reuse the `DIR_MASKERS`
   trigger machinery from `research/confluence_v1/co_fire.py`); record depth (both norms) + entry
   ATR at each.
2. Simulate per-trade R with `research/v2_executable_regate/harness/_lib.py` at the deployed
   1%/1% RR and entry_mode, fixed `max_hold` (document value + source).
3. Bin trades by depth — fixed ATR-units buckets **and** within-cell quintiles. Per-bucket
   mean_R / SE / n.
4. **Monotonicity test:** Spearman(bucket_index, mean_R) and an R-on-depth slope (with the §5 ATR
   control). Monotone-increasing is the signature; a deepest-tail-only spike is weaker and must be
   flagged as such.
5. Pool across the 17 pairs per (evaluator, direction) — primary level — and report per-pair so a
   pooled slope can't hide one-pair dependence.

## 7. Gate stack (v2 standard, staged like P0/P1)

- **P1 (cheap, kill-or-advance):** raw per-trade R; monotonicity + deepest-bucket vs cell-baseline
  expectancy-CI (`mean_R − 1.96·SE > 0` and lift over baseline).
- **P2 (only on survivors):** Newey-West (L = hold−1, both halves; de-overlap is biased →
  [project_deoverlap_signflip_newey_west]); the §5 volatility-confound regression; per-pair
  robustness.
- **P3 (only if P2 survives):** secondary conditioning — **depth × D1-counter-trend** (the forex
  analog of the equity nonbull-gate; the D1 multi-TF filter already exists,
  [project_multitf_filter_v1]); executable ask/bid fills for any limit cells; throughput / book
  level.

## 8. Deployment form (if it survives)

A **conviction-sizing tilt**, not a hard filter: scale risk up on deep entries, keep shallow ones
at base size — preserves firing volume (throughput-over-expectancy). Mirrors the equity live
sleeve's conviction sizing ([project_live_sleeve_gate]). Wiring point: a depth multiplier in the
v2 sizing path, analogous to the retired rising_3bar RSI amplifier but evidence-gated.

## 9. Harness reuse / new code

**Reuse:** `co_fire.DIR_MASKERS` + `factor_grouping.choose_params/deployed_cells` (trigger +
params); `_lib.py` (R-sim); `seed/nw_regate.py` (Newey-West). **New:** a depth-extraction pass
(per-signal depth at each fire) + a bucketing/monotonicity analyzer in
`research/dislocation_depth_v1/`. **No production changes** until a conditioner survives P3.

## 10. Phasing

- **P0** — define + compute depth per dislocation cell; sanity-check distributions and depth⊥ATR
  correlation (how bad is the confound?).
- **P1** — depth-bucketed R curves + monotonicity, raw, pooled + per-pair. Kill-or-advance.
- **P2** — NW both-halves + volatility-confound regression + per-pair robustness on survivors.
- **P3** — D1-regime interaction, executable fills, throughput; sizing-tilt design + deploy call.

## 11. Deliverables

- `research/dislocation_depth_v1/` — depth-extraction + analyzer scripts, per-cell depth→R curves
  CSV, `DISLOCATION_DEPTH_v1_RESULTS.md` verdict (monotonicity, ATR-controlled effect, per-pair
  robustness).
- Memory rollup either way: survivors → conviction-sizing conditioner spec; or a documented null
  (depth doesn't transfer to forex H4) routing to relative-value.

## 12. Success criteria

- **Positive:** a monotone depth→R relation that survives NW both-halves **and** the ATR-confound
  control **and** is robust across pairs → conviction-sizing conditioner on the deployed MR cells.
- **Null (still a win):** depth-R vanishes under vol-control or isn't monotone → depth is not a
  forex H4 lever; record it and move to relative-value / cointegration.

---

## 13. P0/P1 result — DEPTH NULL, but ATR-REGIME is the live lead (2026-06-13)

P0 (`depth_extract.py`, `P0_DEPTH_DISTRIBUTION.md`) gave a clean vol-decorrelated depth metric
(price-domain depth/ATR corr ~0.64 → ~0.03 after ATR-normalization; oscillators already
vol-independent). P1 (`p1_depth_r.py`, `P1_DEPTH_R.md`, `depth_r_curves.csv`) tested the edge.

**Depth → R is NULL.** 0/12 cell-directions pass both gates (monotone + deepest quintile clears
CI over baseline). ~half show a weak positive Spearman but the deepest quintile never clears
CI_low > 0; the one cell whose deepest *is* significant (rsi long, +0.050 / CI_low +0.011) is
non-monotone (Spearman −0.20); `ema long` is actively inverted (Spearman −0.90). The equity
deep-oversold "deeper is better" does **not** transfer to H4 forex.

**The ATR-stratification sanity check surfaced the real signal.** Across five independent long
cells, R is significantly concentrated in **low/mid volatility and dies in high ATR** — the
*opposite* of depth (high-ATR, where price-gaps are deepest, is worst):

| long cell | ATR low | ATR mid | ATR high |
|---|---|---|---|
| bb  | +0.098 (CI +0.051) | +0.060 (CI +0.014) | −0.001 |
| rsi | +0.072 (CI +0.042) | +0.066 (CI +0.034) | −0.017 |
| stoch | +0.056 (CI +0.037) | +0.032 (CI +0.011) | −0.004 |
| ema | +0.049 | +0.081 (CI +0.034) | −0.020 |
| cci | +0.033 (CI +0.011) | +0.041 (CI +0.016) | +0.014 |

**Reframe:** the equity edge's *regime*-gating transfers to forex as a **volatility** regime, not
a dislocation-depth gradient. These MR cells work in calm/normal vol and fail in high vol.

**Caveats:** this is a byproduct sanity table, not a gated test (needs its own NW / both-halves /
de-overlap pass); the short side is messier than the long side (e.g. sma short inverts).

**Next door:** [`ATR_REGIME_v1.md`](ATR_REGIME_v1.md) — gate/size the deployed MR cells on the
volatility regime. Depth is parked; relative-value / cointegration remains the orthogonal
alternative.
