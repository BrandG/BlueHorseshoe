# BH FTMO — SMA Distance-Band Strategy v1 (Phase 0+1+2 Complete)

**Status:** Validated. Production cells **TIGHTENED** under v2 methodology 2026-05-03: 5 pairs → 3 pairs.

**Date locked:** 2026-05-02 (v1), 2026-05-03 (v2 update)

---

## v2 Production Cells (2026-05-03) — supersedes v1 below

Re-run under v2 methodology: per-trade R tracking + expectancy CI gate. The stricter SE-based CI rejected 2 marginal v1 cells (GBP_CAD long, AUD_CHF short) that had Wilson-CI lower bound just above 50%.

**3 production pairs** (was 5 in v1):

| Pair    | SMA period | k (×ATR) | ATR period | Direction | Test n | Test mean R |
|---------|------------|----------|------------|-----------|--------|-------------|
| CAD_JPY | 200        | 2.5      | 14         | long      | 78     | +0.282      |
| EUR_CAD | 100        | 1.5      | 14         | long      | 120    | +0.298      |
| EUR_GBP | 200        | 2.5      | 14         | long      | 81     | +0.182      |

### Portfolio test stats (v2, 278 trades)

WR 71.1% / mean_R +0.289 / cum_R +80.5 / max_DD -12.6R / max_simul 14.

### Changes from v1
- **Lost: GBP_CAD long** (was only in SMA — pair drops out of the multi-indicator universe entirely)
- **Lost: AUD_CHF short** (was only in SMA — pair drops out of the multi-indicator universe entirely)
- **Retained:** EUR_CAD long, EUR_GBP long, CAD_JPY long.
- EUR_GBP cell shifted from p=50 k=1.5 to p=200 k=2.5 under v2 selection.

These two pairs were the marginal Wilson-CI passes that the stricter SE-CI gate rejects. They likely wouldn't have survived in live trading either.

### Reproducibility (v2)
- `research/_v2_rerun/run_sma_v2.py` — full pipeline
- `research/_v2_rerun/sma/walkforward.csv`, `walkforward_spread.csv`, `portfolio_trades.csv`

---

## v1 Original (2026-05-02)

## Strategy Spec

Five-pair SMA distance-band trigger strategy at H4 timeframe, fixed 1.0% take-profit / 1.0% stop, real OANDA bid/ask spread. One production cell per pair.

| Pair    | SMA period | k (×ATR) | ATR period | Direction | Test n | Test WR | Test 95% CI    |
|---------|------------|----------|------------|-----------|--------|---------|----------------|
| EUR_CAD | 100        | 1.5      | 14         | long      | 120    | 70.5%   | [60.4, 80.6]   |
| EUR_GBP | 50         | 1.5      | 14         | long      | 147    | 60.8%   | [51.1, 70.5]   |
| GBP_CAD | 200        | 1.0      | 14         | long      | 89     | 70.3%   | [59.9, 80.7]   |
| CAD_JPY | 200        | 2.5      | 14         | long      | 78     | 64.1%   | [53.5, 74.7]   |
| AUD_CHF | 20         | 2.5      | 14         | short     | 66     | 62.1%   | [50.4, 73.8]   |

### Trigger logic

- **SMA(period)** is the simple moving average of mid-OHLC close.
- **ATR(14)** is Wilder's true-range average on mid OHLC.
- **Distance band:** lower = `SMA - k*ATR`, upper = `SMA + k*ATR`.
- **Long fresh trigger:** `close[i] < SMA[i] - k*ATR[i]` AND the same condition was false at bar `i-1`. Fires only on the bar where penetration first becomes true. (Once price stays below the band, no new triggers fire until price re-enters and exits again.)
- **Short fresh trigger:** mirror — `close[i] > SMA[i] + k*ATR[i]` AND condition was false at `i-1`.
- All indicators are computed on **mid OHLC** (what the trader sees).

### Confirmation rules

None. Entry is at the trigger bar's close.

### Exit logic

