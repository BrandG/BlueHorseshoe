# BH FTMO — CCI Strategy v1 (Phase 0+1+2 Complete)

**Status:** Validated. Production cells re-aligned under v2 methodology 2026-05-03: 5 pairs (lost EUR_GBP long, gained CAD_CHF short).

**Date locked:** 2026-05-03 (v1 + v2 update same day)

---

## v2 Production Cells (2026-05-03) — supersedes v1 below

Re-run under v2 methodology: per-trade R tracking + expectancy CI gate. EUR_GBP long fell out (still in 3 other indicators); CAD_CHF short newly passes (now confirmed in BB + Stoch + CCI).

**5 production pairs** (was 5 in v1, but different mix):

| Pair    | CCI period | Threshold | Recovery | Direction | Test n | Test mean R |
|---------|------------|-----------|----------|-----------|--------|-------------|
| CAD_CHF | 14         | 100       | 1        | short     | 335    | +0.116      |
| CHF_JPY | 40         | 100       | 1        | long      | 245    | +0.165      |
| EUR_USD | 30         | 100       | 1        | short     | 274    | +0.123      |
| USD_CAD | 40         | 150       | 1        | long      | 133    | +0.204      |
| USD_JPY | 40         | 100       | 2        | long      | 179    | +0.159      |

### Portfolio test stats (v2, 1165 trades)

WR 57.8% / mean_R +0.149 / cum_R +173.8 / max_DD -27.2R / max_simul 22.

### Changes from v1
- **Lost: EUR_GBP long** (still in Stoch + SMA + RSI — 3-indicator coverage retained)
- **Gained: CAD_CHF short** (now in BB + Stoch + CCI — 3-indicator confirmation)
- **Retained:** CHF_JPY long, EUR_USD short, USD_CAD long, USD_JPY long.
- CHF_JPY recovery shifted 3 → 1, EUR_GBP cell selection changed.

### Reproducibility (v2)
- `research/_v2_rerun/run_cci_v2.py` — full pipeline
- `research/_v2_rerun/cci/walkforward.csv`, `walkforward_spread.csv`, `portfolio_trades.csv`

---

## v1 Original (2026-05-03)

## Strategy Spec

Five-pair CCI fresh-recovery trigger strategy at H4 timeframe, fixed 1.0% TP / 1.0% stop, real OANDA bid/ask spread. One production cell per pair.

| Pair    | CCI period | Threshold | Recovery | Direction | Test n | Test WR | Test 95% CI    |
|---------|------------|-----------|----------|-----------|--------|---------|----------------|
| EUR_GBP | 20         | 100       | 1        | long      | 313    | 59.4%   | [52.3, 66.4]   |
| USD_JPY | 40         | 100       | 2        | long      | 179    | 57.7%   | [50.4, 65.0]   |
| CHF_JPY | 40         | 100       | 3        | long      | 126    | 63.9%   | [55.2, 72.5]   |
| USD_CAD | 40         | 150       | 1        | long      | 133    | 60.9%   | [51.9, 69.8]   |
| EUR_USD | 30         | 100       | 1        | short     | 274    | 56.6%   | [50.4, 62.7]   |

### Trigger logic

- **CCI(period)** = `(TP - SMA(TP, period)) / (0.015 × mean_abs_deviation)`, where `TP = (high + low + close) / 3`. Computed on mid OHLC.
- **Long fresh trigger:** CCI rose for `recovery` consecutive bars AND CCI at the start of the run was below `-threshold` (oversold). Fires fresh.
- **Short fresh trigger:** CCI fell for `recovery` consecutive bars AND CCI at the start was above `+threshold` (overbought). Fires fresh.

### Confirmation rules

None.

### Exit logic

Same as prior v1s: 1% TP / 1% stop, mid trigger, bid/ask fills, 84 H4-bar timeout, stop-first ordering.

## Portfolio Performance (Test Half: 2023-01-13 → 2026-04-13)

| Metric                          | Train (2,389 trades) | Test (1,024 trades) | Full (3,413 trades) |
|---------------------------------|----------------------|---------------------|---------------------|
| Decisive WR                     | 55.4%                | **58.3%**           | 56.2%               |
| Decisive WR 95% CI              | [53.3, 57.5]         | [54.9, 61.6]        | [54.4, 58.0]        |
| Avg R per trade                 | +0.098               | **+0.136**          | +0.109              |
| Cumulative R                    | +234                 | +139                | +373                |
| Max drawdown (R)                | -37                  | -36                 | -37                 |
| Max consecutive losses          | 20                   | 15                  | 20                  |
| Max simultaneous open positions | 23                   | 25                  | 25                  |

