# BH FTMO — Stochastic Strategy v1 (Phase 0+1+2 Complete)

**Status:** Validated. Production cells re-confirmed under v2 methodology 2026-05-03 (same 4 pairs as v1).

**Date locked:** 2026-05-01 (v1), 2026-05-03 (v2 confirmation)

---

## v2 Production Cells (2026-05-03)

Re-run under v2 methodology: per-trade R tracking + expectancy CI gate. **Same 4 production pairs as v1** — Stoch is the only indicator whose pair set was unchanged by the methodology tightening.

| Pair    | K period | D period | Threshold | Recovery | Direction | Test n | Test mean R |
|---------|----------|----------|-----------|----------|-----------|--------|-------------|
| CAD_CHF | 9        | 3        | 20        | 1        | short     | 504    | +0.109      |
| CHF_JPY | 5        | 3        | 20        | 1        | long      | 529    | +0.132      |
| EUR_GBP | 21       | 3        | 30        | 1        | long      | 575    | +0.082      |
| USD_JPY | 9        | 3        | 30        | 1        | long      | 564    | +0.119      |

Note: USD_JPY threshold shifted slightly (25 → 30) and CAD_CHF k_period shifted (5 → 9) under v2 selection — same pairs, slightly tuned params.

### Portfolio test stats (v2, 2171 trades)

WR 56.1% / mean_R +0.108 / cum_R +233.5 / max_DD -70.5R / max_simul 44.

### Changes from v1
None at the pair level. Specific cell parameters differ slightly.

### Reproducibility (v2)
- `research/_v2_rerun/run_stoch_v2.py` — full pipeline
- `research/_v2_rerun/stoch/walkforward.csv`, `walkforward_spread.csv`, `portfolio_trades.csv`

---

## v1 Original (2026-05-01)

## Strategy Spec

Four-pair Stochastic %K trigger strategy at H4 timeframe, fixed 1.0% take-profit / 1.0% stop, real OANDA bid/ask spread. One production cell per pair.

| Pair    | K period | D period | Threshold | Recovery bars | Direction | Test n | Test WR | Test 95% CI    |
|---------|----------|----------|-----------|---------------|-----------|--------|---------|----------------|
| CHF_JPY | 5        | 3        | 20        | 1             | long      | 529    | 56.5%   | [52.1, 60.8]   |
| EUR_GBP | 14       | 3        | 30        | 1             | long      | 609    | 55.3%   | [50.1, 60.4]   |
| USD_JPY | 9        | 3        | 25        | 1             | long      | 506    | 55.9%   | [51.5, 60.2]   |
| CAD_CHF | 5        | 3        | 15        | 1             | short     | 482    | 57.1%   | [52.4, 61.8]   |

### Trigger logic

- **Stochastic %K** computed on mid OHLC: `100 * (close - min(low, k_period)) / (max(high, k_period) - min(low, k_period))`. The %D signal line (3-period SMA of %K) is computed for symmetry but is not used by the trigger.
- **Long fresh trigger:** %K rose for `recovery` consecutive bars AND %K at the start of that run was below `threshold`. Concretely: `K[i] > K[i-1] > ... > K[i-recovery]` AND `K[i-recovery] < threshold`. Fires only on the bar where the condition first becomes true.
- **Short fresh trigger:** mirror — %K fell `recovery` consecutive bars AND %K at the start was above `100 - threshold`.
- All four production cells use **`recovery=1`**, meaning a single up-bar (long) or down-bar (short) from the threshold extreme. Higher-recovery alternatives surfaced in the sweep but were rejected by the largest-`te_n` selection rule (see "High-edge alternative" below).

### Confirmation rules

None. Entry is at the trigger bar's close.

### Exit logic

- **Long:** TP at `entry × 1.01` (checked against `high_bid`). Stop at `entry × 0.99` (checked against `low_bid`, evaluated stop-first per bar). Timeout exit at `close_bid` after 84 H4 bars (2 weeks).
- **Short:** TP at `entry × 0.99` (checked against `low_ask`). Stop at `entry × 1.01` (checked against `high_ask`). Timeout exit at `close_ask`.
- **Long entry fill:** `close_ask` at the trigger bar. **Short entry fill:** `close_bid` at the trigger bar.

### Sizing convention

R is unitless: +1.0 on TP, -1.0 on stop, fractional on timeout. Sizing (1R = X% of account) is deferred to the FTMO integration phase, not part of this spec.

## Portfolio Performance (Test Half: 2023-02-15 → 2026-04-13)

| Metric                          | Train (4957 trades) | Test (2125 trades)   | Full (7082 trades)  |
|---------------------------------|---------------------|----------------------|---------------------|
| Decisive WR                     | 53.3%               | **56.1%**            | 54.1%               |
| Decisive WR 95% CI              | [51.9, 54.8]        | [53.7, 58.4]         | [52.9, 55.3]        |
| Avg R per trade                 | +0.061              | **+0.101**           | +0.073              |
| Cumulative R                    | +301                | +214                 | +515                |
| Max drawdown (R)                | -67                 | -52                  | -67                 |
| Max consecutive losses          | 22                  | 14                   | 22                  |
| Max simultaneous open positions | 47                  | 40                   | 47                  |

