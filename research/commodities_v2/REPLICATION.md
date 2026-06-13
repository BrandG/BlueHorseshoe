# FTMO Commodity Universe Replication

Run date: 2026-06-13 UTC. Outputs: `research/commodities_v2/regate_ftmo_full/`.
Geometry matches the regate harness: 1% stop / 1% target, 0.25x stop limit offset, 84 max hold bars, matched always-in baselines, and block-bootstrap excess CIs.

## Verdict

Copper MA-distance does not replicate across the new FTMO/OANDA commodity set. The original copper cells remain positive, but the strongest support is copper-local and weakens materially in the 2021-2026 half. I would not graduate it to tracking-only wiring yet; treat it as a research watch item pending a future out-of-sample update or a broader industrial-metals confirmation.

The new six instruments do produce two CI-positive absolute-positive cells, but neither is MA-distance: wheat and sugar trigger on `atr_range_exp` H4 limit. That is not companion-shape evidence for copper, so the MA-distance family remains copper-local in this run.

## MA-Distance Cross-Instrument Table

| instrument | cell | mode | n | mean R | baseline | excess | excess CI |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BCO_USD | ema50_dist_low | limit | 4773 | +0.141 | +0.173 | -0.032 | [-0.069, -0.002] |
| BCO_USD | ema50_dist_low | market | 4773 | -0.107 | -0.070 | -0.037 | [-0.075, -0.003] |
| BCO_USD | sma50_dist_low | limit | 5098 | +0.141 | +0.173 | -0.032 | [-0.068, -0.003] |
| BCO_USD | sma50_dist_low | market | 5098 | -0.108 | -0.070 | -0.038 | [-0.075, -0.011] |
| CORN_USD | ema50_dist_low | limit | 3877 | +0.002 | +0.009 | -0.006 | [-0.057, +0.036] |
| CORN_USD | ema50_dist_low | market | 3877 | -0.217 | -0.232 | +0.015 | [-0.040, +0.068] |
| CORN_USD | sma50_dist_low | limit | 4249 | +0.038 | +0.009 | +0.030 | [-0.014, +0.069] |
| CORN_USD | sma50_dist_low | market | 4249 | -0.182 | -0.232 | +0.050 | [+0.000, +0.091] |
| NATGAS_USD | ema50_dist_low | limit | 6492 | -0.191 | -0.130 | -0.061 | [-0.089, -0.035] |
| NATGAS_USD | ema50_dist_low | market | 6492 | -0.404 | -0.344 | -0.060 | [-0.088, -0.034] |
| NATGAS_USD | sma50_dist_low | limit | 6758 | -0.180 | -0.130 | -0.050 | [-0.074, -0.019] |
| NATGAS_USD | sma50_dist_low | market | 6758 | -0.399 | -0.344 | -0.055 | [-0.081, -0.027] |
| SOYBN_USD | ema50_dist_low | limit | 3818 | +0.073 | +0.084 | -0.011 | [-0.059, +0.034] |
| SOYBN_USD | ema50_dist_low | market | 3818 | -0.151 | -0.156 | +0.005 | [-0.054, +0.061] |
| SOYBN_USD | sma50_dist_low | limit | 4339 | +0.083 | +0.084 | -0.001 | [-0.047, +0.046] |
| SOYBN_USD | sma50_dist_low | market | 4339 | -0.138 | -0.156 | +0.019 | [-0.041, +0.078] |
| SUGAR_USD | ema50_dist_low | limit | 2874 | +0.046 | +0.042 | +0.004 | [-0.041, +0.046] |
| SUGAR_USD | ema50_dist_low | market | 2874 | -0.187 | -0.190 | +0.003 | [-0.040, +0.048] |
| SUGAR_USD | sma50_dist_low | limit | 3037 | +0.043 | +0.042 | +0.001 | [-0.033, +0.037] |
| SUGAR_USD | sma50_dist_low | market | 3037 | -0.192 | -0.190 | -0.002 | [-0.040, +0.035] |
| WHEAT_USD | ema50_dist_low | limit | 4870 | +0.013 | +0.018 | -0.005 | [-0.047, +0.034] |
| WHEAT_USD | ema50_dist_low | market | 4870 | -0.219 | -0.226 | +0.007 | [-0.035, +0.048] |
| WHEAT_USD | sma50_dist_low | limit | 5295 | +0.024 | +0.018 | +0.006 | [-0.031, +0.043] |
| WHEAT_USD | sma50_dist_low | market | 5295 | -0.212 | -0.226 | +0.014 | [-0.025, +0.058] |
| WTICO_USD | ema50_dist_low | limit | 5068 | +0.089 | +0.151 | -0.062 | [-0.090, -0.029] |
| WTICO_USD | ema50_dist_low | market | 5068 | -0.147 | -0.086 | -0.061 | [-0.096, -0.033] |
| WTICO_USD | sma50_dist_low | limit | 5270 | +0.094 | +0.151 | -0.057 | [-0.087, -0.027] |
| WTICO_USD | sma50_dist_low | market | 5270 | -0.137 | -0.086 | -0.051 | [-0.080, -0.023] |
| XAG_USD | ema50_dist_low | limit | 4269 | +0.079 | +0.121 | -0.042 | [-0.073, -0.011] |
| XAG_USD | ema50_dist_low | market | 4269 | -0.166 | -0.124 | -0.042 | [-0.081, -0.004] |
| XAG_USD | sma50_dist_low | limit | 4588 | +0.087 | +0.121 | -0.034 | [-0.066, -0.004] |
| XAG_USD | sma50_dist_low | market | 4588 | -0.160 | -0.124 | -0.036 | [-0.075, -0.002] |
| XAU_USD | ema50_dist_low | limit | 2389 | +0.286 | +0.297 | -0.011 | [-0.081, +0.061] |
| XAU_USD | ema50_dist_low | market | 2389 | +0.031 | +0.063 | -0.032 | [-0.104, +0.038] |
| XAU_USD | sma50_dist_low | limit | 2926 | +0.249 | +0.297 | -0.048 | [-0.112, +0.017] |
| XAU_USD | sma50_dist_low | market | 2926 | +0.003 | +0.063 | -0.059 | [-0.136, +0.011] |
| XCU_USD | ema50_dist_low | limit | 3731 | +0.268 | +0.220 | +0.048 | [+0.014, +0.088] |
| XCU_USD | ema50_dist_low | market | 3731 | +0.038 | -0.017 | +0.055 | [+0.016, +0.100] |
| XCU_USD | sma50_dist_low | limit | 4209 | +0.259 | +0.220 | +0.039 | [-0.002, +0.081] |
| XCU_USD | sma50_dist_low | market | 4209 | +0.022 | -0.017 | +0.039 | [+0.002, +0.085] |
| XPD_USD | ema50_dist_low | limit | 5153 | -0.268 | -0.263 | -0.005 | [-0.039, +0.030] |
| XPD_USD | ema50_dist_low | market | 5153 | -0.501 | -0.497 | -0.004 | [-0.038, +0.027] |
| XPD_USD | sma50_dist_low | limit | 5488 | -0.275 | -0.263 | -0.012 | [-0.045, +0.017] |
| XPD_USD | sma50_dist_low | market | 5488 | -0.505 | -0.497 | -0.008 | [-0.040, +0.023] |
| XPT_USD | ema50_dist_low | limit | 4763 | -0.087 | -0.067 | -0.020 | [-0.046, +0.010] |
| XPT_USD | ema50_dist_low | market | 4763 | -0.326 | -0.314 | -0.012 | [-0.057, +0.025] |
| XPT_USD | sma50_dist_low | limit | 5097 | -0.091 | -0.067 | -0.024 | [-0.056, +0.005] |
| XPT_USD | sma50_dist_low | market | 5097 | -0.327 | -0.314 | -0.013 | [-0.051, +0.020] |

