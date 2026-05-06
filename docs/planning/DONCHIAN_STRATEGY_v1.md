# BH FTMO — Donchian Channel Strategy v1 (Phase 0+1+2 Complete — NULL RESULT)

**Status:** Tested. **ZERO production cells survive.** Donchian breakouts have no time-stable, spread-survivable edge in this H4 forex universe at 1%/1% RR.

**Date locked:** 2026-05-03

## Headline finding

Donchian channel breakouts are the first indicator tested in BH FTMO Phase 2 to produce **no production cells** at all. The methodology is identical to BB v1 / Stoch v1 / SMA v1 / RSI v1 / CCI v1 — same 40-pair universe, same H4 timeframe, same 1%/1% RR, same walk-forward protocol — but Donchian fails at every gate.

## What Donchian's signal looks like

Trigger family:
- **Long:** `close[i] > upper[i-1]` AND condition was false at `i-1` (fresh upper-channel break). Optional `confirm` parameter requires the last `confirm` consecutive bars to close above their respective prior-bar upper.
- **Short:** mirror with `lower`.

Note: bh_ftmo's `donchian()` returns upper/lower inclusive of bar i, so the comparison must use `upper[i-1]` / `lower[i-1]`.

## What we tested

| Sweep | Cells | Edge gate | Cells passing |
|-------|-------|-----------|---------------|
| Phase 0 (mid) | 2,880 (all RR + period + confirm + direction) | n≥50, CI low > break-even WR | 25 (0.9%) |
| Phase 1 (mid walk-forward 70/30) | 1,920 (RR 1/1 + 1/2) | both halves edge CI > BE | **1** (0.05%) |
| Phase 2 (spread walk-forward) | 960 (RR 1/1 only) | both halves CI low > 50% | **0** (0.0%) |

Compared to prior v1s at the same Phase 2 gate:

| Indicator | Phase 2 cells passing |
|-----------|------------------------|
| BB v1 | many (4 production pairs) |
| Stoch v1 | many (4 production pairs) |
| SMA v1 | 7 → 5 production pairs |
| RSI v1 | 13 → 2 production pairs |
| CCI v1 | 7 → 5 production pairs |
| **Donchian v1** | **0** |

## The single mid-walk-forward survivor that died at spread

GBP_CHF p=55 confirm=2 short:

| Stage | Train n | Train WR | Test n | Test WR | Test CI |
|-------|---------|----------|--------|---------|---------|
| Mid Phase 0 | (combined 116) | 67.3% | — | — | — |
| Mid walk-forward | 81 | 67.5% | 35 | 66.7% | [50.6, 82.8] |
| Spread walk-forward | 81 | 66.2% | 35 | 63.6% | **[47.2, 80.0]** |

Test CI lower bound moved from 50.6 to 47.2 once spread was applied — under the 50% gate. The breakout signal was real, but the spread cost (entry at bid for short, slip on stop hits) ate enough WR to push the test CI sub-coin-flip.

## Falsified hypothesis: "breakouts need higher-RR sizing"

Going in, I assumed Donchian would need (1%, 2%) or (1%, 3%) RR — the textbook "let winners run" sizing — and that the prior v1s' 1%/1% would be wrong for breakouts. The Phase 0 sweep tested all three:

| RR | Phase 0 cells with edge above BE |
|----|----------------------------------|
| 1%/1% | 24/960 (2.5%) |
| 1%/2% | 1/960 (0.1%) |
| 1%/3% | 0/960 (0.0%) |

The 1%/1% variant dominated. **H4 forex breakouts are too noisy to extend reliably to 2%/3% targets** — most breakouts revert before the higher TP, getting stopped out in between. The 1%/1% take-profit captures small wins before they revert; the higher targets fail to fire.

This is a real finding worth recording: in this universe, "let winners run" is dominated by "take quick wins" even for indicators whose textbook structure says otherwise.

## Why Donchian fails (interpretation)

Three plausible reasons, presented in increasing severity:

1. **Regime sensitivity.** Donchian is the only indicator we've tested that depends on a market actually trending. The 2016-2022 train period had several extended forex trends (USD strength 2014-2017, JPY moves, COVID dislocations). The 2023-2026 test period is more range-bound. Mean-reversion indicators care about local extremes regardless of regime; breakout indicators only work when breakouts persist.

2. **H4 noise floor.** A 4-hour bar in forex contains enough intra-bar noise that a "fresh close above the 20-bar high" is often a wick that fades within 1-2 bars. The 1%/1% TP is reachable for the half that don't immediately fade, but the other half hit stops first — which is exactly what the spread test reveals.

3. **Spread asymmetry on shorts.** The single survivor was a short. Shorts on cross-currency pairs (GBP_CHF) have wider spreads than majors. Spread cost is paid twice (entry + exit) and bites breakouts harder than mean-reversion entries because mean-reversion trades enter at price extremes (close-of-bar), where the bid-ask snap is less consequential than at a noisy breakout level.

## Implications for the queue

- **Other trend/breakout indicators (Supertrend, Ichimoku) are now suspect.** They share Donchian's "breakout" DNA. Worth testing, but with priors.
- **The "winning shape" in this H4 forex universe at 1%/1% RR is mean-reversion.** Five of six tested indicators (BB, Stoch, SMA-band, RSI, CCI) produced production cells — all are mean-reversion or distance-from-MA structures.
- **Don't downgrade RR for non-mean-reversion indicators.** The Phase 0 RR sweep showed 1%/1% dominates even for breakouts.

## v2 rerun + entry-mode sweep (2026-05-04)

Donchian re-tested under v2 methodology (per-trade R, expectancy CI gate `tr/te ci_low_r > 0`, fixed 1%/1% RR) across all three entry modes:

| Entry mode | Walk-forward survivors | Spread-robust |
|------------|------------------------|---------------|
| `--entry mid`   | 3 / 960  | 0 |
| `--entry limit` | 0 / 960  | — |
| `--entry stop`  | 0 / 960  | — |

The `stop` mode (stop-buy at signal-bar high / stop-sell at signal-bar low — the entry mechanic that's structurally appropriate for breakouts, asking for continuation past the signal bar) was added to `_lib.py` as `sim_long_stop` / `sim_short_stop` (+ spread variants) and tested explicitly to rule out "wrong entry mechanic" as the cause of failure. Result: NULL on stop too. Confirms the breakout shape itself doesn't pay at 1%/1% RR on H4 forex, regardless of entry.

## Reproducibility

Scripts at `research/donchian_phase0_v1/`:
- `sweep_donchian_triggers.py` — Phase 0 (2,880 cells, three RR variants)
- `walkforward_donchian_triggers.py` — mid walk-forward (1,920 cells, RR 1/1 + 1/2)
- `walkforward_donchian_spread.py` — spread walk-forward (960 cells, RR 1/1 only)

v2 rerun:
- `research/_v2_rerun/run_donchian_v2.py` — full pipeline, supports `--entry={mid,limit,stop}`
- `research/_v2_rerun/donchian/walkforward.csv` (mid), `walkforward_limit.csv`, `walkforward_stop.csv`

CSVs in same dirs.
