# P1 Depth R

## Method
Simulated P0 fires with `_lib.py` mid/limit simulators at TP=1%, SL=1%, and fixed `MAX_HOLD=84` H4 bars. `MAX_HOLD` is imported from the v2 harness and matches `research/confluence_v1/p1a_sweep.py`.
Depth metric: `atr_norm_depth` for price-domain cells (bb/ema/sma), raw oscillator-unit depth for rsi/cci/stoch. All six deployed dislocation cells use mean-reversion `mid` entry mode.
Fixed buckets are evaluator-specific: price-domain ATR units [0,0.10,0.25,0.50,1.00,inf), RSI [0,2.5,5,10,15,inf), CCI [0,25,50,100,150,inf), stoch [0,5,10,15,20,inf).

## Deployed Cells
- bb: entry_mode=mid, params=`{"depth": 0.0, "n_std": 2.0, "period": 50}`
- rsi: entry_mode=mid, params=`{"period": 14, "recovery": 1, "threshold": 35}`
- cci: entry_mode=mid, params=`{"period": 14, "recovery": 1, "threshold": 100}`
- sma: entry_mode=mid, params=`{"atr_period": 14, "k": 2.5, "period": 200}`
- ema: entry_mode=mid, params=`{"atr_period": 14, "k": 2.0, "period": 20}`
- stoch: entry_mode=mid, params=`{"d_period": 3, "k_period": 9, "recovery": 1, "threshold": 20}`

## Fire Count / Drop Sanity
| evaluator | direction | fires | realized | dropped | sim_dropped |
| --- | --- | --- | --- | --- | --- |
| bb | long | 5518 | 5500 | 18 | 18 |
| bb | short | 5571 | 5533 | 38 | 38 |
| rsi | long | 11889 | 11843 | 46 | 46 |
| rsi | short | 12396 | 12314 | 82 | 82 |
| cci | long | 19689 | 19604 | 85 | 85 |
| cci | short | 20256 | 20144 | 112 | 112 |
| sma | long | 4470 | 4429 | 41 | 41 |
| sma | short | 4604 | 4570 | 34 | 34 |
| ema | long | 5543 | 5524 | 19 | 19 |
| ema | short | 5710 | 5683 | 27 | 27 |
| stoch | long | 28714 | 28579 | 135 | 135 |
| stoch | short | 30547 | 30360 | 187 | 187 |

## Kill-Or-Advance Verdict
- bb long: baseline=+0.045, Q1=+0.016, Q5=+0.025 (CI_low=-0.032), Q5-baseline=-0.020, Q5-Q1=+0.009, Spearman=+0.000, slope=-0.02587. Monotone=NO; deepest clears=NO; ATR strata positive in 3/4 comparable buckets.
- bb short: baseline=+0.040, Q1=+0.004, Q5=+0.042 (CI_low=-0.015), Q5-baseline=+0.002, Q5-Q1=+0.038, Spearman=+0.300, slope=-0.02906. Monotone=YES; deepest clears=NO; ATR strata positive in 3/4 comparable buckets.
- cci long: baseline=+0.028, Q1=+0.026, Q5=+0.023 (CI_low=-0.007), Q5-baseline=-0.005, Q5-Q1=-0.003, Spearman=+0.100, slope=-0.00003. Monotone=NO; deepest clears=NO; ATR strata positive in 3/4 comparable buckets.
- cci short: baseline=-0.000, Q1=-0.000, Q5=+0.013 (CI_low=-0.016), Q5-baseline=+0.013, Q5-Q1=+0.013, Spearman=+0.200, slope=+0.00009. Monotone=YES; deepest clears=NO; ATR strata positive in 3/4 comparable buckets.
- ema long: baseline=+0.027, Q1=+0.046, Q5=+0.016 (CI_low=-0.041), Q5-baseline=-0.011, Q5-Q1=-0.030, Spearman=-0.900, slope=-0.05299. Monotone=NO; deepest clears=NO; ATR strata positive in 1/4 comparable buckets.
- ema short: baseline=+0.041, Q1=+0.056, Q5=+0.051 (CI_low=-0.005), Q5-baseline=+0.010, Q5-Q1=-0.004, Spearman=-0.100, slope=-0.01280. Monotone=NO; deepest clears=NO; ATR strata positive in 2/4 comparable buckets.
- rsi long: baseline=+0.031, Q1=+0.022, Q5=+0.050 (CI_low=+0.011), Q5-baseline=+0.019, Q5-Q1=+0.028, Spearman=-0.200, slope=+0.00041. Monotone=NO; deepest clears=YES; ATR strata positive in 3/4 comparable buckets.
- rsi short: baseline=+0.011, Q1=-0.009, Q5=-0.008 (CI_low=-0.046), Q5-baseline=-0.019, Q5-Q1=+0.001, Spearman=+0.600, slope=+0.00071. Monotone=YES; deepest clears=NO; ATR strata positive in 3/4 comparable buckets.
- sma long: baseline=+0.037, Q1=+0.050, Q5=+0.062 (CI_low=-0.002), Q5-baseline=+0.025, Q5-Q1=+0.012, Spearman=+0.400, slope=+0.01277. Monotone=YES; deepest clears=NO; ATR strata positive in 3/4 comparable buckets.
- sma short: baseline=+0.011, Q1=-0.001, Q5=+0.051 (CI_low=-0.011), Q5-baseline=+0.041, Q5-Q1=+0.053, Spearman=+0.600, slope=+0.06058. Monotone=YES; deepest clears=NO; ATR strata positive in 4/4 comparable buckets.
- stoch long: baseline=+0.026, Q1=+0.009, Q5=+0.018 (CI_low=-0.007), Q5-baseline=-0.009, Q5-Q1=+0.008, Spearman=+0.100, slope=+0.00041. Monotone=YES; deepest clears=NO; ATR strata positive in 2/4 comparable buckets.
- stoch short: baseline=-0.006, Q1=-0.033, Q5=+0.010 (CI_low=-0.014), Q5-baseline=+0.016, Q5-Q1=+0.043, Spearman=+0.700, slope=+0.00207. Monotone=YES; deepest clears=NO; ATR strata positive in 4/4 comparable buckets.