**Key observation:** test outperformed train (avg R +0.101 vs +0.061; WR +2.8pp), the same pattern observed on BB v1. The rec=1 trigger family fires very frequently — 7,082 trades over 10 years means ~700 trades per year across the four pairs.

### Per-pair contribution (test half)

| Pair    | n    | W/L/T          | WR    | Cum R |
|---------|------|----------------|-------|-------|
| CHF_JPY | 524  | 277/214/33     | 56.4% | +63   |
| USD_JPY | 467  | 260/195/12     | 57.1% | +65   |
| CAD_CHF | 474  | 240/182/52     | 56.9% | +58   |
| EUR_GBP | 660  | 212/184/264    | 53.5% | +28   |

EUR_GBP has by far the highest timeout rate (264/660 = 40%) — its 1% target on H4 takes longer to resolve than the JPY/CHF crosses. Cumulative R contribution is lowest of the four despite trade count being highest.

### Cross-pair monthly R correlation (test half)

```
          CAD_CHF  CHF_JPY  EUR_GBP  USD_JPY
CAD_CHF    1.00    +0.24    +0.19    -0.30
CHF_JPY   +0.24    1.00    +0.06    +0.33
EUR_GBP   +0.19   +0.06     1.00    +0.18
USD_JPY   -0.30   +0.33    +0.18     1.00
```

CAD_CHF and USD_JPY are negatively correlated (-0.30) — natural diversification. The CHF_JPY ↔ USD_JPY correlation (+0.33) is the strongest pair-pair link (shared JPY exposure). EUR_GBP is approximately uncorrelated with the rest.

### Cross-indicator overlap with BB v1

BB v1 production pairs: CAD_CHF (short), USD_JPY (long), EUR_CAD (long), CHF_JPY (long).

Stochastic v1 production pairs: CAD_CHF (short), USD_JPY (long), EUR_GBP (long), CHF_JPY (long).

**Three of four BB v1 production pairs are also production pairs in stochastic v1, in the same direction.** EUR_CAD survived stochastic Phase 1 walk-forward at the cell level (2 mid-robust cells) but did not survive Phase 2 spread. EUR_GBP is the new pair that stochastic surfaces.

## Methodology

Validated through three phases of testing, each with progressively stricter conditions. Identical methodology to BB v1.

### Phase 0 — Does the trigger predict anything?

- Mid prices throughout (entry, TP, stop, timeout exit on mid OHLC). No bid/ask.
- Fixed 1% / 1% RR.
- Full universe (40 OANDA majors and exotics).
- Both directions (long below threshold, short above 100 - threshold).
- Coin-flip gate: WR_decisive Wilson 95% CI lower bound > 50%.

Result: 541 of 5,120 cells passed (10.6%, well above ~2.5% noise rate). Cells clustered tightly by pair and direction — CHF_JPY purely long, CAD_CHF purely short, USD_JPY purely long, etc.

### Phase 1 — Walk-forward 70/30 split

Same 5,120-cell grid. Each cell's trades split chronologically by `entry_ts` at the 70th percentile.

Result: 108 cells passed both halves with CI lower > 50%, train n ≥ 50, test n ≥ 30. Pair clustering preserved: CHF_JPY (44), CAD_CHF (23), USD_JPY (19), EUR_GBP (9), EUR_HUF (6), GBP_NZD (3), EUR_CAD (2), NZD_CHF (2).

### Phase 2 — Deployment cost (real spread)

Same 5,120-cell grid re-run with bid/ask fills. Stochastic %K still computed on mid (what the trader sees), but every fill pays spread.

Result: 28 of 108 mid-robust cells survived spread (74% mortality). Surviving pairs: CHF_JPY (20 cells), EUR_GBP (3), USD_JPY (3), CAD_CHF (2). EUR_HUF, GBP_NZD, EUR_CAD, NZD_CHF dropped — primarily because their per-trade R is small relative to spread cost on H4.

## Parameter Grid

Stochastic-specific dimensions (5,120 cells total):
- K period: 5, 9, 14, 21
- D period: 3 (fixed)
- Threshold: 15, 20, 25, 30 (long); short uses 100 - threshold
- Recovery bars: 1, 2, 3, 4
- Direction: long, short
- Pair: full 40

## High-Edge Alternative (Not Selected)

The `largest te_n` selection rule favors high-frequency rec=1 cells. The Phase 2 sweep also surfaced a CHF_JPY-long cluster of rec=2 cells with much higher per-trade R but smaller sample sizes.

| Cell                              | Test n | Test WR | Test 95% CI    | Implied avg R/trade |
|-----------------------------------|--------|---------|----------------|---------------------|
| CHF_JPY kP=21 thr=15 rec=2 long   | 174    | 67.1%   | [59.9, 74.3]   | ~+0.32              |
| CHF_JPY kP=21 thr=20 rec=2 long   | 203    | 66.1%   | [59.5, 72.8]   | ~+0.30              |
| CHF_JPY kP=5  thr=15 rec=2 long   | 258    | 65.4%   | [59.5, 71.4]   | ~+0.29              |