Read: copper is still the cleanest original survivor. No new-instrument MA-distance row has both positive absolute R and CI-positive excess. Grains show a few positive but non-significant excess rows; PGMs are negative after their high spread costs.

## Copper Parameter Neighborhood

Top 12 XCU_USD H4 MA-distance neighborhood rows:

| MA | period | threshold | mode | n | mean R | baseline | excess | excess CI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ema | 50 | -1.0% | market | 3731 | +0.038 | -0.017 | +0.055 | [+0.016, +0.100] |
| sma | 100 | -2.0% | market | 2976 | +0.031 | -0.017 | +0.049 | [-0.003, +0.097] |
| ema | 50 | -1.0% | limit | 3731 | +0.268 | +0.220 | +0.048 | [+0.014, +0.088] |
| ema | 100 | -0.5% | market | 5588 | +0.030 | -0.017 | +0.047 | [+0.006, +0.082] |
| ema | 200 | -2.0% | market | 3266 | +0.028 | -0.017 | +0.045 | [-0.005, +0.091] |
| ema | 100 | -1.0% | market | 4387 | +0.028 | -0.017 | +0.045 | [-0.003, +0.089] |
| ema | 100 | -2.0% | market | 2479 | +0.027 | -0.017 | +0.045 | [-0.002, +0.091] |
| sma | 100 | -1.0% | market | 4774 | +0.027 | -0.017 | +0.044 | [+0.006, +0.090] |
| sma | 200 | -2.0% | market | 3777 | +0.025 | -0.017 | +0.042 | [-0.001, +0.091] |
| sma | 50 | -1.0% | market | 4209 | +0.022 | -0.017 | +0.039 | [+0.002, +0.085] |
| ema | 200 | -0.5% | market | 5711 | +0.021 | -0.017 | +0.039 | [-0.005, +0.076] |
| sma | 50 | -1.0% | limit | 4209 | +0.259 | +0.220 | +0.039 | [-0.002, +0.081] |