## P2 Candidate Set
- None. No cell-direction passes both monotonicity and deepest-bucket positive-lift gates; route to relative-value / door #2 per the design doc.

## ATR-Percentile Sanity
| evaluator | direction | atr_bucket | n | mean_R_by_ATR | CI_low |
| --- | --- | --- | --- | --- | --- |
| bb | long | ATR_high_67_100 | 2198 | -0.0006316 | -0.04098 |
| bb | long | ATR_low_0_33 | 1575 | 0.09765 | 0.05145 |
| bb | long | ATR_mid_33_67 | 1635 | 0.0596 | 0.01355 |
| bb | long | ATR_missing | 92 | -0.04348 | -0.2487 |
| bb | short | ATR_high_67_100 | 1978 | 0.02782 | -0.01458 |
| bb | short | ATR_low_0_33 | 1880 | 0.03288 | -0.0104 |
| bb | short | ATR_mid_33_67 | 1616 | 0.05426 | 0.007467 |
| bb | short | ATR_missing | 59 | 0.2542 | 0.005333 |
| cci | long | ATR_high_67_100 | 6619 | 0.01423 | -0.00891 |
| cci | long | ATR_low_0_33 | 7027 | 0.03276 | 0.01071 |
| cci | long | ATR_mid_33_67 | 5617 | 0.04101 | 0.01607 |
| cci | long | ATR_missing | 341 | -0.03011 | -0.1362 |
| cci | short | ATR_high_67_100 | 6284 | -0.007442 | -0.0312 |
| cci | short | ATR_low_0_33 | 7672 | 0.006591 | -0.01466 |
| cci | short | ATR_mid_33_67 | 5902 | -0.006 | -0.03039 |
| cci | short | ATR_missing | 286 | 0.08607 | -0.02891 |
| ema | long | ATR_high_67_100 | 2333 | -0.02036 | -0.05951 |
| ema | long | ATR_low_0_33 | 1463 | 0.04856 | 3.128e-05 |
| ema | long | ATR_mid_33_67 | 1628 | 0.08051 | 0.03422 |
| ema | long | ATR_missing | 100 | -0.04 | -0.2368 |
| ema | short | ATR_high_67_100 | 2141 | 0.03883 | -0.002068 |
| ema | short | ATR_low_0_33 | 1773 | 0.04242 | -0.00217 |
| ema | short | ATR_mid_33_67 | 1699 | 0.04197 | -0.003682 |
| ema | short | ATR_missing | 70 | 0.05714 | -0.1784 |
| rsi | long | ATR_high_67_100 | 4562 | -0.01683 | -0.04484 |
| rsi | long | ATR_low_0_33 | 3688 | 0.072 | 0.04172 |
| rsi | long | ATR_mid_33_67 | 3326 | 0.06579 | 0.03356 |
| rsi | long | ATR_missing | 267 | -0.1552 | -0.2737 |
| rsi | short | ATR_high_67_100 | 4187 | -0.003892 | -0.03288 |
| rsi | short | ATR_low_0_33 | 4425 | 0.04009 | 0.01189 |
| rsi | short | ATR_mid_33_67 | 3537 | -0.006782 | -0.03833 |
| rsi | short | ATR_missing | 165 | -0.006939 | -0.1587 |
| sma | long | ATR_high_67_100 | 1510 | 0.0222 | -0.02637 |
| sma | long | ATR_low_0_33 | 1615 | 0.04462 | -0.0009027 |
| sma | long | ATR_mid_33_67 | 1273 | 0.04356 | -0.00918 |
| sma | long | ATR_missing | 31 | 0.03226 | -0.3254 |
| sma | short | ATR_high_67_100 | 1503 | 0.05581 | 0.007633 |
| sma | short | ATR_low_0_33 | 1727 | -0.005242 | -0.05041 |
| sma | short | ATR_mid_33_67 | 1321 | -0.02101 | -0.07266 |
| sma | short | ATR_missing | 19 | 0.05263 | -0.4087 |
| stoch | long | ATR_high_67_100 | 9515 | -0.004415 | -0.02367 |
| stoch | long | ATR_low_0_33 | 10286 | 0.05565 | 0.03742 |
| stoch | long | ATR_mid_33_67 | 8282 | 0.03199 | 0.01148 |
| stoch | long | ATR_missing | 496 | -0.08618 | -0.1737 |
| stoch | short | ATR_high_67_100 | 9609 | -0.01986 | -0.03905 |
| stoch | short | ATR_low_0_33 | 11612 | 0.005211 | -0.01205 |
| stoch | short | ATR_mid_33_67 | 8690 | -0.01187 | -0.032 |
| stoch | short | ATR_missing | 449 | 0.1422 | 0.05104 |

