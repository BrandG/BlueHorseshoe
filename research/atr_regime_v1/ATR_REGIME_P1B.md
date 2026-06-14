# ATR Regime P1b

## Method
Simulated `depth_fires.csv` with `_lib.py` mid-entry R machinery, TP=1%, SL=1%, and `MAX_HOLD=84` H4 bars.
Realized hold is `exit_idx - entry_idx`. The corrected primary Newey-West lag is `L = round(pooled median realized hold) - 1 = 22`. Sensitivity lags are `[22, 31, 83]`; mean-derived L is 31 and `MAX_HOLD - 1` is 83.
Sleeves are book-level deduped at one trade per `(pair, entry_bar, direction)`. The primary gate is the strong-4 long sleeve full-sample NW-positive low/mid-minus-high uplift, direction positive in both halves, per-pair majority, and absolute low/mid +R.

## Headline
Strong-4 long sleeve at corrected L=22: low/mid=+0.051 (NW_CI_low=+0.027), low/mid-high=+0.062 (NW_CI_low=+0.022), both-halves direction=YES, per-pair majority=12/17.
Full-6 long sleeve at corrected L=22: low/mid=+0.052 (NW_CI_low=+0.031), low/mid-high=+0.053 (NW_CI_low=+0.016), both-halves direction=YES, per-pair majority=12/17.
Strong-4 half-level NW detail: h1 uplift=+0.062 (NW_CI_low=+0.003, NW-positive=YES); h2 uplift=+0.063 (NW_CI_low=+0.007, NW-positive=YES).
Absolute tradeability at corrected L: strong-4 low/mid +R=YES; full-6 low/mid +R=YES.
Verdict: the long-MR sleeve holds at book level with corrected L; advance to P2 for alpha-vs-beta regime baseline.
Plain call: if this sleeve holds, P2 is warranted; if it dies here with corrected L, there is no volatility-regime conditioner to deploy from P1.

## Realized Hold
Pooled all trades n=151708, median=23.00, mean=32.16, q10=6.00, q25=11.00, q75=47.00, q90=84.00.

## Dedup Sanity
| sleeve | direction | sum_cell_trades | deduped_trades | dedup_drop |
| --- | --- | --- | --- | --- |
| long_mr_strong4 | long | 50491 | 40153 | 10338 |
| long_mr_strong4 | short | 53147 | 42177 | 10970 |
| long_mr_full6 | long | 74152 | 51971 | 22181 |
| long_mr_full6 | short | 77556 | 54397 | 23159 |

## Per-Cell Corrected-L Recheck
Corrected L does not uniformly strengthen the four long cells versus L=83; the book-level sleeve is the primary P1b gate.
- bb long: corrected diff CI_low=+0.009 vs P1 L83=+0.007; corrected low/mid CI_low=+0.031 vs P1 L83=+0.032; strengthened=NO.
- ema long: corrected diff CI_low=+0.023 vs P1 L83=+0.025; corrected low/mid CI_low=+0.021 vs P1 L83=+0.021; strengthened=NO.
- rsi long: corrected diff CI_low=+0.028 vs P1 L83=+0.029; corrected low/mid CI_low=+0.031 vs P1 L83=+0.031; strengthened=NO.
- stoch long: corrected diff CI_low=+0.009 vs P1 L83=+0.009; corrected low/mid CI_low=+0.018 vs P1 L83=+0.018; strengthened=YES.

## L Sensitivity
| sleeve | direction | L | full_low_mid_mean | full_low_mid_nw_ci_low | full_uplift | full_uplift_nw_ci_low | both_halves_direction_positive | full_pair_positive | full_pair_total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| long_mr_full6 | long | 22 | 0.052 | 0.03079 | 0.0525 | 0.01591 | True | 12 | 17 |
| long_mr_full6 | long | 31 | 0.052 | 0.02879 | 0.0525 | 0.01284 | True | 12 | 17 |
| long_mr_full6 | long | 83 | 0.052 | 0.02298 | 0.0525 | 0.004649 | True | 12 | 17 |
| long_mr_strong4 | long | 22 | 0.05131 | 0.0274 | 0.06238 | 0.02152 | True | 12 | 17 |
| long_mr_strong4 | long | 31 | 0.05131 | 0.02529 | 0.06238 | 0.01842 | True | 12 | 17 |
| long_mr_strong4 | long | 83 | 0.05131 | 0.01965 | 0.06238 | 0.01043 | True | 12 | 17 |

## Short Sleeve Completeness
- long_mr_full6 short: low/mid=+0.006 (NW_CI_low=-0.015), low/mid-high=+0.012 (NW_CI_low=-0.025), both-halves direction=YES, pairs=9/17.
- long_mr_strong4 short: low/mid=+0.008 (NW_CI_low=-0.015), low/mid-high=+0.018 (NW_CI_low=-0.023), both-halves direction=YES, pairs=11/17.

## Artifacts
- `atr_regime_sleeve_curves.csv`: sleeve curves plus realized-hold rows.
- `atr_regime_p1b.out`: run summary.

---

## Audit note (Bubo, 2026-06-13)

Verdict confirmed: the sleeve clears the book-level P1b gate, and robustly — it survives at L=22,
31, AND 83, so the result is the book-level pooling (v2 NW lesson), not a favorable lag pick. Both
my P1 critiques (over-strict per-half gate; over-large L) were valid; pooling is the bigger factor.
**But "survives rigor" ≠ "validated edge."** The decisive open question is P2's
**alpha-vs-beta-regime baseline** — is low-ATR-good specific to these MR cells, or generic to any
forex long? Until that's answered, treat this as a strong lead, not a deployable conditioner. Also
fold a date-clustered / cross-pair-aware SE into P2 (the pooled time-series NW is optimistic about
the 17 pairs' contemporaneous correlation).