- **Long:** TP at `entry × 1.01` (checked against `high_bid`). Stop at `entry × 0.99` (checked against `low_bid`, evaluated stop-first per bar). Timeout exit at `close_bid` after 84 H4 bars (2 weeks).
- **Short:** TP at `entry × 0.99` (checked against `low_ask`). Stop at `entry × 1.01` (checked against `high_ask`). Timeout exit at `close_ask`.
- **Long entry fill:** `close_ask` at the trigger bar. **Short entry fill:** `close_bid` at the trigger bar.

### Sizing convention

R is unitless: +1.0 on TP, -1.0 on stop, fractional on timeout. Sizing (1R = X% of account) is deferred to the FTMO integration phase, not part of this spec.

## Portfolio Performance (Test Half: 2023-03-07 → 2026-04-08)

| Metric                          | Train (1,162 trades) | Test (499 trades)   | Full (1,661 trades) |
|---------------------------------|----------------------|---------------------|---------------------|
| Decisive WR                     | 57.3%                | **65.0%**           | 59.4%               |
| Decisive WR 95% CI              | [54.4, 60.3]         | [60.2, 69.7]        | [56.9, 61.9]        |
| Avg R per trade                 | +0.137               | **+0.235**          | +0.166              |
| Cumulative R                    | +159                 | +117                | +276                |
| Max drawdown (R)                | -26                  | -20                 | -26                 |
| Max consecutive losses          | 14                   | 17                  | 17                  |
| Max simultaneous open positions | 18                   | 22                  | 22                  |

