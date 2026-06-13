# Confluence P1a

## Method
Ran the narrowed strict-AND P1a sweep on the 17 deployed forex pairs from `factor_grouping.deployed_cells()`, using modal-deployed evaluator params from `factor_grouping.choose_params()` and direction-aware fresh fire masks from `co_fire.DIR_MASKERS`.

Simulation uses raw mid-price fills only: `sim_*_mid` and `sim_*_limit` from `research/v2_executable_regate/harness/_lib.py`, with TP_PCT=1.00%, STOP_PCT=1.00%, and one fixed `MAX_HOLD=84` bars for every BOTH and control cell. Source: v2 ledger harness `research/v2_executable_regate/harness/_lib.py`; the seed regate scripts also document this as the deployed ledger geometry.

Pairs: AUD_CAD, AUD_JPY, CAD_CHF, CAD_JPY, CHF_JPY, EUR_CAD, EUR_CHF, EUR_GBP, EUR_NOK, EUR_USD, GBP_CAD, NZD_CHF, NZD_JPY, NZD_USD, USD_CAD, USD_JPY, USD_SGD.

## Modal Params
- stoch: `{'k_period': 9, 'd_period': 3, 'threshold': 20, 'recovery': 1}` (tied modal deployed param set (1/4 cells); ranked-cell order broke tie)
- bb: `{'period': 50, 'n_std': 2.0, 'depth': 0.0}` (modal deployed param set (2/5 cells))
- macd: `{'fast': 6, 'slow': 13, 'signal': 9, 'trigger': 'signal_cross'}` (modal deployed param set (2/5 cells))
- sma: `{'period': 200, 'k': 2.5, 'atr_period': 14}` (modal deployed param set (2/3 cells))
- ema: `{'period': 20, 'k': 2.0, 'atr_period': 14}` (tied modal deployed param set (1/4 cells); ranked-cell order broke tie)
- rsi: `{'period': 14, 'threshold': 35, 'recovery': 1}` (tied modal deployed param set (1/3 cells); ranked-cell order broke tie)
- cci: `{'period': 14, 'threshold': 100, 'recovery': 1}` (tied modal deployed param set (1/5 cells); ranked-cell order broke tie)
- atr: `{'atr_period': 14, 'k': 0.5, 'trigger': 'range_expansion', 'range_lookback': 14}` (modal deployed param set (2/3 cells))
- ichimoku: `{'tenkan': 9, 'kijun': 26, 'senkou_b': 52, 'displacement': 26, 'trigger': 'tk_cross'}` (only deployed param set)
- candle: `{'pattern': 'bull_engulf', 'strict': False}` (single briefing.CELLS param set; evaluator is in _EVALUATORS but not selected by deploy_predicate)

## Verdict
- macd+stoch (candidate): SURVIVES P1a in PAIR/EUR_CAD/long/mid.
- macd+rsi (candidate): SURVIVES P1a in PAIR/EUR_CAD/long/mid, PAIR/NZD_CHF/short/mid.
- macd+cci (candidate): no BOTH cell cleared both P1a gates.
- bb+ema (control): SURVIVES P1a in PAIR/AUD_CAD/short/limit, PAIR/AUD_CAD/short/mid, PAIR/AUD_JPY/short/mid, PAIR/EUR_CAD/long/mid, PAIR/NZD_CHF/short/mid, POOLED/POOLED/short/mid.
- stoch+rsi (control): SURVIVES P1a in PAIR/AUD_CAD/short/limit, PAIR/AUD_CAD/short/mid, PAIR/CAD_CHF/short/limit, PAIR/EUR_CAD/long/mid, PAIR/EUR_CAD/short/limit, PAIR/EUR_GBP/long/limit, PAIR/EUR_USD/long/limit, PAIR/EUR_USD/short/mid, PAIR/USD_JPY/long/limit, PAIR/USD_JPY/long/mid, POOLED/POOLED/long/mid.
- stoch+atr (control): SURVIVES P1a in PAIR/AUD_CAD/short/limit, PAIR/CAD_CHF/short/limit, PAIR/EUR_CAD/long/limit, PAIR/USD_JPY/long/mid, PAIR/USD_SGD/short/limit.

Primary pooled candidate verdict: no macd-crossed BOTH cell clears both P1a gates.
P1b candidate set from all raw P1a survivors, including eligible per-pair cells:
- macd+rsi PAIR/EUR_CAD long mid: n=75, mean_R=0.2938, CI_low=0.0942
- macd+rsi PAIR/NZD_CHF short mid: n=72, mean_R=0.2594, CI_low=0.0380
- macd+stoch PAIR/EUR_CAD long mid: n=94, mean_R=0.2738, CI_low=0.0958