## Depth x ATR Mean R

### bb long
| atr_bucket | Q1_shallow | Q2 | Q3 | Q4 | Q5_deep |
| --- | --- | --- | --- | --- | --- |
| ATR_missing | -0.3333 | 0.1579 | 0.09091 | -0.2 | 0 |
| ATR_low_0_33 | 0.06375 | 0.151 | 0.09456 | 0.08001 | 0.0953 |
| ATR_mid_33_67 | 0.09292 | 0.09714 | 0.01886 | 0.02852 | 0.0597 |
| ATR_high_67_100 | -0.07837 | 0.06735 | 0.01124 | 0.02556 | -0.02156 |

### bb short
| atr_bucket | Q1_shallow | Q2 | Q3 | Q4 | Q5_deep |
| --- | --- | --- | --- | --- | --- |
| ATR_missing | 0.4286 | 0 | 0.2727 | 0 | 0.375 |
| ATR_low_0_33 | 0.01998 | 0.08583 | 0.02324 | -0.01693 | 0.05409 |
| ATR_mid_33_67 | -0.02417 | 0.1043 | 0.02476 | 0.1011 | 0.06307 |
| ATR_high_67_100 | -0.005054 | 0.06159 | 0.01585 | 0.05824 | 0.0098 |

### cci long
| atr_bucket | Q1_shallow | Q2 | Q3 | Q4 | Q5_deep |
| --- | --- | --- | --- | --- | --- |
| ATR_missing | -0.06584 | -0.01754 | 0.04225 | -0.05263 | -0.05263 |
| ATR_low_0_33 | 0.05479 | 0.002552 | 0.02723 | 0.02484 | 0.05765 |
| ATR_mid_33_67 | -0.005268 | 0.05298 | 0.06951 | 0.04689 | 0.04152 |
| ATR_high_67_100 | 0.02495 | 0.00934 | 0.03715 | 0.02092 | -0.0178 |

### cci short
| atr_bucket | Q1_shallow | Q2 | Q3 | Q4 | Q5_deep |
| --- | --- | --- | --- | --- | --- |
| ATR_missing | 0.2 | -0.07727 | 0.1034 | 0.0436 | 0.2128 |
| ATR_low_0_33 | 0.02315 | 0.01755 | 0.0115 | -0.00553 | -0.01694 |
| ATR_mid_33_67 | -0.02649 | -0.01125 | 0.001332 | -0.002395 | 0.009467 |
| ATR_high_67_100 | -0.01393 | -0.001808 | -0.05081 | -0.01625 | 0.03881 |

### ema long
| atr_bucket | Q1_shallow | Q2 | Q3 | Q4 | Q5_deep |
| --- | --- | --- | --- | --- | --- |
| ATR_missing | 0 | -0.3043 | 0 | 0.1429 | -0.06667 |
| ATR_low_0_33 | 0.1173 | 0.08447 | 0.004022 | -0.008393 | 0.0332 |
| ATR_mid_33_67 | 0.009831 | 0.07166 | 0.131 | 0.1128 | 0.08001 |
| ATR_high_67_100 | 0.01869 | -0.01703 | -0.02234 | -0.05448 | -0.02172 |