**Key observation:** test outperformed train substantially (avg R +0.235 vs +0.137; WR +7.7pp), the strongest test/train shape of any v1 strategy so far (BB v1 +R, Stoch v1 +0.04R, SMA v1 +0.10R per trade improvement). Trade volume is much lower than Stoch v1 (1,661 trades over 10 years vs Stoch's 7,082) — fewer setups, higher per-trade quality, lower max simultaneous positions.

### Per-pair contribution (test half)

| Pair    | n   | W/L/T       | WR    | Cum R |
|---------|-----|-------------|-------|-------|
| EUR_CAD | 119 | 54/23/42    | 70.1% | +31   |
| GBP_CAD | 106 | 60/30/16    | 66.7% | +30   |
| CAD_JPY | 64  | 43/21/0     | 67.2% | +22   |
| EUR_GBP | 153 | 62/41/50    | 60.2% | +21   |
| AUD_CHF | 57  | 35/22/0     | 61.4% | +13   |

### Cross-pair monthly R correlation (test half)

|         | AUD_CHF | CAD_JPY | EUR_CAD | EUR_GBP | GBP_CAD |
|---------|---------|---------|---------|---------|---------|
| AUD_CHF |  1.00   |  0.12   | -0.04   | -0.10   | -0.29   |
| CAD_JPY |  0.12   |  1.00   |  0.07   |  0.09   | -0.20   |
| EUR_CAD | -0.04   |  0.07   |  1.00   |  0.42   |  0.39   |
| EUR_GBP | -0.10   |  0.09   |  0.42   |  1.00   |  0.18   |
| GBP_CAD | -0.29   | -0.20   |  0.39   |  0.18   |  1.00   |

- **EUR_CAD / EUR_GBP / GBP_CAD** form a positively-correlated cluster (+0.18 to +0.42) — shared GBP/EUR/CAD bloc exposure. Size accordingly.
- **AUD_CHF (short)** is the lone diversifier — negatively correlated with GBP_CAD (-0.29), CAD_JPY (-0.20), EUR_GBP (-0.10).
- **CAD_JPY** is roughly uncorrelated with the rest, useful diversifier.

## Cross-indicator overlap with prior v1 specs

Two of five SMA production pairs match prior v1s in matching directions:

| Pair    | BB v1 | Stoch v1 | SMA v1 | Notes |
|---------|-------|----------|--------|-------|
| EUR_CAD | long  | —        | long   | BB + SMA agree (Stoch died at spread) |
| EUR_GBP | —     | long     | long   | Stoch + SMA agree |
| CHF_JPY | long  | long     | —      | SMA didn't surface CHF_JPY at any cell |
| USD_JPY | —     | long     | —      | SMA-only candidate, didn't survive |
| CAD_CHF | short | short    | —      | SMA-only candidate, didn't survive walk-forward |
| EUR_CAD | long  | —        | long   | (same row as above)                  |
| GBP_CAD | —     | —        | long   | NEW pair from SMA process            |
| CAD_JPY | —     | —        | long   | NEW pair from SMA process            |
| AUD_CHF | —     | —        | short  | NEW pair from SMA process            |

Three pairs (GBP_CAD long, CAD_JPY long, AUD_CHF short) are exclusive to SMA v1 — net unique contribution to a multi-indicator portfolio.

## High-edge alternatives (NOT selected, but documented)

For each pair, multiple cells survived the spread-aware walk-forward gate. Selection rule was largest test n (mirrors BB v1 / Stoch v1). Per-pair alternatives:

- **EUR_CAD** `p=200 k=2.5 long`: te WR **88.2%** (n=81). Becomes relevant if FTMO sizing favors per-trade quality over volume.
- **EUR_GBP** `p=200 k=2.5 long`: te WR **75.0%** (n=81). Same shape — deeper extension, fewer trades, much higher WR.

These alternative cells consistently land at `p=200 k=2.5` — the strategy of "wait for the deepest reversion setup possible" — and offer roughly 2× the per-trade R at ~½ the trade volume. Decision deferred to FTMO sizing simulation.

## Rejected approaches (do not retry without new evidence)

- **Two-MA crossover** (Family C, 720 cells, 19 cells cleared Phase 0 gate): too sparse, several survivors had n<60 which won't survive a cohort split. Family abandoned.
- **Recovery-from-cross** (Family B, 1,280 cells, 109 cells cleared Phase 0): Phase 0 hits were heavily exotic-weighted (CZK, HUF, PLN, ZAR top 5). These historically die at spread, and the non-exotic survivors duplicated band-family hits. Walk-forward + spread tests not run; band family was strictly stronger so we stopped.
- **Exotic pairs** (HUF, PLN, CZK, ZAR, NOK, SEK): survived Phase 0 mid-only, killed by walk-forward and/or spread. Same lesson as BB v1 and Stoch v1.

## Methodology footnote — why we picked the band family

Three trigger families ran in Phase 0:

| Family            | Cells | Phase 0 cleared (n≥50, CI>50%) | Hit rate |
|-------------------|-------|-------------------------------|----------|
| Recovery-from-cross | 1,280 | 109                          | 8.5%     |
| Two-MA cross      | 720   | 19                            | 2.6%     |
| Distance band     | 1,280 | 160                           | **12.5%** |

Band family had the highest Phase 0 hit rate AND the cleanest cross-indicator agreement with locked v1 specs (EUR_CAD long matches BB v1; EUR_GBP long matches Stoch v1; CAD_CHF short matches both). Walk-forward was therefore run on band-family only.

## Reproducibility

Scripts at `research/sma_phase0_v1/`:
- `sweep_sma_recovery.py` — Family B Phase 0 trigger sweep
- `sweep_sma_cross.py` — Family C two-MA crossover Phase 0
- `sweep_sma_band.py` — Family D distance-band Phase 0 (the one that produced this spec)
- `walkforward_sma_band.py` — mid-only 70/30 walk-forward
- `walkforward_sma_band_spread.py` — spread-aware 70/30 walk-forward
- `portfolio_sma_walkforward.py` — production cell selection + portfolio metrics

CSVs at `research/sma_phase0_v1/`:
- `sma_recovery.csv`, `sma_cross.csv`, `sma_band.csv` — Phase 0 outputs
- `walkforward_sma_band.csv` — mid walk-forward
- `walkforward_sma_band_spread.csv` — spread walk-forward (production cell source)
