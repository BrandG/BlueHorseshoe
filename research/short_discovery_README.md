# Short-side discovery arc (2026-06-26)

The Bud book is structurally long-skewed. Three studies searched for deployable SHORT cells to
balance it, all on the shared fidelity-checked harness (`research/_lib/fx_replay.py`): bracketed R
net of spread, A/B/holdout, expectancy-CI, and a **matched-random-short control** (a short edge on a
pair that simply fell is drift, not signal).

- **short_discovery_v1** — mean-reversion families (bb/rsi/cci/stoch/sma/ema) short. Result: the
  well is mostly dry beyond known cells; survivors concentrated on CAD_CHF (re-found #1 cells). Net
  new diversified supply ≈ sma:CAD_CHF only.
- **short_discovery_trend_v1** — trend/breakout families (atr/macd/ichimoku) short, with vectorized
  masks fidelity-checked against the live evaluators (logic mismatches = 0). Found diversified
  shorts across 4 pairs; ichimoku's bearish tk-cross was the standout. (atr shorts that looked good
  in the recent window FAILED the full gate — recent-regime drift, correctly demoted.)
- **short_tuning_v1** — param-tuning the candidates. Key finding: **in-sample param tuning OVERFIT**
  (degraded 2 of 5 targets vs their textbook defaults) → use default params. The real filter is
  **cross-family pair agreement**: GBP_CAD (ichimoku + macd) and CAD_CHF (3 families) are the most
  credible short hosts; USD_SGD confirmed (already a deployed cell).

## Decision (2026-06-26)
Deploy the cross-confirmed ichimoku core to the autonomous trader with **default params** (9/26
tk_cross): **ichimoku:GBP_CAD:short** (new; hedges the existing ema:GBP_CAD long) and
**ichimoku:CAD_CHF:short** (new). `ichimoku:USD_SGD:short` already exists (briefing.py). Single-family
/ fragile candidates (macd:EUR_USD, atr/sma/cci variants) held for more confirmation.