The edge is not a single exact spike at EMA50/-1%. Positive excess appears across several market-entry thresholds and periods, but CI-positive rows cluster most clearly around EMA50/SMA50 and market entry. Limit-entry absolute R is high because the matched limit baseline is also strong; excess is less stable there.

## Copper Split-Half

| cell | mode | split | n | mean R | baseline | excess | excess CI |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ema50_dist_-1.0% | limit | 2016-2021 | 1644 | +0.261 | +0.218 | +0.043 | [-0.018, +0.099] |
| ema50_dist_-1.0% | limit | 2021-2026 | 2079 | +0.272 | +0.222 | +0.049 | [+0.001, +0.095] |
| ema50_dist_-1.0% | market | 2016-2021 | 1644 | +0.028 | -0.027 | +0.054 | [-0.025, +0.125] |
| ema50_dist_-1.0% | market | 2021-2026 | 2079 | +0.044 | -0.008 | +0.052 | [-0.012, +0.106] |
| sma50_dist_-1.0% | limit | 2016-2021 | 1852 | +0.276 | +0.218 | +0.058 | [+0.003, +0.117] |
| sma50_dist_-1.0% | limit | 2021-2026 | 2344 | +0.242 | +0.222 | +0.019 | [-0.023, +0.056] |
| sma50_dist_-1.0% | market | 2016-2021 | 1852 | +0.032 | -0.027 | +0.059 | [-0.011, +0.129] |
| sma50_dist_-1.0% | market | 2021-2026 | 2344 | +0.011 | -0.008 | +0.020 | [-0.026, +0.070] |

The sign holds in both halves for the 50-period cells, and EMA50 limit barely clears a positive lower CI in 2021-2026. The broader issue is that most split-half lower CIs still cross zero and SMA50 weakens materially after 2021. This is a yellow flag against immediate graduation.

## New-Six Full-Universe Survivors

| instrument | family | cell | tf | mode | dir | n | mean R | baseline | excess | excess CI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SUGAR_USD | mr_under_limit | atr_range_exp | H4 | limit | 1 | 901 | +0.112 | +0.042 | +0.070 | [+0.006, +0.140] |
| WHEAT_USD | mr_under_limit | atr_range_exp | H4 | limit | 1 | 2401 | +0.074 | +0.018 | +0.056 | [+0.007, +0.099] |

## Always-In Baselines For New Instruments

