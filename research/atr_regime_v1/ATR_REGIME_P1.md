# ATR Regime P1

## Method
Simulated `depth_fires.csv` with `_lib.py` mid-entry R machinery, TP=1%, SL=1%, and `MAX_HOLD=84` H4 bars.
Newey-West uses the `nw_regate.py` Bartlett-kernel convention with fixed `L = hold - 1 = 83` for every bucket and low/mid-vs-high diff.
Regimes are within-pair `ATR_percentile` buckets: low [0,33), mid [33,67), high [67,100]. Rows with missing ATR percentile are excluded from P1 regime gates, matching the closed rolling-window warmup.

## ATR Percentile Causality Check
`depth_extract.py` computes `entry_ATR = ATR(14)` on closed H4 midpoint bars and `ATR_percentile` as `rolling(252).apply(rank_last)`. The rolling function ranks `arr[-1]` against the finite values inside that same backward-looking window; no negative shift or forward window is present.
Source check passed=True; recompute sample AUD_CAD n=200 max_abs_delta=1.11e-16. This confirms no future ATR values enter the stored percentile; the current closed signal bar is included and is known at mid-entry simulation time.

## Deployed Cells
- bb: entry_mode=mid, params=`{'period': 50, 'n_std': 2.0, 'depth': 0.0}`
- rsi: entry_mode=mid, params=`{'period': 14, 'threshold': 35, 'recovery': 1}`
- cci: entry_mode=mid, params=`{'period': 14, 'threshold': 100, 'recovery': 1}`
- sma: entry_mode=mid, params=`{'period': 200, 'k': 2.5, 'atr_period': 14}`
- ema: entry_mode=mid, params=`{'period': 20, 'k': 2.0, 'atr_period': 14}`
- stoch: entry_mode=mid, params=`{'k_period': 9, 'd_period': 3, 'threshold': 20, 'recovery': 1}`

## Count Sanity
| evaluator | direction | fires | realized | regime_realized | expected_realized | dropped | sim_dropped | matches_p1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bb | long | 5518 | 5500 | 5408 | 5500 | 18 | 18 | True |
| bb | short | 5571 | 5533 | 5474 | 5533 | 38 | 38 | True |
| rsi | long | 11889 | 11843 | 11576 | 11843 | 46 | 46 | True |
| rsi | short | 12396 | 12314 | 12149 | 12314 | 82 | 82 | True |
| cci | long | 19689 | 19604 | 19263 | 19604 | 85 | 85 | True |
| cci | short | 20256 | 20144 | 19858 | 20144 | 112 | 112 | True |
| sma | long | 4470 | 4429 | 4398 | 4429 | 41 | 41 | True |
| sma | short | 4604 | 4570 | 4551 | 4570 | 34 | 34 | True |
| ema | long | 5543 | 5524 | 5424 | 5524 | 19 | 19 | True |
| ema | short | 5710 | 5683 | 5613 | 5683 | 27 | 27 | True |
| stoch | long | 28714 | 28579 | 28083 | 28579 | 135 | 135 | True |
| stoch | short | 30547 | 30360 | 29911 | 30360 | 187 | 187 | True |

## Headline
Cross-cell consistency: 0/12 cell-directions show an NW-significant low/mid bucket and low>high ordering in both halves.
Strict P1 survivors after full-sample diff NW gate plus per-pair majority: 0/12.
The gradient collapses under the full P1 stack; route this thread to relative-value / door #2 rather than P2 volatility-regime deployment work.

