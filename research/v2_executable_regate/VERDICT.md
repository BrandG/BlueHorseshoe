# Executable-Ledger Re-Gate Verdict

Date: 2026-06-13

## Harness and Regression Gate

Restored the archived v2 limit harness into `research/v2_executable_regate/harness/` for ATR, MACD, and Ichimoku limit cells.

Regression result before the executable-fill change:

- `atr_limit`: seed horizon matched row-for-row on `pair`, `entry_ts`, `exit_ts`, `r`.
- `macd_limit`: seed horizon matched row-for-row on `pair`, `entry_ts`, `exit_ts`, `r`.
- `ichimoku_limit`: seed horizon matched row-for-row on `pair`, `entry_ts`, `exit_ts`, `r`.

The current FxStore extends beyond the seed ledger horizon, so the regression comparison caps each generated ledger at the seed ledger's max `entry_ts`. Pre-horizon rows are exact.

Implementation note: the archived portfolio ledgers are produced by the harness' spread-aware collection path, whose archived limit level is the signal bar's bid-low for longs and ask-high for shorts. To keep the reproduced ledger as the valid baseline, the executable change preserves that archived limit level and changes only the fill-window predicate:

- long fills require fill-bar `low_ask <= limit`
- short fills require fill-bar `high_bid >= limit`
- entry remains the limit price
- exit accounting remains byte-identical to the archived spread path
- code asserts executable fills are a strict subset of archived baseline fills

## Survival

Mid-touch/archive limit trades: 4,092

Executable limit trades: 2,870

Survival: 70.14%

Drop: 29.86%

By strategy:

| Strategy | Mid n | Executable n | Drop | Mid mean R | Exec mean R | Exec NW-lo |
|---|---:|---:|---:|---:|---:|---:|
| ATR | 2,746 | 1,914 | 30.30% | +0.133 | +0.057 | -0.000 |
| MACD | 1,179 | 840 | 28.75% | +0.214 | +0.177 | +0.106 |
| Ichimoku | 167 | 116 | 30.54% | +0.192 | +0.199 | +0.037 |
| Limit sleeve | 4,092 | 2,870 | 29.86% | +0.159 | +0.098 | +0.053 |

## Bias Direction

The phantom-fill bias was material and optimistic.

The executable limit sleeve mean R falls from +0.159 to +0.098, and full-pool NW-lo falls from +0.116 to +0.053. On the live-replicable one-position-per-pair pool, limit-sleeve NW-lo falls from +0.093 to +0.028.

That supports the shallow-touch hypothesis: the removed fills were, on balance, better than the fills that survive executable bid/ask extremes.

## Combined Book

The combined book still clears Newey-West at portfolio level, but with a smaller margin.

| Portfolio | Rule | Pool | n | Mean R | NW-lo |
|---|---|---|---:|---:|---:|
| Combined | mid-touch/archive | full pool | 22,183 | +0.119 | +0.081 |
| Combined | executable limits | full pool | 20,961 | +0.108 | +0.069 |
| Combined | mid-touch/archive | live-replicable | 4,617 | +0.094 | +0.060 |
| Combined | executable limits | live-replicable | 4,272 | +0.065 | +0.031 |

Against the reference combined live-replicable NW-lo of about +0.058, the executable combined book remains positive at +0.031, but roughly halves the evidence margin.

## Recommendation

Do not change live trader behavior in this task.

Re-rank the evidence base:

- MACD limit remains the strongest limit sleeve after executable fills.
- ATR limit collapses to approximately zero at strategy level and all three ATR limit cells have negative full-sample NW-lo after executable filtering.
- Ichimoku remains positive on full sample but is small and thin; its test-half NW-lo is negative after executable filtering.
- The combined book still clears portfolio-level NW, but the limit sleeve should no longer be treated as the strongest defensible core. The mid-entry sleeve now carries more of the book-level case.

Primary outputs:

- `results/midtouch_vs_executable_limit.csv`
- `results/per_cell_limit_nw.csv`
- `results/portfolio_nw.csv`
- `results/ledgers_horizon/`