| instrument | tf | mode | dir | n | mean R | NW CI |
| --- | --- | --- | --- | --- | --- | --- |
| CORN_USD | D1 | limit | -1 | 3087 | -0.054 | [-0.089, -0.019] |
| CORN_USD | D1 | limit | 1 | 3087 | -0.071 | [-0.106, -0.036] |
| CORN_USD | D1 | market | -1 | 3087 | -0.286 | [-0.321, -0.251] |
| CORN_USD | D1 | market | 1 | 3087 | -0.288 | [-0.323, -0.253] |
| CORN_USD | H4 | limit | -1 | 15558 | -0.012 | [-0.037, +0.013] |
| CORN_USD | H4 | limit | 1 | 15558 | +0.009 | [-0.016, +0.033] |
| CORN_USD | H4 | market | -1 | 15558 | -0.256 | [-0.281, -0.230] |
| CORN_USD | H4 | market | 1 | 15558 | -0.232 | [-0.258, -0.206] |
| SOYBN_USD | D1 | limit | -1 | 3088 | +0.047 | [+0.013, +0.082] |
| SOYBN_USD | D1 | limit | 1 | 3088 | +0.037 | [+0.003, +0.072] |
| SOYBN_USD | D1 | market | -1 | 3088 | -0.194 | [-0.229, -0.158] |
| SOYBN_USD | D1 | market | 1 | 3088 | -0.188 | [-0.224, -0.153] |
| SOYBN_USD | H4 | limit | -1 | 15580 | +0.071 | [+0.043, +0.098] |
| SOYBN_USD | H4 | limit | 1 | 15580 | +0.084 | [+0.056, +0.111] |
| SOYBN_USD | H4 | market | -1 | 15580 | -0.169 | [-0.198, -0.141] |
| SOYBN_USD | H4 | market | 1 | 15580 | -0.156 | [-0.185, -0.128] |
| SUGAR_USD | D1 | limit | -1 | 2545 | -0.122 | [-0.161, -0.083] |
| SUGAR_USD | D1 | limit | 1 | 2545 | -0.096 | [-0.135, -0.057] |
| SUGAR_USD | D1 | market | -1 | 2545 | -0.276 | [-0.315, -0.238] |
| SUGAR_USD | D1 | market | 1 | 2545 | -0.287 | [-0.326, -0.249] |
| SUGAR_USD | H4 | limit | -1 | 7774 | +0.046 | [+0.024, +0.068] |
| SUGAR_USD | H4 | limit | 1 | 7774 | +0.042 | [+0.020, +0.063] |
| SUGAR_USD | H4 | market | -1 | 7774 | -0.172 | [-0.198, -0.146] |
| SUGAR_USD | H4 | market | 1 | 7774 | -0.190 | [-0.216, -0.165] |
| WHEAT_USD | D1 | limit | -1 | 3088 | -0.086 | [-0.121, -0.051] |
| WHEAT_USD | D1 | limit | 1 | 3088 | -0.145 | [-0.180, -0.109] |
| WHEAT_USD | D1 | market | -1 | 3088 | -0.288 | [-0.323, -0.253] |
| WHEAT_USD | D1 | market | 1 | 3088 | -0.342 | [-0.377, -0.308] |
| WHEAT_USD | H4 | limit | -1 | 15566 | +0.037 | [+0.015, +0.058] |
| WHEAT_USD | H4 | limit | 1 | 15566 | +0.018 | [-0.004, +0.039] |
| WHEAT_USD | H4 | market | -1 | 15566 | -0.206 | [-0.228, -0.184] |
| WHEAT_USD | H4 | market | 1 | 15566 | -0.226 | [-0.248, -0.204] |
| XPD_USD | D1 | limit | -1 | 3155 | -0.595 | [-0.633, -0.557] |
| XPD_USD | D1 | limit | 1 | 3155 | -0.510 | [-0.547, -0.472] |
| XPD_USD | D1 | market | -1 | 3155 | -0.774 | [-0.811, -0.737] |
| XPD_USD | D1 | market | 1 | 3155 | -0.687 | [-0.724, -0.649] |
| XPD_USD | H4 | limit | -1 | 15953 | -0.334 | [-0.354, -0.313] |
| XPD_USD | H4 | limit | 1 | 15953 | -0.263 | [-0.283, -0.244] |
| XPD_USD | H4 | market | -1 | 15953 | -0.576 | [-0.596, -0.555] |
| XPD_USD | H4 | market | 1 | 15953 | -0.497 | [-0.517, -0.476] |
| XPT_USD | D1 | limit | -1 | 3162 | -0.224 | [-0.260, -0.189] |
| XPT_USD | D1 | limit | 1 | 3162 | -0.217 | [-0.252, -0.182] |
| XPT_USD | D1 | market | -1 | 3162 | -0.440 | [-0.475, -0.404] |
| XPT_USD | D1 | market | 1 | 3162 | -0.429 | [-0.464, -0.394] |
| XPT_USD | H4 | limit | -1 | 15996 | -0.076 | [-0.098, -0.055] |
| XPT_USD | H4 | limit | 1 | 15996 | -0.067 | [-0.086, -0.049] |
| XPT_USD | H4 | market | -1 | 15996 | -0.328 | [-0.351, -0.306] |
| XPT_USD | H4 | market | 1 | 15996 | -0.314 | [-0.336, -0.292] |

