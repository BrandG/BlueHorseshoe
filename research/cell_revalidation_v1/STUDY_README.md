# cell_revalidation_v1 — per-cell adjudication of the mid-entry quarantine

**Question.** The 2026-06-17 live pause (`QUARANTINED_STRATEGIES`) benched six *strategies*
as a class (stoch, bb, sma, ema, rsi, cci). The live tape says stoch is the bleeder
(−3.5R / 5 trades) while rsi/cci/bb were winners — i.e. the class-level pause threw out
profitable selectors to kill one loser. This study re-adjudicates **each cell individually**
on the full H4 history so the quarantine can be flipped from per-class to per-cell.

**This is a research surface, not a deploy.** It writes nothing into the live path. The
production flip (per-cell `QUARANTINED_STRATEGIES`) is a separate, reviewed step.

## Harness (per `research/README.md`)

- **Bracketed R, worst = −1R.** `bracket_trade` from `_lib/harness.py`. Geometry is read
  straight from the live `compute_entry_stop_target` (so long-MR cells inherit 1.5%/1%/10d,
  everything else 1%/1%/14d). `target_R = |target−entry| / |entry−stop|`.
- **Live-faithful fills.** Signal + bracket levels on **mid** (bid+ask)/2, exactly as the
  live trader computes them. Mid cells fill at trigger-bar close; limit cells rest at the
  trigger-bar low/high for the next bar only (GTD), filled only if that bar trades through.
- **Costs (CLEANED).** Spread is taken from the data itself (`close_ask − close_bid` at
  entry); `R_net = R_raw − spread/stop_dist`. RAW and CLEANED reported side-by-side with a
  DELTA so the spread drag is visible.
- **Keep ALL firings** (no de-overlap). Newey-West SE with **L = hold−1** (in bars) plus
  symbol-clustered SE. Conservative SE for the gate = `max(nw_se, clustered_se)`.
- **Splits.** In-sample = before the last 24 months; recent **holdout** = last 24 months.
  In-sample split into interleaved **A/B** by calendar-quarter parity.
- **Matched-random canary** per (pair, side, geometry): same bracket machinery, random
  entries. Must read ~0.000R; if not, the machinery is non-neutral — don't trust the cell.

## Verdict (BUD bar: makes money after costs, A ∧ B ∧ holdout)

A cell **RESTORE**s only if, on `R_net`:
`mean_R > 0` in the full sample AND in A AND in B AND in holdout, AND
`mean_R − 1.96·max(nw_se, clustered_se) > 0` (expectancy-CI gate).
Otherwise **HOLD** (stays quarantined). Thin cells (n below `--min-n`) are reported as
INSUFFICIENT, never auto-restored.

## Run

```bash
./run.sh python research/cell_revalidation_v1/run.py            # full history, all quarantined cells
./run.sh python research/cell_revalidation_v1/run.py --smoke    # last 2500 bars, fast wiring check
./run.sh python research/cell_revalidation_v1/run.py --include-active   # + atr/macd/ichimoku control
```

Outputs a printed table and `scorecard.csv` in this directory.
