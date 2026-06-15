# Entry-Location P0 — entry-distance vs ATR-regime disentangle

Universe: `long_mr_strong4` (bb, rsi, ema, stoch) long fires, deduped to one entry per (pair, signal bar). TP/SL 1%/1%, MAX_HOLD=84. k=0 is the current Bud mid rule; k>0 is a limit at `close - k*ATR(14)` valid `window` H4 bars.

**The disentangling read:** if the k-gradient in the `ALL` row also appears *inside each ATR bucket row*, entry-distance is a real, separate lever. If the k-gradient flattens once you hold the bucket fixed, entry-distance was the ATR-regime effect re-expressed (note §3.2 collapses into §3.1).

## window = 1 H4 bar(s)  (Bud-faithful next-bar limit)

### mean R on fills

| bucket | k=0.00 | k=0.10 | k=0.25 | k=0.50 | k=0.75 | k=1.00 |
| --- | --- | --- | --- | --- | --- | --- |
| low | +0.0571 | +0.0614 | +0.0664 | +0.0766 | +0.0578 | +0.0587 |
| mid | +0.0447 | +0.0387 | +0.0493 | +0.0483 | +0.0403 | +0.0162 |
| high | -0.0111 | -0.0148 | -0.0066 | -0.0074 | -0.0163 | -0.0303 |
| ALL | +0.0272 | +0.0259 | +0.0337 | +0.0361 | +0.0263 | +0.0124 |

### fill rate

| bucket | k=0.00 | k=0.10 | k=0.25 | k=0.50 | k=0.75 | k=1.00 |
| --- | --- | --- | --- | --- | --- | --- |
| low | 0.996 | 0.878 | 0.679 | 0.405 | 0.234 | 0.139 |
| mid | 0.996 | 0.863 | 0.658 | 0.378 | 0.214 | 0.123 |
| high | 0.995 | 0.860 | 0.654 | 0.376 | 0.216 | 0.124 |
| ALL | 0.996 | 0.867 | 0.664 | 0.386 | 0.222 | 0.129 |

### mean R per fire (non-fills counted as 0 — opportunity-cost view)

| bucket | k=0.00 | k=0.10 | k=0.25 | k=0.50 | k=0.75 | k=1.00 |
| --- | --- | --- | --- | --- | --- | --- |
| low | +0.0569 | +0.0540 | +0.0451 | +0.0310 | +0.0135 | +0.0081 |
| mid | +0.0445 | +0.0334 | +0.0324 | +0.0182 | +0.0086 | +0.0020 |
| high | -0.0110 | -0.0127 | -0.0043 | -0.0028 | -0.0035 | -0.0038 |
| ALL | +0.0270 | +0.0224 | +0.0224 | +0.0139 | +0.0058 | +0.0016 |

## window = 6 H4 bar(s)  (contrarian DAY-tif analog)

### mean R on fills

| bucket | k=0.00 | k=0.10 | k=0.25 | k=0.50 | k=0.75 | k=1.00 |
| --- | --- | --- | --- | --- | --- | --- |
| low | +0.0571 | +0.0610 | +0.0643 | +0.0669 | +0.0608 | +0.0505 |
| mid | +0.0447 | +0.0418 | +0.0478 | +0.0445 | +0.0517 | +0.0582 |
| high | -0.0111 | -0.0110 | -0.0043 | -0.0163 | -0.0121 | -0.0183 |
| ALL | +0.0272 | +0.0277 | +0.0328 | +0.0283 | +0.0302 | +0.0262 |

### fill rate

| bucket | k=0.00 | k=0.10 | k=0.25 | k=0.50 | k=0.75 | k=1.00 |
| --- | --- | --- | --- | --- | --- | --- |
| low | 0.996 | 0.951 | 0.878 | 0.752 | 0.632 | 0.521 |
| mid | 0.996 | 0.945 | 0.868 | 0.733 | 0.613 | 0.503 |
| high | 0.995 | 0.946 | 0.870 | 0.730 | 0.604 | 0.490 |
| ALL | 0.996 | 0.947 | 0.872 | 0.738 | 0.616 | 0.505 |

### mean R per fire (non-fills counted as 0 — opportunity-cost view)

| bucket | k=0.00 | k=0.10 | k=0.25 | k=0.50 | k=0.75 | k=1.00 |
| --- | --- | --- | --- | --- | --- | --- |
| low | +0.0569 | +0.0580 | +0.0564 | +0.0503 | +0.0384 | +0.0263 |
| mid | +0.0445 | +0.0394 | +0.0415 | +0.0326 | +0.0317 | +0.0293 |
| high | -0.0110 | -0.0104 | -0.0037 | -0.0119 | -0.0073 | -0.0090 |
| ALL | +0.0270 | +0.0262 | +0.0286 | +0.0209 | +0.0186 | +0.0132 |

## Caveat
Mid-OHLC touch over-counts limit fills vs executable bid/ask (~37%). Fill rates are optimistic; the within-bucket k-gradient is the robust signal.

Artifacts: `disentangle_p0_grid.csv`.
