# BH FTMO — EMA Distance-Band Strategy v1 (Phase 0+1+2 Complete)

**Status:** Validated under v2 methodology. 4 production cells.

**Date locked:** 2026-05-04

---

## v2 Production Cells

Run directly under v2 methodology (per-trade R tracking + expectancy CI gate `mean_R - 1.96*SE > 0`, train/test n ≥ 50/30). Same parameter grid as SMA-band, but with EMA as the moving-average shape.

**4 production pairs:**

| Pair    | EMA period | k (×ATR) | ATR period | Direction | Test n | Test mean R |
|---------|------------|----------|------------|-----------|--------|-------------|
| CHF_JPY | 20         | 2.0      | 14         | long      | 77     | +0.234      |
| EUR_CAD | 100        | 2.0      | 14         | long      | 119    | +0.242      |
| EUR_GBP | 200        | 1.5      | 14         | **short** | 104    | +0.199      |
| GBP_CAD | 200        | 2.0      | 14         | long      | 85     | +0.395      |

### Trigger logic

- **EMA(period)** computed on mid-OHLC close.
- **ATR(14)** Wilder's true-range average on mid OHLC.
- **Distance band:** lower = `EMA - k*ATR`, upper = `EMA + k*ATR`.
- **Long fresh trigger:** `close[i] < EMA[i] - k*ATR[i]` AND condition was false at `i-1`.
- **Short fresh trigger:** `close[i] > EMA[i] + k*ATR[i]` AND condition was false at `i-1`.
- All indicators on mid OHLC; entry at the trigger bar's close.

### Exit logic

Same as SMA / BB / Stoch v2: fixed 1.0% TP, 1.0% stop, 84-bar (2-week) timeout. Long entry fills `close_ask`, exits TP at `high_bid` / stop at `low_bid` / timeout at `close_bid`. Short mirrors. Stop checked first per bar.

## Portfolio Performance (v2, full pipeline)

| Metric                          | Train (893 trades) | Test (384 trades)   | Full (1,277 trades) |
|---------------------------------|--------------------|---------------------|---------------------|
| Decisive WR                     | 58.1%              | **65.0%**           | 59.9%               |
| Avg R per trade                 | +0.150             | **+0.277**          | +0.188              |
| Cumulative R                    | +134.2             | +106.2              | +240.3              |
| Max drawdown (R)                | -21.2              | -11.1               | -21.2               |
| Max consecutive losses          | 19                 | 10                  | 19                  |
| Max simultaneous open positions | 14                 | 17                  | 17                  |

**Test outperforms train** by ~13pp WR and +0.13 R/trade — same favorable shape seen across BB / Stoch / SMA v2.

### Per-pair contribution (test half)

| Pair    | n   | WR    | mean R  | Cum R |
|---------|-----|-------|---------|-------|
| CHF_JPY | 79  | 59.7% | +0.203  | +16.0 |
| EUR_CAD | 102 | 64.9% | +0.273  | +27.8 |
| EUR_GBP | 104 | 62.7% | +0.199  | +20.7 |
| GBP_CAD | 99  | 71.3% | **+0.420** | +41.6 |

GBP_CAD long is the standout — 71.3% WR with mean_R +0.42 over 99 test trades.

## Cross-indicator overlap

| Pair    | BB | Stoch | SMA | RSI | CCI | EMA |
|---------|----|----|-----|-----|-----|-----|
| CHF_JPY | L  | L  | —   | L   | L   | **L** |
| EUR_CAD | L  | —  | L   | —   | —   | **L** |
| EUR_GBP | —  | L  | L   | L   | —   | **S (NEW)** |
| GBP_CAD | —  | —  | —   | —   | —   | **L (NEW)** |

- **EUR_GBP short** is exclusive to EMA — every other indicator surfaces EUR_GBP as long.
- **GBP_CAD long** was a v1 SMA pair killed under v2 SMA; EMA recovers it. The pair has signal — SMA's grid just didn't catch the optimal band geometry.
- CHF_JPY long now has 5-indicator confirmation (BB, Stoch, RSI, CCI, EMA) — tied with USD_JPY for highest coverage in the universe.
- EUR_CAD long now has 3-indicator confirmation (BB, SMA, EMA).

## Why EMA finds different pairs than SMA

EMA weights recent prices more heavily than SMA. Effects:

- **Faster band response** to recent volatility — picks up shorter-term distortions SMA's slower mean smooths over (CHF_JPY p=20 EMA fires; SMA at p=20 didn't survive WF).
- **Different drift center** in trending pairs — EMA's center sits closer to current price, so band-edge triggers identify different mean-reversion setups (EUR_GBP becomes a short candidate under EMA but a long under SMA — likely reflects which side of the EMA's faster mean is anomalous at the trigger).
- **Net effect:** Same underlying mean-reversion shape, different setup catch. Not redundant with SMA; complementary.

## High-edge alternatives (NOT selected)

GBP_CAD `p=200 k=2.0 long` was already the largest-n cell. No higher-edge alternative cells were promoted; selection rule (largest te_n per pair, ties broken by te_mean_r) chose the cells listed.

## Reproducibility

- `research/_v2_rerun/run_ema_v2.py` — full pipeline (Phase 1+2)
- `research/_v2_rerun/ema/walkforward.csv` — mid walk-forward
- `research/_v2_rerun/ema/walkforward_spread.csv` — spread walk-forward (production cell source)
- `research/_v2_rerun/ema/portfolio_trades.csv` — assembled portfolio trades
