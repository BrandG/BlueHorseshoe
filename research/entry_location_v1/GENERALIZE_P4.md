# Entry-Location P4 — does high∩NY skip generalize?

Per-trade R, mid entry, 1%/1%, MAX_HOLD=84, deduped per (pair, bar) within sleeve+direction. `sig_neg` = NW 95% upper bound < 0. `recovered_R` = R gained by skipping high∩NY = +(its losses). Trend families (macd/atr/ichimoku/candle) absent from the fire set → not tested.

| group | book n | book R | high∩NY n | high∩NY mean_R | NW_CI_high | sig_neg | recovered R | % of book | pairs neg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| strong4 long | 40,874 | +1112.1 | 2,558 | -0.0726 | -0.0353 | YES | +185.7 | +16.7% | 15/17 |
| full6 long | 52,868 | +1707.9 | 3,337 | -0.0371 | +0.0022 | · | +124.0 | +7.3% | 12/17 |
| strong4 short | 42,776 | +167.6 | 2,317 | -0.0034 | +0.0387 | · | +7.8 | +4.7% | 8/17 |
| full6 short | 55,143 | +180.0 | 3,130 | -0.0125 | +0.0260 | · | +39.0 | +21.7% | 11/17 |

Reading: a group generalizes the rule if high∩NY mean_R < 0 (ideally sig_neg), the recovered R is a meaningful share of its book, and the loss is broad across pairs. A group where the whole book R is itself negative is a different problem (the sleeve doesn't make money) — the skip can't rescue it.

Artifacts: `generalize_p4.csv`.
