# Newey-West column in clean_harness — ready to run

**Status (2026-06-05):** wired + smoke-verified in a sub-session. NOT run at full scale yet
(deliberately deferred to avoid collision). Pick up here.

## What changed
`research/indicator_screen/clean_harness.py` — PASS 2 now reports **three** numbers per signal
side by side, instead of just the de-overlapped one:

- **DE-OVERLAP** — the existing production-faithful number (`noov`, one position at a time). Unchanged.
- **FULL-POP (cluster)** — *every* firing kept (no de-overlap), same symbol-clustering. Isolates
  whether de-overlap **moves the point estimate**.
- **FULL-POP (Newey-West)** — every firing kept, trade-weighted, Bartlett/HAC t. Bandwidth
  `L = BR_N-1`; kernel weight `(BR_N-j)/BR_N` **is** the true forward-window overlap fraction, so a
  re-fire j bars later is automatically counted as `(BR_N-j)/BR_N`-redundant in the variance. This is
  the **honest-power** t — keeps all data, corrects the SE for overlap instead of throwing rows away.

New machinery (all additive, de-overlap path untouched): `BF`/`bumpF`, `NW`/`bumpNW`, `NW_W`/`L_NW`,
`stNW`, and the PASS-2 print block.

## Why (the conversation that drove it)
De-overlap with a flat N-bar block treats a day-1 re-fire (≈90% the same bet) identically to a day-9
re-fire (≈10% overlap, almost a fresh bet covering a later window) — so it discards nearly-independent
signal. Overlapping forward returns have a *triangular* autocorrelation that dies at lag `BR_N`; that
triangle **is** the Bartlett kernel. So the rigorous fix is Newey-West(`BR_N-1`) on all firings, not a
hard block. (Two follow-on trading ideas were raised but NOT built: conditional-on-persistence /
scale-in curve, and rolling re-entry re-struck off current price. See below.)

## How to run
```bash
cd /root/BlueHorseshoe && .venv/bin/python research/indicator_screen/clean_harness.py
```
Real config is `N_SYMBOLS=2000` (~minutes; read-only DuckDB). **First check** `pgrep -f main.py` is
clear — never run alongside `-p`/`-u` (OOM risk per CLAUDE.md).

## What to read in the output
1. **Sanity:** RANDOM full-pop & full-NW must be ≈`+0.000R t=0.0` (confirms demeaning). Verified in smoke.
2. **Does de-overlap distort?** Compare DE-OVERLAP mean vs FULL-POP(cluster) mean. If they agree →
   de-overlap is unbiased. If they diverge → de-overlap is moving the estimate (the original worry).
3. **Honest significance:** full-NW t. If a signal's NW t collapses vs de-overlap t, its significance
   was leaning on overlap-correlated firings. If NW t is *stronger* (e.g. below_cloud in smoke: deov
   t1.1 → NW t2.4), that's the "keep all data → real power" win.

## Smoke-test preview (120 symbols — PLUMBING ONLY, not a finding)
`rsi_oversold`, nonbull: DE-OVERLAP **−0.032R t−0.4** | FULL-POP(cluster) **+0.180R t+3.0** |
FULL-POP(NW) **+0.067R t+1.4**. The de-overlap and full-pop point estimates **disagree** (deov reads
~zero; keeping all firings flips firmly positive — consistent with the depth-monotonic oversold edge
living in the deeper-in-run bars that de-overlap drops). But the naive full-pop cluster t (+3.0) is
overlap-inflated; NW honestly discounts it to +1.4. **Read the real 2000-symbol numbers before
concluding anything** — and note cluster (symbol-weighted) vs NW (trade-weighted) also differ by
*weighting*, so a cluster-vs-NW mean gap signals an edge concentrated in few-firing symbols.

## Caveats / known limits
- NW kernel is mildly **conservative**: brackets can resolve early, so real overlap ≤ `(BR_N-j)/BR_N`.
- Cluster col is symbol-weighted; NW col is trade-weighted. Mean differences can be weighting, not just
  de-overlap. Keep that in mind when attributing a gap.
- Only PASS 2 signals got the treatment (PASS 1 close-to-close untouched).

## Not built (future, if the NW read warrants)
- **Conditional-on-persistence curve:** forward R of the day-k entry as k grows (does marginal edge
  survive? → empirical scale-in schedule). Directly tests the deep-oversold depth-monotonicity.
- **Rolling re-entry:** model a persistent signal as roll-into-next-window re-struck off current price,
  vs enter/exit/sit-out. Distinct from *adding* (concentration/Kelly under ~0.9 correlation).
