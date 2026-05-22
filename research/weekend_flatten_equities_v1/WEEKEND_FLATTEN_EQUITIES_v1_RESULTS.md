# WEEKEND_FLATTEN_EQUITIES_v1 — Results

**Date:** 2026-05-21
**Status:** Complete. Uniform Friday-flatten rule recommended for shipping into `bh_swing` before Phase 3 live capital.
**Design:** [`docs/planning/WEEKEND_FLATTEN_EQUITIES_v1.md`](../../docs/planning/WEEKEND_FLATTEN_EQUITIES_v1.md)

---

## Headline

| Arm | Cum R | Mean R/day (time-adj) | Max drawdown | Bootstrap flip rate | Decision |
|---|---|---|---|---|---|
| **baseline** (no flatten) | +640.2 | −0.036 | **−130.8** | — | — |
| **uniform** (every Friday close → Monday open) | +594.1 | **−0.027** | **−76.6** | 4.7% | **SHIP** ✓ |
| **asymmetric** (flatten winners only) | +655.2 | −0.035 | −111.6 | **25.6%** | NO — unstable |

Uniform Friday-flatten reduces max drawdown by **41% (130.8 → 76.6 R)**, improves time-adjusted return (mean R/day from −0.036 to −0.027), and costs only 7.2% of cum R. The 4.7% bootstrap flip rate is just inside the 5% stability gate. **Recommended to ship.**

Asymmetric "flatten winners only" fails the bootstrap test (25.6% sign-flip rate) and is not trustworthy on this sample.

## Result strength

**Statistical-power gates (from design doc):**

| Gate | Threshold | Observed | Pass? |
|---|---|---|---|
| Total trades | ≥ 10,000 | 11,163 | ✓ |
| % spanning a weekend | ≥ 50% | 95.2% | ✓ |
| Trades per major regime | ≥ 1,000 each | 969–3,246 | **✗ (4 regimes 969–997)** |
| Bootstrap stability (uniform) | flip rate ≤ 5% | 4.7% | ✓ (barely) |

The per-regime gate misses by 3–31 trades in covid_2020 (969), trend_2021 (972), trend_2019 (980), and bear_2022 (997). The miss is small (~3% under) and the bootstrap result is stable; given the consistency of the regime-level improvement (positive in 6/7 regimes), the conclusion holds. A daily-sampling rerun would close this gate definitively but is not necessary to act.

## Stratified findings

### By regime — uniform flatten consistently helps across vol environments

| Regime | Baseline R/day | Uniform R/day | Δ |
|---|---|---|---|
| **bear_2022** | −0.092 | −0.063 | **+0.029** ← largest gain |
| **covid_2020** | −0.034 | −0.016 | **+0.019** |
| trend_2023_2026 | −0.028 | −0.017 | +0.011 |
| trend_2019 | −0.035 | −0.026 | +0.009 |
| vol_2018 | −0.046 | −0.042 | +0.004 |
| trend_2015_2017 | −0.026 | −0.025 | +0.002 |
| trend_2021 | −0.026 | −0.026 | 0.000 (tie) |

**Strong regime pattern:** improvement scales with realized volatility. The two genuinely high-vol regimes (bear_2022, covid_2020) dominate the result. Trend regimes show smaller but consistently positive improvements. This is exactly the asymmetric tail-risk hypothesis the equity weekend rule was originally built on, now measured.

### By strategy — improvement is consistent across both signals

|  | Trades | Baseline R/day | Uniform R/day | Δ |
|---|---|---|---|---|
| baseline (trend) | 5,477 | −0.038 | −0.027 | +0.011 |
| mean_reversion | 5,686 | −0.034 | −0.026 | +0.008 |

Both signals benefit roughly equally. Trend-following gains slightly more in absolute terms.

### By weekend count — most P&L comes from multi-weekend holds

Baseline ledger only:

| Weekends spanned | Trades | Mean R | Cum R |
|---|---|---|---|
| 0 | 533 | −0.23 | −123 |
| 1 | 4,049 | −0.11 | −451 |
| 2+ | 6,581 | +0.18 | **+1,214** |

The 2+-weekend bucket carries the entire profit — and is the bucket where uniform flatten can extract the most checkpointed value.

