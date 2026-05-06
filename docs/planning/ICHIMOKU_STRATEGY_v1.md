# BH FTMO — Ichimoku Strategy v1 (Marginal — 1 thin cell)

**Status:** Tested under v2 methodology across all three entry modes and all three classical Ichimoku trigger families. **1 production cell** (USD_SGD tk_cross short under limit entry, n=51 test, mean_R +0.251). Cloud-break and confluence triggers are both NULL.

**Date locked:** 2026-05-04

---

## Headline finding

Ichimoku has the same shape division MACD did: the **inflection-event component (tk_cross)** survives under limit entry, while the **static-channel breakout component (cloud_break)** is NULL across all entries — same fate as Donchian. The third classical trigger (tk_cross filtered by cloud-side, the confluence rule) is also NULL — adding the cloud filter cuts more sample than it adds edge, same anti-pattern as the ADX-as-filter test.

This is the cleanest evidence yet that **inflection-event-under-limit** is a real, distinct shape category in this universe. Both MACD signal_cross and Ichimoku tenkan/kijun cross occupy it; both go NULL under mid/stop and produce edge under limit only.

## Per-trigger results across entry modes

| Trigger | Mid (walk-forward survivors) | Limit | Stop | Production cells |
|---------|-------|-------|------|------------------|
| **tk_cross** (inflection)             | 0/240 | **1**/240 | 0/240 | **1 (USD_SGD short)** |
| **cloud_break** (static channel)      | 2/240 (killed by spread) | 0/240 | 0/240 | 0 |
| **tk_cross_above_cloud** (confluence) | 0/240 | 0/240 | 0/240 | 0 |

cloud_break's two mid survivors are exactly the Donchian pattern: gate-skating walk-forward, killed by spread. The confluence trigger (tk_cross + cloud-side filter) is NULL across all entries despite combining a working trigger with an intuitive filter — the filter cuts trigger volume below the v2 sample-size threshold without compensating per-trade quality.

## v2 Production Cell

| Pair    | Params (T, K, SB, D) | Trigger   | Direction | Train n | Train mean_R | Train CI         | Test n | Test mean_R | Test CI         |
|---------|----------------------|-----------|-----------|---------|--------------|------------------|--------|-------------|-----------------|
| USD_SGD | (9, 26, 52, 26) std  | tk_cross  | short     | 116     | +0.166       | [+0.016, +0.316] | 51     | +0.251      | [+0.024, +0.479] |

Both halves have CI lower bounds **clearly above zero (~2 SE)** — not gate-skating, unlike the candlestick survivor (test CI low at +0.0004) or the pivot survivors (train CI low at +0.009). Per-trade quality is comparable to the working mean-reversion indicators.

But the sample is **thin**: single pair, 167 total trades over ~10 years of H4 data. Compare to:

| Indicator | Production cells | Total trades (full ledger) |
|-----------|------------------|----------------------------|
| MACD      | 5 | 1,179 |
| ATR       | 3 | 2,746 |
| BB / RSI / CCI / etc. | 3-5 each | several thousand each |
| Candlestick | 1 | 416 |
| **Ichimoku** | **1** | **167** |

USD_SGD is an exotic pair with limited bar density. The signal *exists* (CI bounds are clean) but you'll only get ~5-6 trades a year, which is not a lot of statistical power for the live deployment.

### Portfolio Performance (single-cell, USD_SGD short)

| Metric            | Train (n=116) | Test (n=51)  | Full (n=167) |
|-------------------|---------------|--------------|--------------|
| WR                | 61.3%         | **70.6%**    | 64.2%        |
| Mean R / trade    | +0.166        | **+0.251**   | +0.192       |
| Cumulative R      | +19.3         | +12.8        | +32.1        |
| Max drawdown      | -10.0R        | **-2.4R**    | -10.0R       |
| Max consec losses | 7             | 4            | 7            |
| Max simultaneous  | 4             | 3            | 4            |

Test out-performs train (+0.251 vs +0.166 mean_R; 70.6% vs 61.3% WR) — desirable shape. **Smallest test max_DD of any v2 indicator (-2.4R)**, but that's at least partly an artifact of the small sample.

### Trigger Spec

**tk_cross (production):**
- Long: `tenkan[i] > kijun[i]` AND `tenkan[i-1] <= kijun[i-1]`
- Short: `tenkan[i] < kijun[i]` AND `tenkan[i-1] >= kijun[i-1]`

Where `tenkan = (highest_high(9) + lowest_low(9)) / 2` and `kijun = (highest_high(26) + lowest_low(26)) / 2`. The standard (9, 26, 52, 26) parameter set wins; faster (7, 22, 44, 22) and slower (12, 30, 60, 30) parameterizations didn't surface any survivors.

**Entry: limit-at-signal-bar-extreme, 1-bar fill window.** Same as MACD — mid was 0 walk-forward survivors for tk_cross, stop also 0.

## Cumulative Indicator Status (BH FTMO Phase 2 v2 sweep)

| Indicator   | Working entry | Production cells | Shape |
|-------------|---------------|------------------|-------|
| BB / Stoch / WR / SMA / EMA / RSI / CCI | mid + limit | 3-5 each | smoothed mean-reversion |
| MACD        | limit only    | 5 | inflection-event |
| ATR-momentum | mid / limit / stop | 2 / 3 / 1 | volatility-scaled momentum |
| Candlestick | mid only      | 1 thin (gate-skating) | bar-pattern reversal |
| **Ichimoku tk_cross** | **limit only** | **1 thin (clean CI)** | **inflection-event** |
| Pivots      | — | 0 | level-touch (no smoothing) |
| Donchian    | — | 0 | static-channel breakout |
| SuperTrend  | — | 0 | trend flip with ATR band |
| ADX (standalone) | — | 0 | trend strength |
| ADX (filter on Donchian/SuperTrend) | — | 0 | filter falsified |
| **Ichimoku cloud_break** | — | 0 | **same family as Donchian — NULL** |
| **Ichimoku tk_cross_above_cloud** | — | 0 | **filter falsified, same as ADX-filter** |

The shape spectrum is now well-mapped:

- **Smoothed mean-reversion**: oscillator state / distance-from-MA → multi-pair production cells.
- **Inflection-event under limit**: MACD signal_cross, Ichimoku tk_cross → small productive set.
- **Volatility-scaled momentum**: ATR range_expansion → only momentum shape that works.
- **Bar-pattern reversal under mid**: candlestick engulfing → 1 thin cell.
- **Static-channel breakout**: Donchian, Ichimoku cloud_break, SuperTrend → NULL.
- **Trend strength**: ADX → NULL standalone AND as filter.
- **Compound trigger + filter**: confluence rules / ADX gates → NULL (filter cuts more than it adds).

## Reproducibility

- `research/_v2_rerun/run_ichimoku_v2.py` — full pipeline, supports `--entry={mid,limit,stop}`
- `research/_v2_rerun/ichimoku/walkforward.csv`, `walkforward_limit.csv`, `walkforward_stop.csv`
- `research/_v2_rerun/ichimoku/walkforward_spread_limit.csv` — single survivor row
- `research/_v2_rerun/ichimoku/portfolio_trades_limit.csv` — 167-trade ledger

(No mid/stop portfolio CSVs — both NULL.)

Param grid: 3 param sets × 3 triggers × 2 directions × 40 pairs = 720 cells per entry mode.
