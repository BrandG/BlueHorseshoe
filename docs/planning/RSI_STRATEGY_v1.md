# BH FTMO — RSI Strategy v1 (Phase 0+1+2 Complete)

**Status:** Validated. Production cells expanded under v2 methodology 2026-05-03: 2 pairs → 3 pairs (added USD_JPY long).

**Date locked:** 2026-05-03 (v1 + v2 update same day)

---

## v2 Production Cells (2026-05-03) — supersedes v1 below

Re-run under v2 methodology: per-trade R tracking + expectancy CI gate. USD_JPY long now passes (was killed in v1 by Wilson-CI margin at spread).

**3 production pairs** (was 2 in v1):

| Pair    | RSI period | Threshold | Recovery | Direction | Test n | Test mean R |
|---------|------------|-----------|----------|-----------|--------|-------------|
| CHF_JPY | 14         | 35        | 1        | long      | 170    | +0.226      |
| EUR_GBP | 21         | 35        | 1        | long      | 118    | +0.226      |
| USD_JPY | 7          | 35        | 1        | long      | 357    | +0.134      |

### Portfolio test stats (v2, 644 trades)

WR 59.4% / mean_R +0.178 / cum_R +114.9 / max_DD -38.0R / max_simul 15.

### Changes from v1
- **Gained:** USD_JPY long (now 4-indicator confirmation: BB, Stoch, RSI, CCI)
- **Retained:** EUR_GBP long, CHF_JPY long.
- CHF_JPY cell shifted from p=7 to p=14, EUR_GBP from p=7 to p=21 under v2 selection.

The "RSI surfaces zero new pairs" finding from v1 is **partially overturned** — RSI still uses pairs already covered by other indicators, but USD_JPY now has 4-indicator confirmation (the highest of any pair tied with CHF_JPY).

### Reproducibility (v2)
- `research/_v2_rerun/run_rsi_v2.py` — full pipeline
- `research/_v2_rerun/rsi/walkforward.csv`, `walkforward_spread.csv`, `portfolio_trades.csv`

---

## v1 Original (2026-05-03)

## Strategy Spec

Two-pair RSI fresh-recovery-from-oversold trigger strategy at H4 timeframe, fixed 1.0% take-profit / 1.0% stop, real OANDA bid/ask spread. One production cell per pair.

| Pair    | RSI period | Threshold | Recovery | Direction | Test n | Test WR | Test 95% CI    |
|---------|------------|-----------|----------|-----------|--------|---------|----------------|
| EUR_GBP | 7          | 35        | 1        | long      | 419    | 57.2%   | [51.1, 63.3]   |
| CHF_JPY | 7          | 30        | 1        | long      | 242    | 60.9%   | [54.6, 67.2]   |

### Trigger logic

- **RSI(period)** is Wilder's-smoothed RSI on mid-OHLC close, range [0, 100].
- **Long fresh trigger:** RSI rose for `recovery` consecutive bars AND RSI at the start of the run was below `threshold`. Concretely: `RSI[i] > RSI[i-1] > ... > RSI[i-recovery]` AND `RSI[i-recovery] < threshold`. Fires only on the bar where the condition first becomes true.
- **Short fresh trigger:** mirror — RSI fell for `recovery` consecutive bars AND RSI at the start was above `100 - threshold`. (No short cells survived.)
- Both production cells use **`recovery=1`** (single up-bar from oversold) due to the largest-`te_n` selection rule.

### Confirmation rules

None. Entry is at the trigger bar's close.

### Exit logic

- **Long:** TP at `entry × 1.01` (checked against `high_bid`). Stop at `entry × 0.99` (checked against `low_bid`, evaluated stop-first per bar). Timeout exit at `close_bid` after 84 H4 bars (2 weeks).
- **Long entry fill:** `close_ask` at the trigger bar.

### Sizing convention

R is unitless: +1.0 on TP, -1.0 on stop, fractional on timeout.

## Portfolio Performance (Test Half: 2023-02-14 → 2026-04-08)

| Metric                          | Train (1,539 trades) | Test (660 trades)   | Full (2,199 trades) |
|---------------------------------|----------------------|---------------------|---------------------|
| Decisive WR                     | 54.6%                | **59.2%**           | 55.8%               |
| Decisive WR 95% CI              | [51.9, 57.2]         | [54.7, 63.6]        | [53.5, 58.0]        |
| Avg R per trade                 | +0.082               | **+0.132**          | +0.097              |
| Cumulative R                    | +126                 | +87                 | +213                |
| Max drawdown (R)                | -44                  | -39                 | -44                 |
| Max consecutive losses          | 20                   | 12                  | 20                  |
| Max simultaneous open positions | 18                   | 18                  | 18                  |

