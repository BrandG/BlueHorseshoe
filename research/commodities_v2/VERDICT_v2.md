# FTMO Commodities v2 — Regate Verdict (gated geometry + beta baseline)

Run date: 2026-06-12 UTC. Outputs: `research/commodities_v2/regate/`.
Geometry: stop 1% / target 1% (the v2 production gate), limit offset 0.25×stop,
max hold 84 bars. 732,410 signal trades; 461,488 always-in baseline trades.

## The question this run answered

Round 1 (VERDICT.md) showed gold positive across both families with NW CIs
above zero. Was that alpha, or a decade of gold beta wearing a bracket? This
run added, for every (instrument, timeframe, entry mode, direction), an
**always-in baseline** — fire on every bar, identical bracket, identical
costs — and judged every cell on **excess over its matched baseline** with a
circular block-bootstrap CI.

## Answer: gold was beta. The baseline absorbs everything.

Always-long XAU_USD with the same bracket earns, per trade:

| baseline | mean R | NW CI |
|---|---|---|
| H4 limit | **+0.297** | [0.266, 0.328] (n=16,061) |
| D1 limit | +0.280 | [0.240, 0.320] |
| H4 market | +0.063 | [0.028, 0.097] |

**Zero gold cells produce bootstrap-CI-positive excess over baseline.** Not
Donchian (+0.366 raw in round 1), not SuperTrend, not TSMOM, not the MR
family. The round-1 "trend wakes up on gold" headline was long-gold beta
plus the limit-entry mechanic. Note also the uniform ~+0.23R gap between
limit and market baselines: the limit fill itself (buy the dip of the next
bar) is an entry mechanic worth more than any signal tested here — consistent
with the forex limit-entry law.

## What actually survives the beta control

Cells with CI-positive excess AND positive absolute R — the only standard
that matters — reduce to **copper MA-distance mean reversion**:

| cell | mode | n | mean R | baseline | excess | boot CI low |
|---|---|---|---|---|---|---|
| XCU ema50_dist_low H4 | limit | 3,731 | +0.268 | +0.220 | +0.048 | +0.014 |
| XCU ema50_dist_low H4 | market | 3,731 | +0.038 | −0.017 | +0.055 | +0.016 |
| XCU sma50_dist_low H4 | market | 4,209 | +0.022 | −0.017 | +0.039 | +0.002 |

Same indicator shape as the forex v2 winners (MA-distance under limit), now
beating an always-in control on a different asset class. Financing-robust:
the cells hold shorter than the baseline, so carry drag *widens* the excess
(at a worst-case 2bp/day, ema50 limit is still +0.255 absolute / +0.050
excess).

Excess-positive but absolute-negative rows (NATGAS donchian D1 −0.30R beating
a −0.45R baseline; WTI supertrend D1 +0.001R) are "less bad than always-in,"
not tradeable cells.

## Cost and venue reality

Median H4 spread in R at the 1% geometry: gold 0.020, copper/WTI/Brent
~0.05, silver 0.090, natgas 0.235. Natgas remains untradeable at this
bracket; silver marginal.

**OANDA practice cannot trade these commodities at all** — the explicit
instrument query returns `INSTRUMENT_NOT_TRADEABLE` (candles are served;
trading and financing metadata are not). Consequences: no OANDA paper venue
for a commodity cell (FTMO's platform would be the venue), and financing is
estimated by sensitivity band, not data.

## Data quality

The round-1 validator gaps were a DST artifact: OANDA anchors commodity
candles to 17:00 America/New_York, so a fixed-UTC expected grid misclassifies
half the year. With the NY-anchored grid (`validate.py`), H4 gaps collapse
from ~10,750 to ~218 per instrument (~22/yr ≈ unmodelled US market holidays);
H1 residuals ~950 except Brent (~5,900 — ICE runs its own break calendar;
does not affect the H4 sweep). Sweep data is sound.

## Recommendations

1. **Copper MA-distance is the one candidate.** Before any wiring: replication
   tests (split-half stability, parameter-neighborhood sweep around the
   50-period / −1% threshold), per the NW-re-gate lesson that single-cell CI
   evidence is fragile. If it replicates, it enters as a tracking-only cell —
   and the venue question (FTMO direct, since OANDA can't paper it) gets
   decided then.
2. **Drop gold-as-signal.** "Long gold with limit brackets" is a beta
   allocation question, not a sleeve signal; no cell adds to it.
3. **Shelve the conditioner ideas** (COT, inventory-event proximity, real
   yields): with no absolute-positive base edge on oil/natgas, there is
   nothing to condition. Revisit only if copper replicates and the family
   broadens.