**Largest trade volume of any v1 to date** (3,413 vs RSI 2,199 vs Stoch 7,082 vs SMA 1,661). High max-simultaneous (25) reflects this — sizing implications for FTMO.

### Per-pair contribution (test half)

| Pair    | n   | W/L/T       | WR    | Cum R |
|---------|-----|-------------|-------|-------|
| EUR_GBP | 352 | 127/93/132  | 57.7% | +34   |
| EUR_USD | 274 | 142/109/23  | 56.6% | +33   |
| USD_JPY | 161 | 91/66/4     | 58.0% | +25   |
| USD_CAD | 129 | 68/44/17    | 60.7% | +24   |
| CHF_JPY | 108 | 62/39/7     | 61.4% | +23   |

### Cross-pair monthly R correlation (test half)

|         | CHF_JPY | EUR_GBP | EUR_USD | USD_CAD | USD_JPY |
|---------|---------|---------|---------|---------|---------|
| CHF_JPY |  1.00   | -0.04   | **-0.35** | -0.20 |  0.06   |
| EUR_GBP | -0.04   |  1.00   | -0.05   | +0.23   | +0.32   |
| EUR_USD | **-0.35** | -0.05 |  1.00   | +0.22   | +0.15   |
| USD_CAD | -0.20   | +0.23   | +0.22   |  1.00   | +0.15   |
| USD_JPY |  0.06   | +0.32   | +0.15   | +0.15   |  1.00   |

CHF_JPY and EUR_USD are strongly negatively correlated (-0.35) — natural diversifier within CCI v1. Three USD-quote / USD-base pairs (USD_JPY, USD_CAD, EUR_USD) lightly positively correlated.

## Cross-indicator overlap

| Pair    | BB v1 | Stoch v1 | SMA v1 | RSI v1 | CCI v1 |
|---------|-------|----------|--------|--------|--------|
| EUR_GBP | —     | long     | long   | long   | **long** |
| CHF_JPY | long  | long     | —      | long   | **long** |
| USD_JPY | —     | long     | —      | —      | **long** |
| EUR_CAD | long  | —        | long   | —      | —      |
| GBP_CAD | —     | —        | long   | —      | —      |
| CAD_JPY | —     | —        | long   | —      | —      |
| AUD_CHF | —     | —        | short  | —      | —      |
| CAD_CHF | short | short    | —      | —      | —      |
| **USD_CAD** | — | —     | —      | —      | **long (NEW)** |
| **EUR_USD** | — | —     | —      | —      | **short (NEW)** |

CCI breaks the diminishing-returns pattern observed at RSI: it surfaces **two genuinely new pairs** (USD_CAD long, EUR_USD short) plus solidifies USD_JPY long (which RSI lost at spread).

## Why CCI surfaced new pairs vs RSI

The trigger family is the same shape (fresh recovery from oversold/overbought), but CCI's threshold structure is fundamentally different:

- **RSI** is bounded [0, 100] with classical thresholds 30 / 70 — a "deep" RSI reading at p=14 might be 25 or 35.
- **CCI** is unbounded — typical extreme readings are ±200 to ±300, requiring price to move further from the local TP-SMA than the RSI threshold demands.

This means CCI fires LATER in the move, requiring a more decisive extension. Pairs whose noise floor swamps RSI's threshold structure (USD_CAD, EUR_USD — both higher-spread USD majors) become tradeable at CCI's stricter extreme.

## Notable null results

- **EUR_NOK**, **NZD_CHF** survived mid walk-forward but died at spread (consistent pattern across all v1s).
- **AUD_CAD long**, **AUD_USD short** surfaced in mid but failed spread CI gate.

## High-edge alternatives (NOT selected)

- EUR_GBP `p=14 thr=100 rec=2 long`: te WR 60.6% (n=288) — barely loses to selected by te_n
- USD_JPY `p=40 thr=100 rec=3 long`: te WR 61.4% (n=135) — slightly higher quality, fewer trades

Both alternatives within the same family of (long-period, threshold=100) — different recovery values trade volume for quality.

## Reproducibility

Scripts at `research/cci_phase0_v1/`:
- `sweep_cci_triggers.py` — Phase 0 (5,120 cells)
- `walkforward_cci_triggers.py` — mid walk-forward
- `walkforward_cci_spread.py` — spread walk-forward
- `portfolio_cci_walkforward.py` — portfolio assembly
