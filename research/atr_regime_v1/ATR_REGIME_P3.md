# ATR Regime P3

## Headline
Deploy call: **deploy** the w252 ATR regime sizing schedule low=1.0, mid=1.0, high=0.5.
Best deployable trade-off on `long_mr_strong4` is `size_down_high_0_5`: total R +1237.028 vs unconditioned +1156.837, maxDD +521.424 vs +664.088 (DD reduction +142.664), return/DD +2.372 vs +1.742, throughput cost 0.0%.
Book-level alpha arbiter: the same conditioner on the all-bars random-long book has delta return/DD -0.012 and DD reduction +301.863. MR minus random alpha deltas are total R +432.029, return/DD +0.642, and DD reduction -159.199. Interpretation: **MR-specific return/return-DD alpha plus generic vol-beta DD control**.

## Primary Book Full-Period Metrics
| conditioner | total_R | expectancy_R | trades | throughput_cost_pct | maxDD_R | return_DD | delta_total_R | delta_maxDD_reduction_R | delta_return_DD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unconditioned | 1157 | 0.02881 | 40153 | 0.0% | 664.1 | 1.742 | 0 | 0 | 0 |
| hard_gate_skip_high | 1317 | 0.05131 | 25673 | 36.1% | 459 | 2.87 | 160.4 | 205.1 | 1.128 |
| size_down_high_0_5 | 1237 | 0.03081 | 40153 | 0.0% | 521.4 | 2.372 | 80.19 | 142.7 | 0.6304 |
| size_down_high_0_0 | 1317 | 0.05131 | 25673 | 36.1% | 459 | 2.87 | 160.4 | 205.1 | 1.128 |
| size_up_low_1_5 | 1551 | 0.03864 | 40153 | 0.0% | 794.4 | 1.953 | 394.5 | -130.3 | 0.211 |
| size_up_low_1_5_down_high_0_5 | 1632 | 0.04063 | 40153 | 0.0% | 678.8 | 2.404 | 474.7 | -14.67 | 0.6617 |

## Stability
| conditioner | half | total_R | trades | maxDD_R | return_DD | delta_total_R |
| --- | --- | --- | --- | --- | --- | --- |
| unconditioned | full | 1157 | 40153 | 664.1 | 1.742 | 0 |
| size_down_high_0_5 | full | 1237 | 40153 | 521.4 | 2.372 | 80.19 |
| unconditioned | h1 | 471.5 | 20076 | 664.1 | 0.7099 | 0 |
| size_down_high_0_5 | h1 | 531.6 | 20076 | 521.4 | 1.019 | 60.11 |
| unconditioned | h2 | 685.4 | 20077 | 354.8 | 1.932 | 0 |
| size_down_high_0_5 | h2 | 705.5 | 20077 | 261 | 2.703 | 20.08 |

## Alpha Arbiter
| conditioner | mr_delta_total_R | random_delta_total_R | cell_alpha_delta_R | mr_delta_return_DD | random_delta_return_DD | cell_alpha_delta_return_DD | mr_dd_reduction_R | random_dd_reduction_R | cell_alpha_dd_reduction_R | mr_throughput_cost_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hard_gate_skip_high | 160.4 | -703.7 | 864.1 | 1.128 | -0.05734 | 1.185 | 205.1 | 500.4 | -295.3 | 36.1% |
| size_down_high_0_5 | 80.19 | -351.8 | 432 | 0.6304 | -0.01188 | 0.6423 | 142.7 | 301.9 | -159.2 | 0.0% |
| size_down_high_0_0 | 160.4 | -703.7 | 864.1 | 1.128 | -0.05734 | 1.185 | 205.1 | 500.4 | -295.3 | 36.1% |
| size_up_low_1_5 | 394.5 | 910.8 | -516.2 | 0.211 | -0.05612 | 0.2671 | -130.3 | -1157 | 1027 | 0.0% |
| size_up_low_1_5_down_high_0_5 | 474.7 | 558.9 | -84.19 | 0.6617 | -0.06874 | 0.7305 | -14.67 | -855.5 | 840.9 | 0.0% |

## Full-6 Cross-Check
`long_mr_full6` under `size_down_high_0_5`: total R +1749.191, delta R +4.576, maxDD reduction +130.540, return/DD delta +0.405.

## Dedup And Method
| sleeve | direction | sum_cell_trades | deduped_trades | dedup_drop |
| --- | --- | --- | --- | --- |
| long_mr_strong4 | long | 51446 | 40887 | 10559 |
| long_mr_strong4 | short | 53890 | 42776 | 11114 |
| long_mr_full6 | long | 75479 | 52879 | 22600 |
| long_mr_full6 | short | 78604 | 55142 | 23462 |

Method: causal/PIT `atr_pct_w252` ATR(14) rolling percentile; buckets are low 0-33, mid 33-67, high 67-100. Long-MR trades use deployed mid-entry fires, 1%/1% R, MAX_HOLD=84, deduped one trade per `(pair, entry_bar)`. Random baseline is the all-bars long book over the same pairs and period. No sampling is used; numpy seed 20260614 is fixed for reproducibility if sampling is added later.

## Artifacts
- `atr_regime_p3_book.csv`: book metrics by sample, conditioner, and half.
- `atr_regime_p3.out`: run summary.

Production wiring is intentionally out of scope for P3.

---

## Audit note (Bubo, 2026-06-14)

Verdict confirmed — `size_down_high_0_5` is a legitimate deploy candidate (return/DD 1.74→2.37,
maxDD −21%, throughput-neutral, stable both halves), and the alpha arbiter is correctly read:
return/return-DD = MR cell-alpha (down-sizing hurts a random book, helps MR), DD reduction =
generic vol-beta. Both deployable.

Three things to carry into the FTMO-constrained sim (P4), not blockers but real:
1. **Return-alpha is strong-4-specific** — full-6 adds only +4.6 R, so on the broad book it's mostly
   DD control. Decide the deploy sleeve accordingly.
2. **R-space ≠ FTMO-space.** P3 ignores max-positions/daily-loss/slot redeployment. Down-sizing
   high-ATR frees slots a constrained book could reuse → the +R may be *understated*; and the hard
   max-DD / daily-loss limits must be checked directly.
3. **`size_down` vs `hard_gate`.** Hard-gate has the better risk numbers (return/DD 2.87, maxDD 459)
   at −36% throughput. For FTMO's pass/fail max-DD, evaluate both under the constrained sim before
   committing to the throughput-neutral form.

Production wiring (a w252 sizing multiplier in `bud/`) stays a separate, approval-gated task after
P4.
