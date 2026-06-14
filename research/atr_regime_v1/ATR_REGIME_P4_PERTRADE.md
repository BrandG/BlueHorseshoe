# ATR Regime P4 — Per-Trade Re-cut (win rate + R, calm vs choppy)

Judges the volatility conditioner on the trades themselves — no +10% FTMO target, no challenge-pass race. Calm = low+mid ATR (the pair's vol in the bottom two-thirds of its own recent ~6 weeks, w252 percentile); choppy = high ATR (top third).

## long_mr_strong4
| regime | trades | win_rate | avg_R | median_R | worst_R | p05_R | total_R |
| --- | --- | --- | --- | --- | --- | --- | --- |
| calm (low+mid ATR) | 25673 | 52.6% | 0.051 | 0.255 | -1.00 | -1.00 | 1317.2 |
| choppy (high ATR) | 14480 | 49.2% | -0.011 | -0.115 | -1.00 | -1.00 | -160.4 |
| all | 40153 | 51.3% | 0.029 | 0.146 | -1.00 | -1.00 | 1156.8 |
| low | 13850 | 53.0% | 0.057 | 0.279 | -1.00 | -1.00 | 789.1 |
| mid | 11823 | 52.1% | 0.045 | 0.225 | -1.00 | -1.00 | 528.1 |
| high | 14480 | 49.2% | -0.011 | -0.115 | -1.00 | -1.00 | -160.4 |

Choppy trades are 36% of the book but account for 38% of total losing-trade R. Down-sizing or skipping them is the conditioner's mechanism.

## long_mr_full6
| regime | trades | win_rate | avg_R | median_R | worst_R | p05_R | total_R |
| --- | --- | --- | --- | --- | --- | --- | --- |
| calm (low+mid ATR) | 33725 | 52.5% | 0.052 | 0.256 | -1.00 | -1.00 | 1753.8 |
| choppy (high ATR) | 18246 | 49.6% | -0.001 | -0.044 | -1.00 | -1.00 | -9.2 |
| all | 51971 | 51.5% | 0.034 | 0.172 | -1.00 | -1.00 | 1744.6 |
| low | 18474 | 52.7% | 0.054 | 0.253 | -1.00 | -1.00 | 1003.0 |
| mid | 15251 | 52.3% | 0.049 | 0.259 | -1.00 | -1.00 | 750.8 |
| high | 18246 | 49.6% | -0.001 | -0.044 | -1.00 | -1.00 | -9.2 |

Choppy trades are 35% of the book but account for 37% of total losing-trade R. Down-sizing or skipping them is the conditioner's mechanism.