## Pooled BOTH Gates
| evaluator_pair | scope | direction | entry | n | mean_R | CI_low | component_best | pass |
|---|---:|---|---|---:|---:|---:|---:|---|
| bb+ema | POOLED | long | limit | 1594 | 0.0283 | -0.0187 | 0.0336 | False |
| bb+ema | POOLED | long | mid | 2226 | 0.0438 | 0.0040 | 0.0447 | False |
| bb+ema | POOLED | short | limit | 1632 | 0.0426 | -0.0041 | 0.0399 | False |
| bb+ema | POOLED | short | mid | 2265 | 0.0560 | 0.0164 | 0.0411 | True |
| macd+cci | POOLED | long | limit | 186 | 0.0681 | -0.0703 | 0.0438 | False |
| macd+cci | POOLED | long | mid | 1216 | 0.0135 | -0.0403 | 0.0278 | False |
| macd+cci | POOLED | short | limit | 199 | 0.0316 | -0.1021 | 0.0258 | False |
| macd+cci | POOLED | short | mid | 1356 | -0.0219 | -0.0729 | -0.0003 | False |
| macd+rsi | POOLED | long | limit | 260 | 0.0369 | -0.0789 | 0.0544 | False |
| macd+rsi | POOLED | long | mid | 1342 | 0.0390 | -0.0121 | 0.0309 | False |
| macd+rsi | POOLED | short | limit | 277 | 0.0579 | -0.0566 | 0.0258 | False |
| macd+rsi | POOLED | short | mid | 1484 | 0.0022 | -0.0469 | 0.0110 | False |
| macd+stoch | POOLED | long | limit | 250 | 0.0267 | -0.0908 | 0.0425 | False |
| macd+stoch | POOLED | long | mid | 1534 | 0.0354 | -0.0123 | 0.0263 | False |
| macd+stoch | POOLED | short | limit | 296 | 0.0781 | -0.0315 | 0.0258 | False |
| macd+stoch | POOLED | short | mid | 1783 | -0.0064 | -0.0511 | -0.0018 | False |
| stoch+atr | POOLED | long | limit | 4723 | 0.0257 | -0.0015 | 0.0425 | False |
| stoch+atr | POOLED | long | mid | 17540 | 0.0172 | 0.0031 | 0.0263 | False |
| stoch+atr | POOLED | short | limit | 5003 | 0.0141 | -0.0124 | 0.0115 | False |
| stoch+atr | POOLED | short | mid | 18491 | -0.0101 | -0.0238 | -0.0056 | False |
| stoch+rsi | POOLED | long | limit | 2168 | 0.0518 | 0.0116 | 0.0544 | False |
| stoch+rsi | POOLED | long | mid | 7157 | 0.0328 | 0.0107 | 0.0309 | True |
| stoch+rsi | POOLED | short | limit | 2298 | 0.0327 | -0.0064 | 0.0202 | False |
| stoch+rsi | POOLED | short | mid | 7605 | 0.0109 | -0.0106 | 0.0110 | False |

## Pooled Attribution
| evaluator_pair | direction | entry | A_all | B_all | A_pure | B_pure | BOTH |
|---|---|---|---:|---:|---:|---:|---:|
| bb+ema | long | limit | 0.0336 | 0.0092 | 0.0373 | -0.0039 | 0.0283 |
| bb+ema | long | mid | 0.0447 | 0.0273 | 0.0453 | 0.0161 | 0.0438 |
| bb+ema | short | limit | 0.0273 | 0.0399 | 0.0163 | 0.0381 | 0.0426 |
| bb+ema | short | mid | 0.0397 | 0.0411 | 0.0284 | 0.0313 | 0.0560 |
| macd+cci | long | limit | 0.0176 | 0.0438 | 0.0153 | 0.0432 | 0.0681 |
| macd+cci | long | mid | 0.0075 | 0.0278 | 0.0070 | 0.0287 | 0.0135 |
| macd+cci | short | limit | 0.0258 | 0.0099 | 0.0255 | 0.0094 | 0.0316 |
| macd+cci | short | mid | -0.0018 | -0.0003 | -0.0000 | 0.0012 | -0.0219 |
| macd+rsi | long | limit | 0.0176 | 0.0544 | 0.0163 | 0.0557 | 0.0369 |
| macd+rsi | long | mid | 0.0075 | 0.0309 | 0.0047 | 0.0299 | 0.0390 |
| macd+rsi | short | limit | 0.0258 | 0.0202 | 0.0235 | 0.0171 | 0.0579 |
| macd+rsi | short | mid | -0.0018 | 0.0110 | -0.0022 | 0.0123 | 0.0022 |
| macd+stoch | long | limit | 0.0176 | 0.0425 | 0.0170 | 0.0429 | 0.0267 |
| macd+stoch | long | mid | 0.0075 | 0.0263 | 0.0046 | 0.0258 | 0.0354 |
| macd+stoch | short | limit | 0.0258 | 0.0115 | 0.0218 | 0.0097 | 0.0781 |
| macd+stoch | short | mid | -0.0018 | -0.0056 | -0.0013 | -0.0055 | -0.0064 |
| stoch+atr | long | limit | 0.0425 | 0.0227 | 0.0563 | 0.0217 | 0.0257 |
| stoch+atr | long | mid | 0.0263 | 0.0107 | 0.0408 | 0.0085 | 0.0172 |
| stoch+atr | short | limit | 0.0115 | 0.0057 | 0.0094 | 0.0026 | 0.0141 |
| stoch+atr | short | mid | -0.0056 | -0.0110 | 0.0014 | -0.0114 | -0.0101 |
| stoch+rsi | long | limit | 0.0425 | 0.0544 | 0.0400 | 0.0582 | 0.0518 |
| stoch+rsi | long | mid | 0.0263 | 0.0309 | 0.0242 | 0.0281 | 0.0328 |
| stoch+rsi | short | limit | 0.0115 | 0.0202 | 0.0061 | -0.0004 | 0.0327 |
| stoch+rsi | short | mid | -0.0056 | 0.0110 | -0.0111 | 0.0113 | 0.0109 |