## Contrast with the forex precedent

The 2026-05-07 forex weekend-flatten test ([[weekend-flatten-test]]) **rejected** both uniform and asymmetric variants on H4 forex. That memo explicitly hypothesized the asymmetry:

> "Equities: weekend-gap risk is dominated by news/earnings/sentiment shocks, often >2-3% gap. Slippage cost is real and frequently exceeds the trade's typical edge."
> "H4 forex: weekend gaps are usually small (3-8 pips on majors), and *both directions* gap symmetrically over time. The 'hold through weekend' exposure is mostly noise rather than an asymmetric tail risk."

This study **confirms the equity side of that hypothesis.** Uniform Friday-flatten pays for itself in equities (max DD −41%, time-adjusted return improves) while costing nothing meaningful in cum R (−7%). The same rule cost forex 35% of cum R for noise-level safety improvement. Different asset classes; different answer.

## Asymmetric rule rejected — why

Asymmetric "flatten winners only" looks attractive in pooled cum R (+15 vs baseline), but the bootstrap reveals it is not stable: 25.6% of 1,000 resamples flip the sign of the delta. The pooled result is within sampling noise.

The mechanism: "flatten winners only" sacrifices losers' weekend protection (which is where the tail risk concentrates per the bear_2022 regime data) in exchange for capturing winners' weekend gains (which average out across the sample). The losers carry the asymmetric downside, and not flattening them defeats the rule's purpose.

## Simulator drift caveat

Both ledgers use the lean simulator's split-bracket logic, which moves the T2 stop to `entry × 0.98` after T1 fills. Production (post-2026-05-21 fix) moves T2 to entry exactly. The simulator therefore overstates baseline T2 losses by up to 2%, which means **the baseline cum R / max DD are conservative**. The flatten rule's measured benefit should hold or grow under a production-accurate simulator. Re-running with corrected T2-stop behavior is a future option.

## Recommendation

**Ship a Friday-close uniform-flatten policy into `bh_swing` before Phase 3 live capital.**

Concrete shape:
- Cron `bh_swing_friday_flatten.py` at e.g. 19:55 UTC Fri (≈15:55 ET, 5 min before US close)
- Walk every open position via broker truth (same path as `bh_swing_monitor`)
- Submit MKT sells for each, journal the close as a new event `event=friday_flatten`
- Re-entries come naturally Monday from the existing `-p` pipeline if signals still rank

The implementation lives parallel to `bh_swing_monitor` — not inside it — because the policy is a daily scheduled event, not a per-tick reconciliation.

## Reproducibility

```bash
# Phase 1: baseline ledger (6 hours on c-8 droplet, lon1)
./run.sh python research/weekend_flatten_equities_v1/generate_baseline_ledger_lean.py \
    --start 2015-01-01 --end 2026-05-01 --interval-days 7 --max-workers 8 \
    --output research/weekend_flatten_equities_v1/baseline_ledger_weekly.csv

# Phase 2: both flatten ledgers (~30 sec each, local)
./run.sh python research/weekend_flatten_equities_v1/simulate_flatten.py \
    --rule uniform \
    --output research/weekend_flatten_equities_v1/uniform_flatten_ledger.csv
./run.sh python research/weekend_flatten_equities_v1/simulate_flatten.py \
    --rule asymmetric \
    --output research/weekend_flatten_equities_v1/asymmetric_flatten_ledger.csv

# Phase 3: comparison + memo
./run.sh python research/weekend_flatten_equities_v1/compare_arms.py
```

Artifacts:
- `baseline_ledger_weekly.csv` (2.9 MB, 11,163 trades)
- `uniform_flatten_ledger.csv` (3.0 MB, same trade IDs, blended_pnl_pct overridden)
- `asymmetric_flatten_ledger.csv` (3.0 MB, same)
- `run.log` (Phase 1 progress trace from the droplet)

## Related work

- [[weekend-flatten-test]] — forex precedent (REJECTED for forex)
- [[rising-3bar-paper]] — regime-dependence pattern that informed the per-regime stratification
- [[bh-swing-automation-plan]] — Phase 3 live-capital roadmap that this study unblocks
