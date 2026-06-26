# exit_geometry_v2 — per-family TP/SL/hold sweep for Bud's deployed cells

## Question
`exit_geometry_v1` tuned only the long-MR bucket (bb/rsi/ema long mid → 1.5%/1%/10d). Every
other deployed family still runs the untuned uniform **1%/1%/14d**. Does per-family TP/SL/hold
beat that uniform default, validated out-of-sample?

## Harness
- Reuses the fidelity-checked fire detection in `research/_lib/fx_replay.py` (vectorised for the
  mid strategies, live `evaluate_cell` fallback for atr/macd/ichimoku). Fire events are cached
  (`.cache/`) so the slow detection runs once.
- Bracketed R, spread charged as `spread/stop_dist` (penalises very tight stops). Unit = R; Bud
  sizes to fixed risk per trade, so 1R = constant dollars and `auto_trader.compute_units` sizes
  off the *actual* stop distance — tightening the stop keeps dollar-risk constant.
- Split: in-sample = before the last 24 months; **holdout** = last 24 months; in-sample → A/B by
  calendar-quarter parity.
- **Selection bias guard:** grid argmax is chosen on in-sample, but a change is only recommended
  if it ALSO clears the holdout. Plus a **matched-random-per-geometry control**: each candidate
  must beat random entries under the *same* geometry (nets out pair drift — the v1 canary lesson).
  Plus a throughput floor (mean R / holding-day must not materially drop).

## Findings
1. **Naive grid** wanted wide-TP / tight-SL / long-hold almost everywhere — a drift + tail-luck +
   selection artifact. The matched-random control flipped the worst offender: `atr:short` 2/1/21
   "improved" 0.192→0.332 purely by riding NZD_CHF's −16% holdout slide (edge-over-random went
   **negative**), and the +0.000/+0.007 noise picks were dropped.
2. **A blanket 0.75% stop is NOT globally safe.** It helps mean-reversion entries (bb, cci, macd)
   and *hurts* breakout/momentum entries (atr, sma, ichimoku) which need room — tested directly
   via `--candidate-sl 0.0075`.
3. **Robust, cross-direction-confirmed result → SHIP:** tightening the stop **1.0% → 0.75% for bb
   and macd** improves holdout mean R in BOTH directions of each strategy (two semi-independent
   confirmations), beats random-same-geometry, and holds throughput:
   - bb:long 0.305→0.375 (edge +0.094), bb:short 0.087→0.124 (edge +0.150)
   - macd:long 0.283→0.333 (edge +0.050), macd:short 0.324→0.393 (edge +0.066)
   `cci:long` and `ema:short` also pass but are single-direction (weaker). `atr:long` separately
   wants a wider *target* (2%), not a tighter stop — a different knob, deferred.

## Decision (2026-06-26)
Deploy **bb + macd → 0.75% stop** only (TP and hold unchanged). cci/ema/atr left at baseline.

## Run
```bash
./run.sh python research/exit_geometry_v2/run.py            # full grid sweep (caches fires)
./run.sh python research/exit_geometry_v2/run.py --candidate-sl 0.0075   # single-knob SL test
./run.sh python research/exit_geometry_v2/run.py --smoke    # wiring check
```
Outputs `sweep.csv` + a per-bucket table with the matched-random edge and verdict.