## Eligible Per-Pair BOTH Gates
| evaluator_pair | scope | direction | entry | n | mean_R | CI_low | component_best | pass |
|---|---:|---|---|---:|---:|---:|---:|---|
| bb+ema | AUD_CAD | long | limit | 78 | -0.0402 | -0.2523 | 0.0539 | False |
| bb+ema | AUD_CAD | long | mid | 111 | 0.0357 | -0.1412 | 0.0827 | False |
| bb+ema | AUD_CAD | short | limit | 76 | 0.2895 | 0.0757 | 0.2374 | True |
| bb+ema | AUD_CAD | short | mid | 104 | 0.2447 | 0.0633 | 0.1698 | True |
| bb+ema | AUD_JPY | long | limit | 95 | -0.0393 | -0.2403 | -0.0227 | False |
| bb+ema | AUD_JPY | long | mid | 135 | -0.1473 | -0.3141 | -0.0653 | False |
| bb+ema | AUD_JPY | short | limit | 92 | 0.1606 | -0.0412 | 0.0410 | False |
| bb+ema | AUD_JPY | short | mid | 133 | 0.2149 | 0.0500 | 0.0934 | True |
| bb+ema | CAD_CHF | long | limit | 94 | -0.1426 | -0.3400 | -0.0573 | False |
| bb+ema | CAD_CHF | long | mid | 129 | -0.1559 | -0.3249 | -0.0549 | False |
| bb+ema | CAD_CHF | short | limit | 97 | 0.0906 | -0.1057 | 0.1647 | False |
| bb+ema | CAD_CHF | short | mid | 124 | 0.0641 | -0.1102 | 0.1196 | False |
| bb+ema | CAD_JPY | long | limit | 101 | 0.0131 | -0.1824 | 0.0229 | False |
| bb+ema | CAD_JPY | long | mid | 149 | 0.0402 | -0.1203 | 0.0735 | False |
| bb+ema | CAD_JPY | short | limit | 111 | -0.0821 | -0.2667 | 0.0286 | False |
| bb+ema | CAD_JPY | short | mid | 137 | -0.0258 | -0.1909 | 0.0391 | False |
| bb+ema | CHF_JPY | long | limit | 82 | 0.2365 | 0.0339 | 0.2581 | False |
| bb+ema | CHF_JPY | long | mid | 112 | 0.1732 | -0.0025 | 0.2327 | False |
| bb+ema | CHF_JPY | short | limit | 93 | 0.1871 | -0.0057 | 0.0494 | False |
| bb+ema | CHF_JPY | short | mid | 134 | 0.0679 | -0.0962 | -0.0128 | False |
| bb+ema | EUR_CAD | long | limit | 94 | 0.1489 | -0.0411 | 0.1454 | False |
| bb+ema | EUR_CAD | long | mid | 134 | 0.2588 | 0.1028 | 0.1640 | True |
| bb+ema | EUR_CAD | short | limit | 112 | 0.0561 | -0.1193 | 0.0562 | False |
| bb+ema | EUR_CAD | short | mid | 170 | 0.0934 | -0.0512 | 0.0792 | False |
| bb+ema | EUR_CHF | long | limit | 85 | -0.1129 | -0.2903 | -0.0313 | False |
| bb+ema | EUR_CHF | long | mid | 120 | -0.0832 | -0.2333 | -0.0402 | False |
| bb+ema | EUR_CHF | short | limit | 67 | -0.0982 | -0.3149 | 0.0528 | False |
| bb+ema | EUR_CHF | short | mid | 103 | -0.0828 | -0.2582 | 0.0581 | False |
| bb+ema | EUR_GBP | long | limit | 93 | 0.0560 | -0.1301 | 0.0686 | False |
| bb+ema | EUR_GBP | long | mid | 131 | 0.1120 | -0.0435 | 0.1214 | False |
| bb+ema | EUR_GBP | short | limit | 105 | 0.0268 | -0.1570 | 0.0758 | False |
| bb+ema | EUR_GBP | short | mid | 155 | 0.0368 | -0.1127 | 0.1052 | False |
| bb+ema | EUR_NOK | long | limit | 79 | 0.1893 | -0.0222 | 0.2281 | False |
| bb+ema | EUR_NOK | long | mid | 116 | 0.1166 | -0.0578 | 0.1593 | False |
| bb+ema | EUR_NOK | short | limit | 79 | 0.0176 | -0.1992 | -0.0152 | False |
| bb+ema | EUR_NOK | short | mid | 133 | 0.0604 | -0.1044 | -0.0123 | False |
| bb+ema | EUR_USD | long | limit | 117 | 0.0893 | -0.0884 | 0.0246 | False |
| bb+ema | EUR_USD | long | mid | 163 | 0.0420 | -0.1081 | 0.0288 | False |
| bb+ema | EUR_USD | short | limit | 106 | -0.0567 | -0.2410 | 0.1000 | False |
| bb+ema | EUR_USD | short | mid | 159 | -0.0490 | -0.1972 | 0.1068 | False |
| bb+ema | GBP_CAD | long | limit | 97 | -0.0256 | -0.2196 | -0.0294 | False |
| bb+ema | GBP_CAD | long | mid | 132 | 0.0408 | -0.1267 | -0.0213 | False |
| bb+ema | GBP_CAD | short | limit | 97 | 0.0588 | -0.1332 | 0.0383 | False |
| bb+ema | GBP_CAD | short | mid | 141 | 0.0980 | -0.0593 | 0.0550 | False |
| bb+ema | NZD_CHF | long | limit | 95 | 0.0375 | -0.1607 | 0.0311 | False |
| bb+ema | NZD_CHF | long | mid | 123 | 0.0477 | -0.1262 | 0.0638 | False |
| bb+ema | NZD_CHF | short | limit | 72 | 0.2174 | -0.0068 | 0.2276 | False |
| bb+ema | NZD_CHF | short | mid | 91 | 0.2059 | 0.0058 | 0.1990 | True |
| bb+ema | NZD_JPY | long | limit | 88 | 0.0227 | -0.1874 | -0.0132 | False |
| bb+ema | NZD_JPY | long | mid | 126 | -0.0317 | -0.2070 | -0.0395 | False |
| bb+ema | NZD_JPY | short | limit | 89 | -0.0615 | -0.2692 | -0.0536 | False |
| bb+ema | NZD_JPY | short | mid | 116 | -0.0586 | -0.2403 | -0.0585 | False |
| bb+ema | NZD_USD | long | limit | 104 | 0.0385 | -0.1545 | 0.0125 | False |
| bb+ema | NZD_USD | long | mid | 138 | 0.1014 | -0.0651 | 0.0509 | False |
| bb+ema | NZD_USD | short | limit | 103 | 0.0097 | -0.1844 | 0.1093 | False |
| bb+ema | NZD_USD | short | mid | 134 | 0.0000 | -0.1700 | 0.1009 | False |
| bb+ema | USD_CAD | long | limit | 94 | -0.0130 | -0.2060 | 0.0599 | False |
| bb+ema | USD_CAD | long | mid | 139 | 0.0720 | -0.0875 | 0.0873 | False |
| bb+ema | USD_CAD | short | limit | 104 | 0.0454 | -0.1359 | 0.0017 | False |
| bb+ema | USD_CAD | short | mid | 140 | 0.1020 | -0.0546 | 0.0477 | False |
| bb+ema | USD_JPY | long | limit | 102 | 0.1302 | -0.0610 | 0.1355 | False |
| bb+ema | USD_JPY | long | mid | 136 | 0.1600 | -0.0041 | 0.1981 | False |
| bb+ema | USD_JPY | short | limit | 115 | -0.0440 | -0.2206 | -0.0284 | False |
| bb+ema | USD_JPY | short | mid | 148 | -0.0082 | -0.1644 | -0.0630 | False |
| bb+ema | USD_SGD | long | limit | 96 | -0.0980 | -0.2623 | -0.0294 | False |
| bb+ema | USD_SGD | long | mid | 132 | -0.0352 | -0.1785 | -0.0027 | False |
| bb+ema | USD_SGD | short | limit | 114 | 0.0114 | -0.1473 | 0.0721 | False |
| bb+ema | USD_SGD | short | mid | 143 | 0.0497 | -0.0914 | 0.0925 | False |
| macd+cci | AUD_CAD | long | mid | 63 | -0.0011 | -0.2469 | 0.0220 | False |
| macd+cci | AUD_CAD | short | mid | 81 | 0.0147 | -0.1991 | 0.0494 | False |
| macd+cci | AUD_JPY | long | mid | 62 | -0.2340 | -0.4764 | 0.0561 | False |
| macd+cci | AUD_JPY | short | mid | 66 | 0.0606 | -0.1821 | 0.0034 | False |
| macd+cci | CAD_CHF | long | mid | 79 | -0.1048 | -0.3213 | -0.0310 | False |
| macd+cci | CAD_CHF | short | mid | 69 | 0.1649 | -0.0551 | 0.1342 | False |
| macd+cci | CAD_JPY | long | mid | 58 | 0.1724 | -0.0833 | 0.0200 | False |
| macd+cci | CAD_JPY | short | mid | 79 | -0.0656 | -0.2848 | -0.0123 | False |
| macd+cci | CHF_JPY | long | mid | 73 | 0.1576 | -0.0584 | 0.1057 | False |
| macd+cci | CHF_JPY | short | mid | 102 | -0.1542 | -0.3435 | -0.0536 | False |
| macd+cci | EUR_CAD | long | mid | 80 | 0.0725 | -0.1269 | 0.0514 | False |
| macd+cci | EUR_CAD | short | mid | 92 | -0.0128 | -0.2018 | -0.0164 | False |
| macd+cci | EUR_CHF | long | mid | 69 | -0.0406 | -0.2423 | -0.0452 | False |
| macd+cci | EUR_CHF | short | mid | 77 | 0.0263 | -0.1656 | 0.0381 | False |
| macd+cci | EUR_GBP | long | mid | 80 | 0.0018 | -0.1993 | 0.1075 | False |
| macd+cci | EUR_GBP | short | mid | 81 | 0.0400 | -0.1614 | 0.0174 | False |
| macd+cci | EUR_NOK | long | mid | 79 | 0.0940 | -0.1205 | 0.0777 | False |
| macd+cci | EUR_NOK | short | mid | 64 | 0.1180 | -0.1216 | -0.0461 | False |
| macd+cci | EUR_USD | long | mid | 86 | 0.0730 | -0.1296 | 0.0055 | False |
| macd+cci | EUR_USD | short | mid | 72 | 0.1874 | -0.0328 | 0.0729 | False |
| macd+cci | GBP_CAD | long | mid | 60 | 0.1568 | -0.0884 | 0.0154 | False |
| macd+cci | GBP_CAD | short | mid | 74 | -0.2555 | -0.4655 | -0.0208 | False |
| macd+cci | NZD_CHF | long | mid | 60 | -0.0151 | -0.2639 | 0.0318 | False |
| macd+cci | NZD_CHF | short | mid | 74 | 0.0632 | -0.1627 | 0.0764 | False |
| macd+cci | NZD_JPY | long | mid | 75 | -0.2533 | -0.4737 | 0.0134 | False |
| macd+cci | NZD_JPY | short | mid | 87 | -0.0852 | -0.2950 | -0.0100 | False |
| macd+cci | NZD_USD | long | mid | 75 | 0.0098 | -0.2174 | 0.0136 | False |
| macd+cci | NZD_USD | short | mid | 84 | -0.0238 | -0.2389 | 0.0300 | False |
| macd+cci | USD_CAD | long | mid | 74 | 0.0574 | -0.1645 | 0.0616 | False |
| macd+cci | USD_CAD | short | mid | 84 | -0.1435 | -0.3434 | -0.0173 | False |
| macd+cci | USD_JPY | long | mid | 63 | 0.0415 | -0.2037 | 0.1004 | False |
| macd+cci | USD_JPY | short | mid | 102 | -0.1369 | -0.3245 | -0.0538 | False |
| macd+cci | USD_SGD | long | mid | 80 | 0.0483 | -0.1477 | 0.0041 | False |
| macd+cci | USD_SGD | short | mid | 68 | -0.0124 | -0.2202 | 0.0524 | False |
| macd+rsi | AUD_CAD | long | mid | 75 | 0.1555 | -0.0667 | 0.0101 | False |
| macd+rsi | AUD_CAD | short | mid | 64 | 0.1769 | -0.0611 | 0.1245 | False |
| macd+rsi | AUD_JPY | long | mid | 55 | -0.0909 | -0.3565 | 0.0561 | False |
| macd+rsi | AUD_JPY | short | mid | 80 | 0.0000 | -0.2205 | -0.0091 | False |
| macd+rsi | CAD_CHF | long | mid | 92 | -0.1534 | -0.3503 | -0.0964 | False |
| macd+rsi | CAD_CHF | short | mid | 76 | 0.1295 | -0.0880 | 0.1085 | False |
| macd+rsi | CAD_JPY | long | mid | 59 | 0.1421 | -0.1108 | 0.0200 | False |
| macd+rsi | CAD_JPY | short | mid | 108 | -0.0357 | -0.2219 | -0.0018 | False |
| macd+rsi | CHF_JPY | long | mid | 74 | 0.1380 | -0.0860 | 0.1708 | False |
| macd+rsi | CHF_JPY | short | mid | 107 | -0.0915 | -0.2759 | -0.0536 | False |
| macd+rsi | EUR_CAD | long | mid | 75 | 0.2938 | 0.0942 | 0.1074 | True |
| macd+rsi | EUR_CAD | short | mid | 95 | -0.1282 | -0.3139 | 0.0039 | False |
| macd+rsi | EUR_CHF | long | mid | 78 | 0.0603 | -0.1364 | -0.0292 | False |
| macd+rsi | EUR_CHF | short | mid | 79 | -0.1821 | -0.3749 | 0.0497 | False |
| macd+rsi | EUR_GBP | long | mid | 83 | 0.0116 | -0.1834 | 0.1362 | False |
| macd+rsi | EUR_GBP | short | mid | 86 | -0.0231 | -0.2268 | 0.0123 | False |
| macd+rsi | EUR_NOK | long | mid | 90 | 0.0879 | -0.1140 | 0.0949 | False |
| macd+rsi | EUR_NOK | short | mid | 79 | 0.0546 | -0.1583 | -0.0062 | False |
| macd+rsi | EUR_USD | long | mid | 104 | 0.1213 | -0.0621 | 0.0483 | False |
| macd+rsi | EUR_USD | short | mid | 76 | 0.0869 | -0.1325 | 0.0644 | False |
| macd+rsi | GBP_CAD | long | mid | 81 | 0.0837 | -0.1268 | 0.0154 | False |
| macd+rsi | GBP_CAD | short | mid | 85 | -0.0746 | -0.2768 | -0.0208 | False |
| macd+rsi | NZD_CHF | long | mid | 72 | -0.0406 | -0.2682 | -0.0436 | False |
| macd+rsi | NZD_CHF | short | mid | 72 | 0.2594 | 0.0380 | 0.1507 | True |
| macd+rsi | NZD_JPY | long | mid | 70 | -0.2286 | -0.4583 | 0.0134 | False |
| macd+rsi | NZD_JPY | short | mid | 90 | 0.0491 | -0.1576 | 0.0129 | False |
| macd+rsi | NZD_USD | long | mid | 87 | -0.0805 | -0.2911 | 0.0373 | False |
| macd+rsi | NZD_USD | short | mid | 92 | 0.1087 | -0.0956 | 0.0300 | False |
| macd+rsi | USD_CAD | long | mid | 84 | 0.0676 | -0.1335 | 0.0598 | False |
| macd+rsi | USD_CAD | short | mid | 107 | -0.0320 | -0.2162 | 0.0045 | False |
| macd+rsi | USD_JPY | long | mid | 71 | 0.0520 | -0.1790 | 0.1158 | False |
| macd+rsi | USD_JPY | short | mid | 122 | -0.1351 | -0.3059 | -0.0538 | False |
| macd+rsi | USD_SGD | long | mid | 92 | 0.0296 | -0.1413 | 0.0503 | False |
| macd+rsi | USD_SGD | short | mid | 66 | 0.0980 | -0.1088 | 0.0227 | False |
| macd+stoch | AUD_CAD | long | mid | 90 | 0.1367 | -0.0626 | 0.0401 | False |
| macd+stoch | AUD_CAD | short | mid | 106 | 0.0110 | -0.1775 | 0.0319 | False |
| macd+stoch | AUD_JPY | long | mid | 73 | -0.0959 | -0.3258 | 0.0561 | False |
| macd+stoch | AUD_JPY | short | mid | 110 | 0.0937 | -0.0928 | -0.0091 | False |
| macd+stoch | CAD_CHF | long | mid | 102 | -0.1396 | -0.3291 | -0.0733 | False |
| macd+stoch | CAD_CHF | short | mid | 94 | 0.1253 | -0.0703 | 0.1186 | False |
| macd+stoch | CAD_JPY | long | mid | 72 | 0.0833 | -0.1485 | 0.0200 | False |
| macd+stoch | CAD_JPY | short | mid | 132 | -0.0187 | -0.1894 | -0.0123 | False |
| macd+stoch | CHF_JPY | long | mid | 78 | 0.1357 | -0.0813 | 0.1020 | False |
| macd+stoch | CHF_JPY | short | mid | 131 | -0.0969 | -0.2658 | -0.0536 | False |
| macd+stoch | EUR_CAD | long | mid | 94 | 0.2738 | 0.0958 | 0.0743 | True |
| macd+stoch | EUR_CAD | short | mid | 106 | -0.0059 | -0.1815 | -0.0109 | False |
| macd+stoch | EUR_CHF | long | mid | 100 | -0.0421 | -0.2124 | -0.0452 | False |
| macd+stoch | EUR_CHF | short | mid | 100 | -0.0098 | -0.1770 | 0.0405 | False |
| macd+stoch | EUR_GBP | long | mid | 112 | 0.0669 | -0.0953 | 0.0820 | False |
| macd+stoch | EUR_GBP | short | mid | 87 | -0.0675 | -0.2552 | 0.0158 | False |
| macd+stoch | EUR_NOK | long | mid | 92 | -0.0551 | -0.2571 | 0.0480 | False |
| macd+stoch | EUR_NOK | short | mid | 69 | 0.0563 | -0.1760 | -0.0425 | False |
| macd+stoch | EUR_USD | long | mid | 111 | 0.0535 | -0.1277 | 0.0464 | False |
| macd+stoch | EUR_USD | short | mid | 92 | 0.0698 | -0.1288 | 0.0458 | False |
| macd+stoch | GBP_CAD | long | mid | 75 | 0.0742 | -0.1463 | 0.0154 | False |
| macd+stoch | GBP_CAD | short | mid | 103 | -0.0180 | -0.2031 | 0.0021 | False |
| macd+stoch | NZD_CHF | long | mid | 78 | 0.0080 | -0.2100 | 0.0063 | False |
| macd+stoch | NZD_CHF | short | mid | 87 | 0.0364 | -0.1724 | 0.0488 | False |
| macd+stoch | NZD_JPY | long | mid | 80 | -0.2000 | -0.4161 | 0.0134 | False |
| macd+stoch | NZD_JPY | short | mid | 121 | -0.0048 | -0.1832 | -0.0100 | False |
| macd+stoch | NZD_USD | long | mid | 98 | -0.0612 | -0.2599 | 0.0004 | False |
| macd+stoch | NZD_USD | short | mid | 107 | 0.0280 | -0.1623 | 0.0300 | False |
| macd+stoch | USD_CAD | long | mid | 109 | 0.0692 | -0.1092 | 0.0257 | False |
| macd+stoch | USD_CAD | short | mid | 109 | -0.0063 | -0.1895 | -0.0313 | False |
| macd+stoch | USD_JPY | long | mid | 62 | 0.2115 | -0.0285 | 0.1121 | False |
| macd+stoch | USD_JPY | short | mid | 141 | -0.1105 | -0.2712 | -0.0538 | False |
| macd+stoch | USD_SGD | long | mid | 108 | 0.1097 | -0.0466 | 0.0128 | False |
| macd+stoch | USD_SGD | short | mid | 88 | -0.1107 | -0.2927 | 0.0444 | False |
| stoch+atr | AUD_CAD | long | limit | 292 | 0.0985 | -0.0119 | 0.0755 | False |
| stoch+atr | AUD_CAD | long | mid | 1059 | 0.0314 | -0.0270 | 0.0401 | False |
| stoch+atr | AUD_CAD | short | limit | 306 | 0.1096 | 0.0022 | 0.0805 | True |
| stoch+atr | AUD_CAD | short | mid | 1138 | 0.0366 | -0.0198 | 0.0319 | False |
| stoch+atr | AUD_JPY | long | limit | 272 | 0.0458 | -0.0727 | 0.0074 | False |
| stoch+atr | AUD_JPY | long | mid | 958 | 0.0348 | -0.0283 | 0.0328 | False |
| stoch+atr | AUD_JPY | short | limit | 350 | -0.0727 | -0.1766 | -0.0426 | False |
| stoch+atr | AUD_JPY | short | mid | 1216 | -0.0587 | -0.1146 | -0.0385 | False |
| stoch+atr | CAD_CHF | long | limit | 289 | -0.0904 | -0.2011 | -0.0415 | False |
| stoch+atr | CAD_CHF | long | mid | 1063 | -0.0953 | -0.1531 | -0.0733 | False |
| stoch+atr | CAD_CHF | short | limit | 256 | 0.1803 | 0.0641 | 0.1546 | True |
| stoch+atr | CAD_CHF | short | mid | 1069 | 0.1100 | 0.0524 | 0.1186 | False |
| stoch+atr | CAD_JPY | long | limit | 272 | 0.0516 | -0.0670 | 0.0281 | False |
| stoch+atr | CAD_JPY | long | mid | 977 | 0.0153 | -0.0472 | 0.0191 | False |
| stoch+atr | CAD_JPY | short | limit | 338 | -0.0726 | -0.1777 | -0.0529 | False |
| stoch+atr | CAD_JPY | short | mid | 1172 | -0.0235 | -0.0802 | -0.0117 | False |
| stoch+atr | CHF_JPY | long | limit | 290 | 0.1090 | 0.0001 | 0.1409 | False |
| stoch+atr | CHF_JPY | long | mid | 1007 | 0.0858 | 0.0268 | 0.0974 | False |
| stoch+atr | CHF_JPY | short | limit | 369 | -0.0872 | -0.1855 | -0.0665 | False |
| stoch+atr | CHF_JPY | short | mid | 1199 | -0.1023 | -0.1560 | -0.0894 | False |
| stoch+atr | EUR_CAD | long | limit | 241 | 0.1813 | 0.0648 | 0.1340 | True |
| stoch+atr | EUR_CAD | long | mid | 1053 | 0.0717 | 0.0151 | 0.0743 | False |
| stoch+atr | EUR_CAD | short | limit | 273 | 0.0482 | -0.0655 | 0.0339 | False |
| stoch+atr | EUR_CAD | short | mid | 1002 | -0.0233 | -0.0813 | -0.0109 | False |
| stoch+atr | EUR_CHF | long | limit | 265 | 0.0056 | -0.0944 | -0.0091 | False |
| stoch+atr | EUR_CHF | long | mid | 1010 | -0.0345 | -0.0853 | -0.0336 | False |
| stoch+atr | EUR_CHF | short | limit | 251 | -0.0804 | -0.1829 | 0.0281 | False |
| stoch+atr | EUR_CHF | short | mid | 1021 | 0.0339 | -0.0170 | 0.0405 | False |
| stoch+atr | EUR_GBP | long | limit | 237 | 0.1401 | 0.0279 | 0.1783 | False |
| stoch+atr | EUR_GBP | long | mid | 1004 | 0.0437 | -0.0121 | 0.0820 | False |
| stoch+atr | EUR_GBP | short | limit | 243 | 0.0638 | -0.0507 | 0.0315 | False |
| stoch+atr | EUR_GBP | short | mid | 960 | 0.0145 | -0.0431 | 0.0158 | False |
| stoch+atr | EUR_NOK | long | limit | 239 | 0.0924 | -0.0325 | 0.1251 | False |
| stoch+atr | EUR_NOK | long | mid | 966 | 0.0016 | -0.0599 | 0.0542 | False |
| stoch+atr | EUR_NOK | short | limit | 259 | 0.0092 | -0.1099 | 0.0190 | False |
| stoch+atr | EUR_NOK | short | mid | 888 | -0.0516 | -0.1159 | -0.0425 | False |
| stoch+atr | EUR_USD | long | limit | 267 | 0.0110 | -0.1060 | 0.0415 | False |
| stoch+atr | EUR_USD | long | mid | 1026 | 0.0396 | -0.0194 | 0.0464 | False |
| stoch+atr | EUR_USD | short | limit | 245 | 0.0400 | -0.0812 | 0.0357 | False |
| stoch+atr | EUR_USD | short | mid | 993 | 0.0580 | -0.0022 | 0.0458 | False |
| stoch+atr | GBP_CAD | long | limit | 230 | -0.1042 | -0.2283 | -0.0364 | False |
| stoch+atr | GBP_CAD | long | mid | 996 | 0.0020 | -0.0583 | -0.0037 | False |
| stoch+atr | GBP_CAD | short | limit | 261 | 0.0757 | -0.0413 | 0.0522 | False |
| stoch+atr | GBP_CAD | short | mid | 1035 | 0.0186 | -0.0400 | 0.0048 | False |
| stoch+atr | NZD_CHF | long | limit | 315 | -0.0314 | -0.1402 | -0.0046 | False |
| stoch+atr | NZD_CHF | long | mid | 1111 | 0.0133 | -0.0445 | 0.0063 | False |
| stoch+atr | NZD_CHF | short | limit | 307 | 0.1459 | 0.0365 | 0.1616 | False |
| stoch+atr | NZD_CHF | short | mid | 1101 | 0.0065 | -0.0518 | 0.0488 | False |
| stoch+atr | NZD_JPY | long | limit | 325 | -0.0171 | -0.1259 | 0.0056 | False |
| stoch+atr | NZD_JPY | long | mid | 1066 | 0.0048 | -0.0551 | 0.0454 | False |
| stoch+atr | NZD_JPY | short | limit | 341 | -0.0477 | -0.1530 | -0.0484 | False |
| stoch+atr | NZD_JPY | short | mid | 1221 | -0.0631 | -0.1189 | -0.0302 | False |
| stoch+atr | NZD_USD | long | limit | 314 | -0.0573 | -0.1679 | 0.0060 | False |
| stoch+atr | NZD_USD | long | mid | 1094 | -0.0113 | -0.0706 | 0.0004 | False |
| stoch+atr | NZD_USD | short | limit | 286 | -0.0280 | -0.1440 | 0.0510 | False |
| stoch+atr | NZD_USD | short | mid | 1130 | -0.0124 | -0.0707 | 0.0142 | False |
| stoch+atr | USD_CAD | long | limit | 289 | -0.0173 | -0.1290 | 0.0654 | False |
| stoch+atr | USD_CAD | long | mid | 1081 | -0.0100 | -0.0667 | 0.0376 | False |
| stoch+atr | USD_CAD | short | limit | 278 | -0.0598 | -0.1716 | -0.0191 | False |
| stoch+atr | USD_CAD | short | mid | 1063 | -0.0399 | -0.0968 | -0.0313 | False |
| stoch+atr | USD_JPY | long | limit | 264 | 0.0888 | -0.0298 | 0.0974 | False |
| stoch+atr | USD_JPY | long | mid | 949 | 0.1167 | 0.0554 | 0.1121 | True |
| stoch+atr | USD_JPY | short | limit | 296 | -0.0461 | -0.1551 | -0.0467 | False |
| stoch+atr | USD_JPY | short | mid | 1141 | -0.0947 | -0.1504 | -0.0743 | False |
| stoch+atr | USD_SGD | long | limit | 322 | -0.0115 | -0.1019 | 0.0104 | False |
| stoch+atr | USD_SGD | long | mid | 1120 | -0.0009 | -0.0494 | 0.0128 | False |
| stoch+atr | USD_SGD | short | limit | 344 | 0.1229 | 0.0368 | 0.0671 | True |
| stoch+atr | USD_SGD | short | mid | 1142 | 0.0477 | -0.0005 | 0.0444 | False |
| stoch+rsi | AUD_CAD | long | limit | 111 | 0.0637 | -0.1128 | 0.0998 | False |
| stoch+rsi | AUD_CAD | long | mid | 402 | 0.0126 | -0.0816 | 0.0401 | False |
| stoch+rsi | AUD_CAD | short | limit | 114 | 0.2971 | 0.1300 | 0.2230 | True |
| stoch+rsi | AUD_CAD | short | mid | 393 | 0.1562 | 0.0628 | 0.1245 | True |
| stoch+rsi | AUD_JPY | long | limit | 107 | 0.0073 | -0.1827 | -0.0004 | False |
| stoch+rsi | AUD_JPY | long | mid | 341 | -0.0029 | -0.1092 | 0.0328 | False |
| stoch+rsi | AUD_JPY | short | limit | 152 | -0.0902 | -0.2481 | -0.0841 | False |
| stoch+rsi | AUD_JPY | short | mid | 489 | -0.0405 | -0.1287 | -0.0351 | False |
| stoch+rsi | CAD_CHF | long | limit | 117 | -0.0955 | -0.2730 | -0.0415 | False |
| stoch+rsi | CAD_CHF | long | mid | 404 | -0.1326 | -0.2279 | -0.0733 | False |
| stoch+rsi | CAD_CHF | short | limit | 104 | 0.1895 | 0.0014 | 0.1546 | True |
| stoch+rsi | CAD_CHF | short | mid | 405 | 0.0894 | -0.0061 | 0.1186 | False |
| stoch+rsi | CAD_JPY | long | limit | 117 | 0.1266 | -0.0537 | 0.1176 | False |
| stoch+rsi | CAD_JPY | long | mid | 352 | 0.0287 | -0.0755 | 0.0141 | False |
| stoch+rsi | CAD_JPY | short | limit | 174 | -0.0396 | -0.1857 | -0.0602 | False |
| stoch+rsi | CAD_JPY | short | mid | 509 | 0.0191 | -0.0666 | -0.0018 | False |
| stoch+rsi | CHF_JPY | long | limit | 90 | 0.1915 | -0.0084 | 0.1772 | False |
| stoch+rsi | CHF_JPY | long | mid | 347 | 0.1535 | 0.0527 | 0.1708 | False |
| stoch+rsi | CHF_JPY | short | limit | 177 | -0.1645 | -0.3047 | -0.0665 | False |
| stoch+rsi | CHF_JPY | short | mid | 505 | -0.1432 | -0.2259 | -0.0955 | False |
| stoch+rsi | EUR_CAD | long | limit | 118 | 0.1370 | -0.0307 | 0.1340 | False |
| stoch+rsi | EUR_CAD | long | mid | 416 | 0.1571 | 0.0675 | 0.1074 | True |
| stoch+rsi | EUR_CAD | short | limit | 131 | 0.1711 | 0.0060 | 0.0857 | True |
| stoch+rsi | EUR_CAD | short | mid | 422 | 0.0645 | -0.0253 | 0.0039 | False |
| stoch+rsi | EUR_CHF | long | limit | 122 | 0.0998 | -0.0556 | 0.0383 | False |
| stoch+rsi | EUR_CHF | long | mid | 416 | -0.0137 | -0.0941 | -0.0292 | False |
| stoch+rsi | EUR_CHF | short | limit | 117 | 0.0030 | -0.1536 | 0.0347 | False |
| stoch+rsi | EUR_CHF | short | mid | 401 | 0.0198 | -0.0647 | 0.0497 | False |
| stoch+rsi | EUR_GBP | long | limit | 139 | 0.2996 | 0.1555 | 0.2857 | True |
| stoch+rsi | EUR_GBP | long | mid | 448 | 0.1000 | 0.0175 | 0.1362 | False |
| stoch+rsi | EUR_GBP | short | limit | 139 | -0.0639 | -0.2184 | 0.0315 | False |
| stoch+rsi | EUR_GBP | short | mid | 452 | -0.0562 | -0.1417 | 0.0158 | False |
| stoch+rsi | EUR_NOK | long | limit | 137 | 0.0957 | -0.0687 | 0.1251 | False |
| stoch+rsi | EUR_NOK | long | mid | 455 | 0.0720 | -0.0171 | 0.0949 | False |
| stoch+rsi | EUR_NOK | short | limit | 140 | 0.0777 | -0.0840 | 0.0552 | False |
| stoch+rsi | EUR_NOK | short | mid | 421 | 0.0475 | -0.0456 | -0.0062 | False |
| stoch+rsi | EUR_USD | long | limit | 161 | 0.1747 | 0.0285 | 0.1457 | True |
| stoch+rsi | EUR_USD | long | mid | 498 | 0.0792 | -0.0050 | 0.0483 | False |
| stoch+rsi | EUR_USD | short | limit | 128 | 0.1027 | -0.0621 | 0.0357 | False |
| stoch+rsi | EUR_USD | short | mid | 445 | 0.1226 | 0.0337 | 0.0644 | True |
| stoch+rsi | GBP_CAD | long | limit | 121 | -0.0950 | -0.2647 | -0.0364 | False |
| stoch+rsi | GBP_CAD | long | mid | 434 | 0.0046 | -0.0869 | -0.0037 | False |
| stoch+rsi | GBP_CAD | short | limit | 115 | 0.0788 | -0.0952 | 0.0522 | False |
| stoch+rsi | GBP_CAD | short | mid | 414 | 0.0069 | -0.0852 | 0.0021 | False |
| stoch+rsi | NZD_CHF | long | limit | 113 | -0.1504 | -0.3335 | -0.0309 | False |
| stoch+rsi | NZD_CHF | long | mid | 418 | -0.0685 | -0.1632 | 0.0063 | False |
| stoch+rsi | NZD_CHF | short | limit | 108 | 0.2430 | 0.0596 | 0.2515 | False |
| stoch+rsi | NZD_CHF | short | mid | 353 | 0.1142 | 0.0116 | 0.1507 | False |
| stoch+rsi | NZD_JPY | long | limit | 125 | -0.1886 | -0.3608 | -0.0217 | False |
| stoch+rsi | NZD_JPY | long | mid | 414 | -0.0835 | -0.1795 | -0.0066 | False |
| stoch+rsi | NZD_JPY | short | limit | 120 | 0.0079 | -0.1711 | 0.0512 | False |
| stoch+rsi | NZD_JPY | short | mid | 472 | -0.0089 | -0.0989 | 0.0129 | False |
| stoch+rsi | NZD_USD | long | limit | 143 | -0.0769 | -0.2409 | 0.0380 | False |
| stoch+rsi | NZD_USD | long | mid | 452 | 0.0088 | -0.0834 | 0.0373 | False |
| stoch+rsi | NZD_USD | short | limit | 131 | -0.1145 | -0.2853 | 0.0510 | False |
| stoch+rsi | NZD_USD | short | mid | 452 | 0.0310 | -0.0613 | 0.0288 | False |
| stoch+rsi | USD_CAD | long | limit | 165 | -0.0117 | -0.1591 | 0.0654 | False |
| stoch+rsi | USD_CAD | long | mid | 510 | 0.0304 | -0.0524 | 0.0598 | False |
| stoch+rsi | USD_CAD | short | limit | 138 | 0.0656 | -0.0927 | 0.0837 | False |
| stoch+rsi | USD_CAD | short | mid | 473 | -0.0321 | -0.1177 | 0.0045 | False |
| stoch+rsi | USD_JPY | long | limit | 128 | 0.2480 | 0.0822 | 0.2147 | True |
| stoch+rsi | USD_JPY | long | mid | 383 | 0.1586 | 0.0619 | 0.1158 | True |
| stoch+rsi | USD_JPY | short | limit | 175 | -0.0558 | -0.1953 | -0.0456 | False |
| stoch+rsi | USD_JPY | short | mid | 567 | -0.1128 | -0.1909 | -0.0743 | False |
| stoch+rsi | USD_SGD | long | limit | 154 | 0.0365 | -0.0899 | 0.0431 | False |
| stoch+rsi | USD_SGD | long | mid | 467 | 0.0532 | -0.0196 | 0.0503 | False |
| stoch+rsi | USD_SGD | short | limit | 135 | 0.0945 | -0.0452 | 0.1012 | False |
| stoch+rsi | USD_SGD | short | mid | 432 | 0.0221 | -0.0572 | 0.0444 | False |

## Control Sanity

- stoch+rsi long limit: BOTH mean_R=0.0518, best component=0.0544, lift=-0.0026.
- stoch+rsi long mid: BOTH mean_R=0.0328, best component=0.0309, lift=0.0018.
- stoch+rsi short limit: BOTH mean_R=0.0327, best component=0.0202, lift=0.0125.
- stoch+rsi short mid: BOTH mean_R=0.0109, best component=0.0110, lift=-0.0002.

## Artifacts
- `p1a_results.csv`: one row per evaluator-pair/level/pair/direction/entry/cell.
- `p1a_sweep.out`: console summary from the sweep run.
