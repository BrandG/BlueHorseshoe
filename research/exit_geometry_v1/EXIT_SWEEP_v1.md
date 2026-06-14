# Exit Sweep v1 — best exit setup by total money (individual trades)

## Headline
`long_mr_strong4`: best total-money setup is **TP 1.5% / SL 0.6% / 10-day hold** at **+1308R** vs the fixed 1:1/14d baseline +1157R (+13%); profitable in all three eras.
`long_mr_full6`: best total-money setup is **TP 1.5% / SL 0.6% / 10-day hold** at **+2085R** vs the fixed 1:1/14d baseline +1745R (+20%); profitable in all three eras.

## What this measures (and what it does NOT)
Each setup is scored on the trades themselves, ranked by **total money** (sum of per-trade R at constant per-trade risk, so total R is proportional to total dollars). Every trade is included. There is **no account drawdown, no concurrent-position cap, no calm/choppy filter** — a single trade cannot produce a portfolio drawdown, and regime is a property of the market at entry, not of the trade. The A/B interleaved-quarter split + last-24-month holdout (from `2024-06-12`) is only a robustness check: a setup must make money in all three eras to be reported, so the winner is not a one-period fluke. (Account-level FTMO limits are a separate question, not how a per-trade setup is chosen.)
Faithfulness: `154,083` real fires reproduce `_lib.py` exactly at TP=SL=1%/14d, so the baseline below IS the campaign's book. Sample period `2016-01-05..2026-06-12`, 120 setups swept.

## long_mr_strong4 — top 10 by total money (all eras positive)
| TP | SL | hold(d) | A | B | holdout | TOTAL | win | trades |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1.5% | 0.6% | 10 | +228 | +719 | +361 | +1308 | 34.7% | 40153 |
| 2.0% | 1.0% | 10 | +40 | +878 | +340 | +1259 | 43.6% | 40153 |
| 1.5% | 1.0% | 10 | +191 | +725 | +332 | +1248 | 45.6% | 40153 |
| 1.5% | 0.8% | 10 | +113 | +739 | +365 | +1217 | 41.1% | 40153 |
| 1.0% | 1.0% | 14 | +244 | +484 | +429 | +1157 | 51.3% | 40153 |
| 1.5% | 1.0% | 14 | +143 | +632 | +376 | +1151 | 44.0% | 40153 |
| 1.0% | 1.0% | 10 | +214 | +555 | +367 | +1136 | 51.3% | 40153 |
| 1.5% | 0.6% | 6 | +120 | +629 | +383 | +1132 | 38.3% | 40153 |
| 1.0% | 1.5% | 14 | +169 | +562 | +397 | +1128 | 58.7% | 40153 |
| 1.5% | 1.0% | 20 | +196 | +574 | +355 | +1125 | 42.6% | 40074 |

Current 1:1/14d baseline for reference:
| TP | SL | hold(d) | A | B | holdout | TOTAL | win | trades |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1.0% | 1.0% | 14 | +244 | +484 | +429 | +1157 | 51.3% | 40153 |

## long_mr_full6 — top 10 by total money (all eras positive)
| TP | SL | hold(d) | A | B | holdout | TOTAL | win | trades |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1.5% | 0.6% | 10 | +529 | +948 | +608 | +2085 | 34.9% | 51971 |
| 2.0% | 0.6% | 10 | +222 | +1306 | +544 | +2072 | 32.9% | 51971 |
| 1.5% | 1.0% | 20 | +472 | +899 | +578 | +1948 | 43.0% | 51864 |
| 1.5% | 0.8% | 10 | +361 | +1014 | +573 | +1947 | 41.3% | 51971 |
| 2.0% | 1.0% | 10 | +221 | +1203 | +519 | +1943 | 43.8% | 51971 |
| 1.5% | 1.0% | 10 | +434 | +983 | +525 | +1942 | 45.8% | 51971 |
| 2.0% | 1.0% | 20 | +201 | +1227 | +499 | +1927 | 39.0% | 51864 |
| 1.5% | 0.6% | 14 | +538 | +785 | +590 | +1914 | 32.7% | 51971 |
| 1.5% | 1.0% | 14 | +384 | +939 | +589 | +1912 | 44.3% | 51971 |
| 2.0% | 0.8% | 10 | +105 | +1268 | +514 | +1887 | 39.2% | 51971 |

Current 1:1/14d baseline for reference:
| TP | SL | hold(d) | A | B | holdout | TOTAL | win | trades |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1.0% | 1.0% | 14 | +445 | +730 | +571 | +1745 | 51.5% | 51971 |

## Read
The consistent pattern across both books: **shorter hold (10 days, not 14) and a target wider than the stop** (let winners run, cut losers faster). The single best total-money setup uses a tight 0.6% stop, but it is the best of 120 swept — trust the *direction* (shorter hold, wider target than stop) more than the exact 0.6%. A steadier alternative on the focused book is TP 1.5% / SL 1.0% / 10-day (more even across eras).

