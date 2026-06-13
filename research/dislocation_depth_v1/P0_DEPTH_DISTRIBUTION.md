# P0 Depth Distribution

## Method
Extracted fresh fires for 6 dislocation-family evaluators across 17 deployed pairs using `co_fire.DIR_MASKERS`, `deployed_cells()`, and modal deployed params from `choose_params()`.
Bars are closed H4 bars (`include_incomplete=False`). `entry_ATR` is ATR(14); `ATR_percentile` is the rolling 252-bar percentile rank. `ts` is the source H4 bar-open timestamp.
For RSI, stochastic, and CCI, the plan defines depth in oscillator units; `atr_norm_depth` therefore equals the oscillator-unit depth for P0 reporting.

## Parameter Choices
- bb: `{"depth": 0.0, "n_std": 2.0, "period": 50}`
- rsi: `{"period": 14, "recovery": 1, "threshold": 35}`
- cci: `{"period": 14, "recovery": 1, "threshold": 100}`
- sma: `{"atr_period": 14, "k": 2.5, "period": 200}`
- ema: `{"atr_period": 14, "k": 2.0, "period": 20}`
- stoch: `{"d_period": 3, "k_period": 9, "recovery": 1, "threshold": 20}`

## Count Sanity
- bb: long=5,518, short=5,571
- rsi: long=11,889, short=12,396
- cci: long=19,689, short=20,256
- sma: long=4,470, short=4,604
- ema: long=5,543, short=5,710
- stoch: long=28,714, short=30,547

## Depth Distribution

| evaluator | direction | n | raw q10 | raw q50 | raw q90 | atr q10 | atr q50 | atr q90 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| bb | long | 5,518 | 0.000159305 | 0.0014184 | 0.161088 | 0.0407078 | 0.282429 | 0.880888 |
| bb | short | 5,571 | 0.000190522 | 0.00163729 | 0.134668 | 0.0448184 | 0.282628 | 0.883161 |
| cci | long | 19,689 | 10.007 | 52.5551 | 137.982 | 10.007 | 52.5551 | 137.982 |
| cci | short | 20,256 | 9.99511 | 52.2886 | 134.183 | 9.99511 | 52.2886 | 134.183 |
| ema | long | 5,543 | 0.000153618 | 0.00130168 | 0.15282 | 0.0405541 | 0.243567 | 0.781429 |
| ema | short | 5,710 | 0.000150884 | 0.00153365 | 0.125399 | 0.0332082 | 0.231094 | 0.751319 |
| rsi | long | 11,889 | 0.812438 | 4.75604 | 12.6437 | 0.812438 | 4.75604 | 12.6437 |
| rsi | short | 12,396 | 0.82395 | 4.91295 | 13.0173 | 0.82395 | 4.91295 | 13.0173 |
| sma | long | 4,470 | 0.000145723 | 0.00124956 | 0.141694 | 0.0415961 | 0.268509 | 0.849909 |
| sma | short | 4,604 | 0.00016673 | 0.0014773 | 0.124614 | 0.0407035 | 0.262373 | 0.795028 |
| stoch | long | 28,714 | 3.22265 | 12.5457 | 18.5546 | 3.22265 | 12.5457 | 18.5546 |
| stoch | short | 30,547 | 3.43492 | 12.8968 | 18.6257 | 3.43492 | 12.8968 | 18.6257 |

## Volatility-Confound Diagnostic

| evaluator | n | corr(raw, ATR) | corr(ATR-norm, ATR) | per-pair raw range | per-pair ATR-norm range |
|---|---:|---:|---:|---:|---:|
| bb | 11,089 | 0.639 | 0.029 | [0.276, 0.547] | [0.011, 0.145] |
| cci | 39,945 | 0.008 | 0.008 | [0.003, 0.076] | [0.003, 0.076] |
| ema | 11,253 | 0.636 | 0.030 | [0.283, 0.547] | [0.016, 0.184] |
| rsi | 24,285 | 0.039 | 0.039 | [-0.019, 0.144] | [-0.019, 0.144] |
| sma | 9,074 | 0.654 | 0.019 | [0.313, 0.512] | [0.003, 0.193] |
| stoch | 59,261 | 0.015 | 0.015 | [-0.016, 0.043] | [-0.016, 0.043] |

## Verdict
For price-domain dislocations, ATR-normalization materially reduces the pooled depth/ATR linkage (mean |corr| 0.643 -> 0.026). P1 should lean on `atr_norm_depth` for those cells.