**Key observation:** Test outperforms train as in prior v1s (+4.6pp WR, +0.05 R/trade). The deepest drawdown of any v1 strategy so far (-44 R), driven by RSI's high trade volume (1,395 EUR_GBP + 804 CHF_JPY = 2,199 over 10 years, more than any other v1).

### Per-pair contribution (test half)

| Pair    | n    | W/L/T          | WR    | Cum R |
|---------|------|----------------|-------|-------|
| CHF_JPY | 219  | 126/81/12      | 60.9% | +45   |
| EUR_GBP | 441  | 155/113/173    | 57.8% | +42   |

### Cross-pair monthly R correlation (test half)

|         | CHF_JPY | EUR_GBP |
|---------|---------|---------|
| CHF_JPY |  1.00   | -0.04   |
| EUR_GBP | -0.04   |  1.00   |

EUR_GBP and CHF_JPY are essentially uncorrelated at the monthly R level — a clean two-pair pairing.

## Cross-indicator overlap with prior v1 specs

| Pair    | BB v1 | Stoch v1 | SMA v1 | RSI v1 |
|---------|-------|----------|--------|--------|
| EUR_GBP | —     | long ✅   | long ✅ | long ✅ |
| CHF_JPY | long ✅| long ✅   | —      | long ✅ |

**Both RSI v1 production pairs already exist in other v1 production specs in matching directions.** RSI surfaces ZERO new pairs — it is purely a confirmation indicator.

This is the lesson of running a fourth oscillator-shaped indicator: same pair set, same direction, different parameters. Diminishing returns on the "new pair" axis.

## Role in the FTMO portfolio

Per the `feedback_signal_role_by_solo_edge.md` rule, RSI has solid solo edge so it counts as a standalone strategy. But its production pair set is a strict subset of the union of BB/Stoch/SMA. So RSI's role in the eventual multi-indicator portfolio is one of:

1. **Add as another lane** alongside BB/Stoch/SMA on the same pairs — increases trade volume and lets the same pair fire from multiple angles. Requires position-deduplication logic at portfolio assembly.
2. **Use as confirmation filter on existing v1 strategies** — only take BB/Stoch/SMA entries when RSI is also in fresh-recovery state. Fewer trades, presumably higher quality.
3. **Skip** — its information is already substantially captured by Stoch v1 (the closest oscillator analogue).

The role decision is best made in the cross-indicator portfolio walk-forward phase, not now.

## Notable null results

- **No short cells survived** — even AUD_CAD short (which surfaced in mid-only walk-forward) flipped sign at spread.
- **USD_JPY long** — surfaced in mid walk-forward (te WR 57.4%) but spread killed the train CI lower bound. Notable because USD_JPY is a Stoch v1 production pair.
- **Exotic pairs** (HUF, NOK, ZAR) all died at spread, same lesson as prior v1s.

## High-edge alternatives (NOT selected)

Per pair, multiple cells survived. Selection rule = largest test n. Per-pair alternatives if FTMO sizing prefers per-trade quality:

- **EUR_GBP** `p=28 thr=35 rec=1 long`: te WR **80.6%** (n=64, vs selected 57.2% at n=419)
- **EUR_GBP** `p=21 thr=35 rec=1 long`: te WR **70.7%** (n=118)
- **CHF_JPY** `p=7 thr=30 rec=2 long`: te WR **67.3%** (n=115, vs selected 60.9% at n=242)

The pattern across both pairs is clear: longer RSI period + higher threshold + higher recovery → fewer but higher-quality trades.

## Methodology footnote — recovery=2 outperforms recovery=1 within CHF_JPY

CHF_JPY has both rec=1 and rec=2 survivors at multiple periods. Within each `(period, threshold)` group, rec=2 has 5-7pp higher WR but ~½ the trade volume — the same shape as the BB / Stoch / SMA "deeper extension = higher per-trade quality" pattern.

## Reproducibility

Scripts at `research/rsi_phase0_v1/`:
- `sweep_rsi_triggers.py` — Phase 0 trigger sweep (5,120 cells)
- `walkforward_rsi_triggers.py` — mid 70/30 walk-forward
- `walkforward_rsi_spread.py` — spread-aware 70/30 walk-forward (production cell source)
- `portfolio_rsi_walkforward.py` — portfolio assembly + per-pair contribution

CSVs at `research/rsi_phase0_v1/`:
- `rsi_triggers.csv` — Phase 0 output
- `walkforward_rsi_triggers.csv` — mid walk-forward
- `walkforward_rsi_spread.csv` — spread walk-forward