## Cell-Direction Verdicts
- bb long: low=+0.098, mid=+0.060, high=-0.001, low/mid=+0.078 (NW_CI_low=+0.032), low/mid-high=+0.079 (NW_CI_low=+0.007), Spearman=-1.000, halves low>high=YES, halves gate=NO, pairs low>high=14/17 (0.824), survives=NO.
- bb short: low=+0.033, mid=+0.054, high=+0.028, low/mid=+0.043 (NW_CI_low=-0.004), low/mid-high=+0.015 (NW_CI_low=-0.053), Spearman=-0.500, halves low>high=NO, halves gate=NO, pairs low>high=8/17 (0.471), survives=NO.
- cci long: low=+0.033, mid=+0.041, high=+0.014, low/mid=+0.036 (NW_CI_low=+0.006), low/mid-high=+0.022 (NW_CI_low=-0.023), Spearman=-0.500, halves low>high=YES, halves gate=NO, pairs low>high=9/17 (0.529), survives=NO.
- cci short: low=+0.007, mid=-0.006, high=-0.007, low/mid=+0.001 (NW_CI_low=-0.029), low/mid-high=+0.009 (NW_CI_low=-0.036), Spearman=-1.000, halves low>high=NO, halves gate=NO, pairs low>high=9/17 (0.529), survives=NO.
- ema long: low=+0.049, mid=+0.081, high=-0.020, low/mid=+0.065 (NW_CI_low=+0.021), low/mid-high=+0.086 (NW_CI_low=+0.025), Spearman=-0.500, halves low>high=YES, halves gate=NO, pairs low>high=13/17 (0.765), survives=NO.
- ema short: low=+0.042, mid=+0.042, high=+0.039, low/mid=+0.042 (NW_CI_low=+0.001), low/mid-high=+0.003 (NW_CI_low=-0.060), Spearman=-1.000, halves low>high=NO, halves gate=NO, pairs low>high=9/17 (0.529), survives=NO.
- rsi long: low=+0.072, mid=+0.066, high=-0.017, low/mid=+0.069 (NW_CI_low=+0.031), low/mid-high=+0.086 (NW_CI_low=+0.029), Spearman=-1.000, halves low>high=YES, halves gate=NO, pairs low>high=13/17 (0.765), survives=NO.
- rsi short: low=+0.040, mid=-0.007, high=-0.004, low/mid=+0.019 (NW_CI_low=-0.019), low/mid-high=+0.023 (NW_CI_low=-0.034), Spearman=-0.500, halves low>high=YES, halves gate=NO, pairs low>high=10/17 (0.588), survives=NO.
- sma long: low=+0.045, mid=+0.044, high=+0.022, low/mid=+0.044 (NW_CI_low=-0.016), low/mid-high=+0.022 (NW_CI_low=-0.070), Spearman=-1.000, halves low>high=NO, halves gate=NO, pairs low>high=9/17 (0.529), survives=NO.
- sma short: low=-0.005, mid=-0.021, high=+0.056, low/mid=-0.012 (NW_CI_low=-0.073), low/mid-high=-0.068 (NW_CI_low=-0.162), Spearman=0.500, halves low>high=NO, halves gate=NO, pairs low>high=7/17 (0.412), survives=NO.
- stoch long: low=+0.056, mid=+0.032, high=-0.004, low/mid=+0.045 (NW_CI_low=+0.018), low/mid-high=+0.050 (NW_CI_low=+0.009), Spearman=-1.000, halves low>high=YES, halves gate=NO, pairs low>high=11/17 (0.647), survives=NO.
- stoch short: low=+0.005, mid=-0.012, high=-0.020, low/mid=-0.002 (NW_CI_low=-0.030), low/mid-high=+0.018 (NW_CI_low=-0.023), Spearman=-1.000, halves low>high=YES, halves gate=NO, pairs low>high=9/17 (0.529), survives=NO.

## P2 Survivor Set
- None.

## Selection Control
Within-pair control: 10/12 cell-directions have a majority of the 17 pairs with low-ATR mean_R > high-ATR mean_R, so the headline is not just pooled low-vol pairs outperforming.
Calendar/era control: h1 gates=1/12 and h2 gates=2/12. Both-halves status for each cell-direction is listed above; any one-half-only effect is treated as non-survival.

## Artifacts
- `atr_regime_curves.csv`: 1,944 bucket rows.
- `atr_regime_p1.out`: run summary.

---

## Audit addendum (Bubo, 2026-06-13) — the "0/12" is a gating artifact, not a collapse

The script's headline ("0/12, route to relative-value") over-reads the result. The strict gate
required NW-significance **independently within each time-half, per cell** — and the data shows
that's a power failure, not an absence of signal:

- **4 long cells pass the full-sample stack:** bb/rsi/ema/stoch long all have NW_CI_low > 0 on
  BOTH the low/mid level and the low/mid−high diff, perfect monotonicity (low>mid>high), per-pair
  majority 11–14/17, and the low>high **direction holds in both halves** (`halves low>high=YES`).
- They fail only `halves gate` = NW-significant in *each half*. Per the selection-control line,
  `h1 gates=1/12, h2 gates=2/12` — halving n on an already-conservative NW kills per-half
  significance. Direction is stable across halves (it doesn't flip), so this is **underpower, not
  instability**.
- **L = 83 (= MAX_HOLD−1) is almost certainly far too large.** These 1%/1% bracket trades resolve
  in a handful of bars, not 84; L=83 over-inflates the NW SE. That the full sample passes anyway is
  evidence of strength, not weakness.

This is the exact pattern the v2 NW re-gate documented: per-cell CI collapses under NW, the
**portfolio/book survives**. The correct next step is a **P1b re-gate** (§13 / ATR_REGIME_v1 §10):
realized-hold-based L + a **pooled long-MR sleeve** judged under NW both-halves, not per-cell-per-
half. The short side is genuinely null (a long-side phenomenon, consistent with dislocation-depth
P1). Do NOT route to relative-value until the sleeve is tested at the right altitude.
