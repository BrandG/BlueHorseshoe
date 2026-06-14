# ATR Regime P2b

## Headline
Verdict: **corroborated: the edge is recent-relative calm, not a 252-rank artifact**.
Plain call: alternative time-local metrics corroborate the low>high sleeve gradient and positive alpha-vs-beta excess; advance to P3 for book-level sizing/throughput/DD.

## Metric Robustness
Corroboration rule: at least 2 of 3 alternative time-local metrics must have NW-positive sleeve low/mid-high uplift and positive sleeve-vs-baseline excess. Observed alt hits: 2/3.
| metric | uplift | NW_CI_low | cluster_CI_low | excess_vs_baseline | excess_NW_CI_low | excess_cluster_CI_low | pair | n | corroborates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| atr_pct_w252 | 0.06238 | 0.02152 | 0.039 | 0.0533 | 0.004633 | 0.03207 | 12/17 | 40153 | True |
| atr_ma_ratio | 0.03063 | -0.008791 | 0.008167 | 0.01114 | -0.03583 | -0.009321 | 14/17 | 40051 | False |
| atr_pct_w60 | 0.04086 | 0.001771 | 0.01828 | 0.01619 | -0.03032 | -0.00429 | 10/17 | 40707 | True |
| atr_pct_w500 | 0.04636 | 0.0048 | 0.02251 | 0.04408 | -0.005508 | 0.02231 | 11/17 | 39511 | True |

## PIT Check
All metrics are recomputed from `FxStore(read_only=True)` complete H4 midpoint bars.
`ATR(14)` uses closed bars at the entry timestamp. Each percentile is `rolling(window, min_periods=window).apply(rank_last)`, where `rank_last` ranks `arr[-1]` inside the backward-looking window. There is no negative shift or forward window.
`atr_ma_ratio` uses `ATR(14) / SMA(ATR(14), 50)` and is bucketed by a rolling 252-bar percentile of that ratio. This keeps the ratio metric time-local while avoiding fixed cross-period level thresholds.

## Metric Definitions
- `atr_pct_w252`: ATR(14) rolling 252-bar percentile, recomputed from closed H4 midpoint bars.
- `atr_ma_ratio`: ATR(14) / SMA(ATR(14),50), bucketed by rolling 252-bar percentile of that ratio.
- `atr_pct_w60`: ATR(14) rolling 60-bar percentile, recomputed from closed H4 midpoint bars.
- `atr_pct_w500`: ATR(14) rolling 500-bar percentile, recomputed from closed H4 midpoint bars.

## Dedup Sanity
long_mr_strong4 long: sum_cell_trades=51,446, deduped_trades=40,887, dedup_drop=10,559.

## Artifacts
- `atr_regime_p2b_metrics.csv`: per-metric bucket, uplift, excess, and per-pair rows.
- `atr_regime_p2b.out`: run summary.

---

## Audit note (Bubo, 2026-06-14)

The "corroborated → P3" headline conflates two questions; separating them:

- **Gradient (low>high uplift): robust.** NW-positive at w252/w60/w500 (3/4; only the ATR/MA ratio
  is weak). So the edge is NOT a 252-rank construction artifact — this resolves P2's open worry. ✓
- **Alpha (excess vs baseline): metric-sensitive.** Significant only on w252 (NW + cluster);
  cluster-only on w500; NOT significant on w60 or the ratio. Codex's corroboration rule counted a
  *positive point estimate* of excess as a hit — but by the significance bar (the meaningful one,
  from P2), the alpha is fragile. At the short w60 window the all-bars baseline itself gains a
  gradient, so the excess shrinks = more vol-beta at short horizons.

**Net:** advance to P3 (the gradient robustness clears the kill condition), but NOT as the clean
"pure alpha" the headline implies. Deploy on the causal/PIT **w252** percentile; treat as a
vol-regime risk/sizing lever with a real-but-metric-sensitive alpha; P3's **book-level baseline**
(conditioned vs unconditioned vs random-entry, in $/throughput/DD) is the deployable-value arbiter.
For FTMO, max-DD reduction is itself deployable even if expectancy uplift is modest.

*(This run was executed by Bubo directly: Codex parked ~2.5h on the blackout note, but today is
Sunday and the heavy pipeline is Tue–Sat-only, so nothing was running. Script lint 10/10.)*