None of the new six is a gold-like runaway beta instrument. XPT/XPD baselines are strongly negative after their high spread costs. The ags' H4 limit baselines are near flat to mildly positive, while market baselines are materially negative after spread.

## Session And Data Notes

The onboarded OANDA candles validated cleanly during backfill, and the sweep's stored validator output is summarized below. The ags do not trade a metals/energy-style near-23h session, so NY-anchored commodity validation gaps on those instruments are calendar mismatch, not evidence of missing bars.

| instrument | granularity | issue | count |
| --- | --- | --- | --- |
| BCO_USD | H1 | data_gap | 5859 |
| BCO_USD | H4 | data_gap | 170 |
| CORN_USD | H1 | data_gap | 14168 |
| CORN_USD | H4 | data_gap | 708 |
| NATGAS_USD | H1 | data_gap | 1091 |
| NATGAS_USD | H4 | data_gap | 217 |
| SOYBN_USD | H1 | data_gap | 13165 |
| SOYBN_USD | H4 | data_gap | 686 |
| SUGAR_USD | H1 | data_gap | 36769 |
| SUGAR_USD | H4 | data_gap | 8491 |
| WHEAT_USD | H1 | data_gap | 13324 |
| WHEAT_USD | H4 | data_gap | 700 |
| WTICO_USD | H1 | data_gap | 959 |
| WTICO_USD | H4 | data_gap | 221 |
| XAG_USD | H1 | data_gap | 954 |
| XAG_USD | H4 | data_gap | 217 |
| XAU_USD | H1 | data_gap | 945 |
| XAU_USD | H4 | data_gap | 218 |
| XCU_USD | H1 | data_gap | 954 |
| XCU_USD | H4 | data_gap | 217 |
| XPD_USD | H1 | data_gap | 1640 |
| XPD_USD | H4 | data_gap | 319 |
| XPT_USD | H1 | data_gap | 1437 |
| XPT_USD | H4 | data_gap | 276 |

Observed weekday-hour patterns for the six new instruments are in `regate_ftmo_full/session_profile.csv`; key point: XPT/XPD look like the metals session, CORN/WHEAT/SOYBN H1 trade mostly weekday 00-19/20 UTC, and SUGAR is shorter and irregular around 07-17 UTC plus sparse evening prints.

Research cost metadata for the new six:

| instrument | FTMO | OANDA | pip | $/pip/lot | median H4 spread R |
| --- | --- | --- | --- | --- | --- |
| XPT_USD | XPT/USD | XPT_USD | 0.01 | 1.0 | 0.269 |
| XPD_USD | XPD/USD | XPD_USD | 0.01 | 1.0 | 0.388 |
| CORN_USD | CORN.c | CORN_USD | 0.01 | 1.0 | 0.233 |
| WHEAT_USD | WHEAT.c | WHEAT_USD | 0.01 | 1.0 | 0.188 |
| SOYBN_USD | SOYBEAN.c | SOYBN_USD | 0.01 | 1.0 | 0.163 |
| SUGAR_USD | SUGAR.c | SUGAR_USD | 0.001 | 0.1 | 0.153 |

Pip economics for PGMs and ags are placeholders for research only. The current sweep's R math is effectively pip-independent for spread and placeholder financing drag; verify FTMO contract economics before any wiring. FTMO-tradeable coffee, cocoa, cotton, and heating oil remain out of scope here because OANDA does not serve these candles.

Harness caveats retained: `bars_per_day = 6` overstates ag H4 bar density, mildly understating hold-days/financing drag, and `max_hold_bars = 84` spans more calendar days on shorter-session instruments. These do not change spread costs or excess-vs-baseline comparisons.

## Cell Design Decision

Do not wire a tracking cell from this run. If a future review insists on tracking despite the limited replication, the only defensible research spec is H4 long MA-distance mean reversion on XCU_USD with EMA/SMA 50, close at least 1% below MA, market entry preferred for cleaner excess-vs-baseline behavior, 1% stop / 1% target, and 84-bar max hold. Wheat and sugar ATR-expansion limit cells should be treated as separate research leads, not companions for copper.

Supporting CSVs: `copper_ma_neighborhood.csv` and `copper_ma_split_half.csv`.
