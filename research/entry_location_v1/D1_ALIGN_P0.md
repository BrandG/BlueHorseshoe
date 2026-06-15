# Entry-Location P0b — D1-alignment, ATR-disentangled

Universe: `long_mr_strong4` (bb, rsi, ema, stoch) long, mid entry, TP/SL 1%/1%, MAX_HOLD=84, deduped one entry per (pair, signal bar). D1 alignment uses the PIT-live definition (day-open vs trigger-bar close). NW SE: Bartlett L=83.

**Read:** (1) is with-trend > counter-trend for these MR longs, and NW-significant? (2) does the with-trend lift survive *inside* each ATR bucket — i.e. is D1 a separate axis from volatility, unlike entry-distance?

## mean R by ATR bucket x D1 alignment

| bucket | with-trend (n) | flat (n) | counter-trend (n) | wt−ct | NW_SE | NW_CI_low |
| --- | --- | --- | --- | --- | --- | --- |
| low | +0.0623 (3,072) | -0.0061 (17) | +0.0559 (10,766) | +0.0064 | +0.0293 | -0.0510 |
| mid | +0.0546 (2,564) | +0.1103 (11) | +0.0418 (9,248) | +0.0128 | +0.0268 | -0.0397 |
| high | +0.0087 (3,238) | -0.2450 (10) | -0.0166 (11,232) | +0.0252 | +0.0299 | -0.0333 |
| ALL | +0.0372 (9,045) | -0.0353 (38) | +0.0244 (31,791) | +0.0128 | +0.0174 | -0.0214 |

`wt−ct` > 0 means with-trend beats counter-trend; NW_CI_low > 0 means the gap clears the Newey-West 95% bar. If the gap holds inside low/mid/high (not just ALL), D1 is orthogonal to the ATR axis and is a real second entry-location lever.

Artifacts: `d1_align_p0_grid.csv`.
