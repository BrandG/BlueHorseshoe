# Entry-Location P3 — per-trade payoff + per-pair concentration of high∩NY

Strong-4 long-MR, mid entry, 1%/1%, MAX_HOLD=84. Pure per-trade R; no account framing.

## Payoff of skipping high∩NY

- Book total R (take everything): **+1112.1**
- high∩NY total R (the corner): **-185.7** over 2,558 trades
- Book total R if high∩NY skipped: **+1297.9**  (recovers +185.7 R, +17% of book)

## Per-pair concentration of the high∩NY loss

- 17 pairs fire in this corner; 15/17 have negative total R, 15/17 have negative mean R.
- Worst single pair = AUD_JPY (-31.0 R, 17% of the corner loss).
- Worst 3 pairs = 44% of the corner loss.

| pair | n | mean_R | total_R |
| --- | --- | --- | --- |
| AUD_JPY | 167 | -0.1856 | -31.0 |
| CAD_CHF | 156 | -0.1842 | -28.7 |
| NZD_JPY | 154 | -0.1429 | -22.0 |
| USD_SGD | 145 | -0.1437 | -20.8 |
| EUR_USD | 158 | -0.1055 | -16.7 |
| GBP_CAD | 164 | -0.0905 | -14.8 |
| NZD_USD | 145 | -0.0920 | -13.3 |
| EUR_CHF | 157 | -0.0825 | -12.9 |
| EUR_CAD | 179 | -0.0587 | -10.5 |
| NZD_CHF | 151 | -0.0692 | -10.4 |
| AUD_CAD | 134 | -0.0656 | -8.8 |
| EUR_GBP | 123 | -0.0332 | -4.1 |
| CAD_JPY | 165 | -0.0113 | -1.9 |
| EUR_NOK | 111 | -0.0066 | -0.7 |
| USD_JPY | 142 | -0.0010 | -0.1 |
| CHF_JPY | 138 | +0.0374 | +5.2 |
| USD_CAD | 169 | +0.0357 | +6.0 |

**Concentration verdict:** BROAD — most pairs lose in this corner and no single pair dominates; the corner is a real cross-book property.

Artifacts: `recover_and_pairs_p3.csv`.