### ema short
| atr_bucket | Q1_shallow | Q2 | Q3 | Q4 | Q5_deep |
| --- | --- | --- | --- | --- | --- |
| ATR_missing | 0.1 | 0 | -0.2 | -0.05263 | 0.3333 |
| ATR_low_0_33 | 0.1298 | 0.001643 | 0.02645 | -0.01119 | 0.06498 |
| ATR_mid_33_67 | 0.04266 | 0.06558 | 0.004925 | 0.0789 | 0.01588 |
| ATR_high_67_100 | -0.008801 | 0.0702 | -0.01259 | 0.08066 | 0.05777 |

### rsi long
| atr_bucket | Q1_shallow | Q2 | Q3 | Q4 | Q5_deep |
| --- | --- | --- | --- | --- | --- |
| ATR_missing | -0.2 | -0.04 | -0.1818 | -0.06122 | -0.2432 |
| ATR_low_0_33 | 0.03016 | 0.121 | 0.0677 | 0.05891 | 0.08562 |
| ATR_mid_33_67 | 0.0818 | 0.07517 | 0.01682 | 0.03116 | 0.1331 |
| ATR_high_67_100 | -0.02918 | -0.01562 | -0.0143 | -0.04732 | 0.01308 |

### rsi short
| atr_bucket | Q1_shallow | Q2 | Q3 | Q4 | Q5_deep |
| --- | --- | --- | --- | --- | --- |
| ATR_missing | -0.2973 | 0.04288 | 0.3103 | 0.08571 | -0.1452 |
| ATR_low_0_33 | 0.06024 | -0.006927 | -0.01696 | 0.1635 | 0.0003492 |
| ATR_mid_33_67 | -0.02745 | -0.04867 | 0.02782 | -0.01249 | 0.03042 |
| ATR_high_67_100 | -0.06471 | 0.01722 | 0.03045 | 0.04016 | -0.03538 |

### sma long
| atr_bucket | Q1_shallow | Q2 | Q3 | Q4 | Q5_deep |
| --- | --- | --- | --- | --- | --- |
| ATR_missing | -0.3333 | -0.2 | 0.1429 | 0 | 0.2 |
| ATR_low_0_33 | 0.09515 | -0.02341 | -0.001215 | 0.06694 | 0.1008 |
| ATR_mid_33_67 | 0.01264 | -0.03138 | -0.005362 | 0.09809 | 0.1402 |
| ATR_high_67_100 | 0.02506 | 0.04085 | 0.09417 | -0.01387 | -0.01944 |

### sma short
| atr_bucket | Q1_shallow | Q2 | Q3 | Q4 | Q5_deep |
| --- | --- | --- | --- | --- | --- |
| ATR_missing | -0.5 | -1 | -0.3333 | 0 | 1 |
| ATR_low_0_33 | -0.01918 | -0.008716 | -0.042 | 0.00542 | 0.05367 |
| ATR_mid_33_67 | -0.07696 | 0.001067 | 0.01679 | 0.009791 | -0.05511 |
| ATR_high_67_100 | 0.1056 | 0.00755 | 0.01747 | 0.02166 | 0.1128 |

### stoch long
| atr_bucket | Q1_shallow | Q2 | Q3 | Q4 | Q5_deep |
| --- | --- | --- | --- | --- | --- |
| ATR_missing | -0.1414 | -0.07527 | -0.03529 | -0.1083 | -0.05954 |
| ATR_low_0_33 | 0.04838 | 0.03908 | 0.09645 | 0.05587 | 0.03721 |
| ATR_mid_33_67 | -0.02132 | 0.05736 | 0.07444 | 0.01245 | 0.0363 |
| ATR_high_67_100 | -0.001615 | 0.009337 | -0.0343 | 0.01528 | -0.01054 |

### stoch short
| atr_bucket | Q1_shallow | Q2 | Q3 | Q4 | Q5_deep |
| --- | --- | --- | --- | --- | --- |
| ATR_missing | 0.04181 | 0.1606 | 0.125 | 0.09537 | 0.2795 |
| ATR_low_0_33 | -0.02934 | 0.0244 | 0.01806 | -0.001132 | 0.01661 |
| ATR_mid_33_67 | -0.03345 | -0.0586 | 0.02378 | -0.00496 | 0.01011 |
| ATR_high_67_100 | -0.03961 | -0.03369 | -0.01178 | -0.008727 | -0.007667 |

## Artifacts
- `depth_r_curves.csv`: 2,160 bucket rows, pooled and per-pair.
- `p1_depth_r.out`: run summary and headline survivor list.
