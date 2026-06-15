# Entry-Location P1 — high-ATR loss-corner robustness

Strong-4 long-MR, mid entry, 1%/1%, MAX_HOLD=84. NW Bartlett L=83. Halves = chronological median split of all fires. `sig_neg` = NW 95% upper bound < 0 (significantly money-losing); `sig_pos` = NW 95% lower bound > 0.

Book total R: +1112.1  |  high-ATR total R: -160.4  (-14% of book) over 14,480 high-ATR trades.

## Sub-cell stats within the high-ATR bucket

| sub-cell | n | mean_R | NW_CI_low | NW_CI_high | sig_neg | h1 mean (n) | h2 mean (n) | sign-stable |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| high (all) | 14,480 | -0.0111 | -0.0523 | +0.0301 | · | -0.0144 (6,815) | -0.0081 (7,665) | YES |
| high ∩ NY | 2,558 | -0.0726 | -0.1263 | -0.0189 | YES | -0.0702 (1,169) | -0.0746 (1,389) | YES |
| high ∩ not-NY | 11,922 | +0.0021 | -0.0399 | +0.0441 | · | -0.0028 (5,646) | +0.0066 (6,276) | no |
| high ∩ counter | 11,232 | -0.0166 | -0.0616 | +0.0285 | · | -0.0209 (5,258) | -0.0127 (5,974) | YES |
| high ∩ with-trend | 3,238 | +0.0087 | -0.0433 | +0.0607 | · | +0.0083 (1,550) | +0.0090 (1,688) | YES |
| high ∩ NY ∩ counter | 2,334 | -0.0777 | -0.1300 | -0.0254 | YES | -0.0704 (1,064) | -0.0838 (1,270) | YES |
| CUT set: high ∩ (NY or counter) | 11,456 | -0.0166 | -0.0614 | +0.0282 | · | -0.0218 (5,363) | -0.0120 (6,093) | YES |
| KEEP set: high ∩ (not-NY & not-counter) | 3,024 | +0.0100 | -0.0425 | +0.0624 | · | +0.0131 (1,452) | +0.0071 (1,572) | YES |

## Blunt vs surgical (the deployment question)

- High-ATR total R = -160.4. The blunt `size_down_high_0_5` halves ALL of it.
- CUT set (high ∩ NY-or-counter): n=11,456, total R = -190.5.
- KEEP set (high ∩ neither): n=3,024, total R = +30.1.

If the KEEP set is solidly positive and the CUT set holds the loss in both halves, a surgical size-down (cut the corner, keep full size on the rest) dominates the blunt rule: same DD reduction, less throughput sacrificed.

Artifacts: `high_atr_subcell_p1.csv`.
