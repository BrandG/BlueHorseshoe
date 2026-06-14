# ATR Regime P2

## Headline
Verdict: **percentile cell alpha, but not robust across ATR metric formulations**.
Plain call: do not advance this to P3 as a robust conditioner yet; the percentile alpha clears the baseline, but robustness fails outside the percentile formulation.

## Alpha vs Beta Baseline
All-bars baseline count sanity: baseline n=270,381 versus long_mr_strong4 long sleeve n=40,153.
Regime-gradient uplift: sleeve=+0.062 (NW_CI_low=+0.022, date-cluster_CI_low=+0.039) versus all-bars=+0.009 (NW_CI_low=-0.017).
Excess uplift (sleeve - baseline)=+0.053 (NW_CI_low=+0.005, date-cluster_CI_low=+0.032).
Low/mid absolute R: sleeve=+0.051 (NW_CI_low=+0.027) versus all-bars=+0.017 (NW_CI_low=+0.001).
Excess low/mid R (sleeve - baseline)=+0.034 (NW_CI_low=+0.005, date-cluster_CI_low=+0.021).

## Date-Clustered SE
Cluster unit is entry timestamp across pairs. The sleeve's own low/mid-high CI_low moves from NW +0.022 to date-cluster +0.039.

## Long/Short Confirmation
long_mr_strong4 short uplift=+0.018 (NW_CI_low=-0.023, date-cluster_CI_low=-0.005).

## ATR Metric Formulations
| formulation | uplift | nw_ci_low | cluster_ci_low | n | passes_nw | passes_cluster |
| --- | --- | --- | --- | --- | --- | --- |
| atr_percentile | 0.06238 | 0.02152 | 0.039 | 40153 | True | True |
| absolute_atr | -0.02377 | -0.06458 | -0.04713 | 40153 | False | False |
| atr_over_price | -0.03565 | -0.07616 | -0.05936 | 40153 | False | False |

## Dedup Sanity
| sleeve | direction | sum_cell_trades | deduped_trades | dedup_drop |
| --- | --- | --- | --- | --- |
| long_mr_strong4 | long | 50491 | 40153 | 10338 |
| long_mr_strong4 | short | 53147 | 42177 | 10970 |
| long_mr_full6 | long | 74152 | 51971 | 22181 |
| long_mr_full6 | short | 77556 | 54397 | 23159 |

## Light Generalization
Dislocation-family full-6 descriptive rows are included in the CSV. Limit-cell status: research/v2_executable_regate/seed/ledger_tp05.csv exists but has columns ['strategy', 'pair', 'direction', 'entry_mode', 'entry_ts', 'exit_ts', 'r']; no ATR bucket fields, so limit-cell regime gradient not computed.

## Artifacts
- `atr_regime_p2_baseline.csv`: sleeve, all-bars baseline, excess, robustness rows.
- `atr_regime_p2.out`: run summary.

---

## Audit note (Bubo, 2026-06-14)

The alpha-vs-beta verdict is **confirmed and strong**: the sleeve regime edge is ~6× the all-bars
baseline (which is n.s.), the excess survives the date-clustered SE (+0.032), so it is cell
selection alpha — not generic vol-beta. The `advance_to_p3=False` is a fair pause but its
"route away" implication is premature.

The reason: the "not robust across formulations" failure is **not** a comparability artifact — all
three formulations are bucketed per-pair (code lines ~230–231). The real distinction is **time-local
(rolling causal percentile, which works) vs time-global (per-pair full-sample level cuts, which
invert)**. So the edge is specifically "calm relative to this pair's *recent* normal," not "low vol
level." That is a coherent adaptive regime, and the rolling percentile is the PIT metric we'd
deploy. Two facts argue real-not-artifact: the gradient is absent in the all-bars baseline under the
*same* percentile metric; and vol clustering makes "recent-relative calm" a sensible predictor.

**Next is P2b, not P3 or relative-value:** corroborate with alternative *time-local* metrics
(`ATR/SMA(ATR,50)`, percentile at 60/500-bar windows). If they agree → real edge → P3. If only the
exact 252-bar rank shows it → construction artifact → relative-value.
