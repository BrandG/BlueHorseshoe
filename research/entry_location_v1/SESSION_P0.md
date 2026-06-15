# Entry-Location P0c — session, ATR-disentangled

Universe: `long_mr_strong4` long, mid entry, TP/SL 1%/1%, MAX_HOLD=84, deduped one entry per (pair, signal bar). Session = trigger-bar NY-clock label. NW L=83.

**Read:** (1) does any session's per-trade R clear its own NW bar / beat the rest? (2) does a session edge hold *inside* ATR buckets (orthogonal to vol)?

## mean R by ATR bucket x session

| bucket | asia (n) | london (n) | overlap (n) | ny (n) | closed (n) |
| --- | --- | --- | --- | --- | --- |
| low | +0.0642 (6,692) | +0.0442 (2,579) | +0.0566 (2,256) | +0.0519 (2,327) | +1.0000 (1) |
| mid | +0.0419 (5,183) | +0.0289 (2,199) | +0.0772 (2,420) | +0.0301 (2,021) | nan (0) |
| high | +0.0064 (6,152) | +0.0057 (2,549) | -0.0094 (3,219) | -0.0726 (2,558) | +1.0000 (2) |
| ALL | +0.0359 (18,364) | +0.0254 (7,440) | +0.0357 (8,042) | -0.0038 (7,025) | +1.0000 (3) |

## Pooled significance (Newey-West)

| session | n | mean_R | own_CI_low | diff_vs_rest | diff_CI_low |
| --- | --- | --- | --- | --- | --- |
| asia | 18,364 | +0.0359 | +0.0127 | +0.0158 | -0.0174 |
| london | 7,440 | +0.0254 | -0.0044 | -0.0022 | -0.0395 |
| overlap | 8,042 | +0.0357 | +0.0096 | +0.0106 | -0.0243 |
| ny | 7,025 | -0.0038 | -0.0329 | -0.0374 | -0.0743 |
| closed | 3 | +1.0000 | +1.0000 | +0.9729 | +0.9503 |

`own_CI_low` > 0 means the session is individually profitable past the NW bar; `diff_CI_low` > 0 means it NW-beats the other sessions. A real session lever needs the edge to also persist inside the low/mid/high rows above.

Artifacts: `session_p0_grid.csv`.