The deployed `rising_3bar` paper trader (`recovery=3, threshold=20, long`, all 40 pairs at 1.5%/1.5% RR) is a relative of these higher-edge cells. The rec=2 family produces ~3× the per-trade R of the rec=1 selected cells, at ~1/3 the trade volume — net cumulative R is similar but per-trade Sharpe is higher.

This alternative becomes relevant at the FTMO sizing phase: fewer, higher-quality trades may be preferable when each loss consumes daily-DD budget. The current spec uses rec=1 to mirror BB v1's selection rule and produce comparable cumulative-R portfolios for cross-indicator combination work.

## Approaches Tested and Rejected

### Higher recovery counts on non-CHF_JPY pairs

Recovery=2/3/4 cells failed Phase 2 outside CHF_JPY. EUR_GBP, USD_JPY, CAD_CHF only survived spread at recovery=1. The rec=2 high-edge family is a CHF_JPY-specific phenomenon in this data window.

### Confirmation bar variants

Not tested in the stochastic sweep. BB v1 found that only `none` and `rise_0.00%` (one specific pair) added value across 6 confirmation variants, and that the dimension dilutes the sample without surfacing meaningful winners. Confirmation was deliberately omitted from the stochastic Phase 0/1/2 grid.

### Exotic pairs (HUF, PLN, CZK, ZAR)

Same pattern as BB v1: positive-WR mid cells at Phase 0 (EUR_HUF in particular had 38 surviving cells), but spread costs eliminated edge at Phase 2.

### `recovery=4`

Highest-recovery cells (35 in Phase 0, dropped to ~1 by Phase 2) had insufficient sample sizes after the walk-forward split. Not productive.

## On the Spread Question

Same discipline as BB v1: Phase 0 / Phase 1 run on mid prices to isolate trigger predictive value; Phase 2 introduces spread to test deployment cost survivability. Conflating the phases obscures both the signal-quality question and the cost-survival question.

## Reproducibility

The four scripts that produced this work live at `research/stoch_phase0_v1/`:

| Script                              | Purpose                                                    |
|-------------------------------------|------------------------------------------------------------|
| `sweep_stoch_triggers.py`           | Phase 0 base sweep: 5,120 cells, mid prices.               |
| `walkforward_stoch_triggers.py`     | Phase 1 walk-forward 70/30, mid prices.                    |
| `walkforward_stoch_spread.py`       | Phase 2 walk-forward 70/30, real OANDA bid/ask fills.      |
| `portfolio_stoch_walkforward.py`    | Final per-pair cell selection + portfolio walk-forward.    |

To regenerate:

```bash
./run.sh python research/stoch_phase0_v1/sweep_stoch_triggers.py
./run.sh python research/stoch_phase0_v1/walkforward_stoch_triggers.py
./run.sh python research/stoch_phase0_v1/walkforward_stoch_spread.py
./run.sh python research/stoch_phase0_v1/portfolio_stoch_walkforward.py
```

CSVs are written to `/tmp/` and are not version-controlled.

## Relationship to the Deployed `rising_3bar` Paper Trader

The deployed `rising_3bar_from_oversold` paper trader (`src/bh_ftmo_paper.py`, OANDA practice account, every 4h) uses `recovery=3, threshold=20, long`, all 40 pairs, at 1.5%/1.5% RR. This v1 spec is a tighter, multi-pair-cell version at 1.0%/1.0% RR.

Differences:
- **Universe:** rising_3bar = all 40 pairs (no selection); v1 = 4 specific pairs.
- **Recovery:** rising_3bar = 3 bars; v1 = 1 bar.
- **RR:** rising_3bar = 1.5%/1.5%; v1 = 1.0%/1.0%.
- **Direction mix:** rising_3bar = long-only; v1 = three long + one short.

Both are valid. v1 is the spec used for cross-indicator portfolio assembly with BB v1; rising_3bar is the live forward-test running in parallel.

## Next Steps

The Stochastic strategy is locked at v1. It will not be deployed standalone. Pending:

1. **One additional indicator** through the same Phase 0/1/2 methodology, before assembling a multi-indicator portfolio.
2. **Cross-indicator portfolio walk-forward** — combine BB v1 cells, Stochastic v1 cells, and any third indicator's cells into one chronological trade ledger. Re-walk-forward at the portfolio level, measure aggregate WR, R, max DD, concurrent positions.
3. **FTMO sizing simulation** — once the multi-indicator portfolio is locked, layer the FTMO 2-Step Swing 10k rules. Pass-rate analysis. See `FTMO_RULES.md`.
4. **Live forward test** — paper trade the portfolio on the OANDA practice account, parallel to `rising_3bar`. Soak for 4+ weeks before live FTMO deployment.

Sizing is **deliberately not** part of v1.
