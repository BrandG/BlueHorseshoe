# Entry-Location P2 — high-ATR ∩ NY recent-holdout gate

Holdout = 2024-06-15 .. now (last 24 months); train = before. Strong-4 long-MR, mid entry, 1%/1%, MAX_HOLD=84. NW Bartlett L=83.

**Gate (high∩NY negative in BOTH train & holdout): PASS.**
Corollary (rest of high-ATR not a loser in either, so blunt rule over-cuts): holds.

| cell | split | n | mean_R | NW_CI_low | NW_CI_high | total_R |
| --- | --- | --- | --- | --- | --- | --- |
| high ∩ NY | full | 2,558 | -0.0726 | -0.1263 | -0.0189 | -185.7 |
| high ∩ NY | train | 2,099 | -0.0697 | -0.1257 | -0.0136 | -146.2 |
| high ∩ NY | holdout | 459 | -0.0861 | -0.2493 | +0.0770 | -39.5 |
| high ∩ not-NY | full | 11,922 | +0.0021 | -0.0399 | +0.0441 | +25.4 |
| high ∩ not-NY | train | 9,621 | +0.0000 | -0.0446 | +0.0447 | +0.3 |
| high ∩ not-NY | holdout | 2,301 | +0.0109 | -0.1013 | +0.1230 | +25.0 |
| high (all) | full | 14,480 | -0.0111 | -0.0523 | +0.0301 | -160.4 |
| high (all) | train | 11,720 | -0.0124 | -0.0564 | +0.0315 | -145.9 |
| high (all) | holdout | 2,760 | -0.0053 | -0.1143 | +0.1038 | -14.5 |

high∩NY: train -0.0697 (n=2,099), holdout -0.0861 (n=459).
rest of high-ATR: train +0.0000, holdout +0.0109.

Artifacts: `holdout_high_ny_p2.csv`.
