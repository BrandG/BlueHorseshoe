# ATR Regime P4

## Headline
FTMO-constrained call on `long_mr_strong4` at the 180-calendar-day external censoring horizon: **no improvement once constrained**.
`size_down_high_0_5` pass/fail/push is 5.3%/0.0%/94.7% vs unconditioned 8.8%/2.7%/88.5%. Max-loss breaches: 0 vs 3; daily-loss breaches: 0 vs 0.
`hard_gate_skip_high` pass/fail/push is 5.3%/0.9%/93.8%; max-loss breaches 1 and daily-loss breaches 0.

The 180-day horizon is a reporting/censoring convention for a finite probability estimate; the loaded Swing FTMO config has `max_trading_days = null`, so the rule engine imposes no challenge expiry and pushes here mean the external analysis horizon expired.

## FTMO And Risk Inputs
FTMO config: `src/bh_ftmo_swing_config.json`; initial_balance=10000, phase=step1, target=10.0%, daily_loss=5.0%, max_loss=10.0%, max_loss_type=static, min_trading_days=4, max_trading_days=None, timezone=Europe/Prague.
Base risk/trade: 0.5% from `src/bud/auto_v2.py:87` (`RISK_PER_TRADE_PCT = 0.005`). Slot cap and daily risk cap: 3 concurrent positions and 4.0% daily risk from `src/bh_ftmo_config.json` risk block.

## Headline Aggregates
| sample | book | horizon_days | windows | pass_rate | fail_rate | push_rate | median_days_to_target | daily_loss_breaches | max_loss_breaches | median_max_drawdown_pct | opened_trades | skipped_slot | skipped_daily_risk | skipped_regime |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| long_mr_full6 | hard_gate_skip_high | 180 | 113 | 8.0% | 0.0% | 92.0% | 120 | 0 | 0 | 4.1% | 7763 | 170986 | 0 | 99169 |
| long_mr_full6 | size_down_high_0_5 | 180 | 113 | 5.3% | 0.0% | 94.7% | 121 | 0 | 0 | 3.8% | 9630 | 270175 | 0 | 0 |
| long_mr_full6 | unconditioned | 180 | 113 | 10.6% | 0.9% | 88.5% | 123.5 | 0 | 1 | 4.8% | 9417 | 264626 | 17 | 0 |
| long_mr_strong4 | hard_gate_skip_high | 180 | 113 | 5.3% | 0.9% | 93.8% | 112.5 | 0 | 1 | 4.5% | 7577 | 128534 | 0 | 78320 |
| long_mr_strong4 | size_down_high_0_5 | 180 | 113 | 5.3% | 0.0% | 94.7% | 140.5 | 0 | 0 | 3.8% | 9444 | 207653 | 0 | 0 |
| long_mr_strong4 | unconditioned | 180 | 113 | 8.8% | 2.7% | 88.5% | 108 | 0 | 3 | 5.0% | 9145 | 201270 | 10 | 0 |

## Horizon Sensitivity
| sample | book | horizon_days | windows | pass_rate | fail_rate | push_rate | median_days_to_target | daily_loss_breaches | max_loss_breaches | median_max_drawdown_pct | opened_trades | skipped_slot | skipped_daily_risk | skipped_regime |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| long_mr_strong4 | hard_gate_skip_high | 120 | 113 | 3.5% | 0.9% | 95.6% | 104 | 0 | 1 | 3.4% | 5248 | 87039 | 0 | 52908 |
| long_mr_strong4 | hard_gate_skip_high | 365 | 113 | 24.8% | 2.7% | 72.6% | 228 | 0 | 3 | 6.2% | 13808 | 239319 | 0 | 148901 |
| long_mr_strong4 | size_down_high_0_5 | 120 | 113 | 0.9% | 0.0% | 99.1% | 77 | 0 | 0 | 3.3% | 6521 | 139824 | 0 | 0 |
| long_mr_strong4 | size_down_high_0_5 | 365 | 113 | 23.0% | 8.0% | 69.0% | 259 | 0 | 9 | 4.9% | 17252 | 389593 | 0 | 0 |
| long_mr_strong4 | unconditioned | 120 | 113 | 4.4% | 1.8% | 93.8% | 77 | 0 | 2 | 4.1% | 6397 | 137092 | 10 | 0 |
| long_mr_strong4 | unconditioned | 365 | 113 | 31.0% | 15.0% | 54.0% | 243 | 0 | 17 | 6.4% | 15939 | 361953 | 10 | 0 |

## Slot And Redeployment
The position-count cap binds heavily. `size_down_high_0_5` reduces high-ATR dollars at risk but still consumes one of the three slots, so it does not materially redeploy freed count capacity into low/mid trades. Hard-gate frees count slots by skipping high ATR entirely, but that is the same throughput cut P3 flagged.
| book | opened_trades | low_mid_opened | high_opened | skipped_slot | low_mid_slot_blocks | high_slot_blocks | skipped_daily_risk | low_mid_daily_risk_blocks | high_daily_risk_blocks | skipped_regime |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hard_gate_skip_high | 7577 | 7577 | 0 | 128534 | 128534 | 0 | 0 | 0 | 0 | 78320 |
| size_down_high_0_5 | 9444 | 5134 | 4310 | 207653 | 132835 | 74818 | 0 | 0 | 0 | 0 |
| unconditioned | 9145 | 4939 | 4206 | 201270 | 128296 | 72974 | 10 | 0 | 10 | 0 |

## Method
Trade stream: deployed long-MR strong-4 primary sleeve and long-MR full-6 cross-check, deduped one trade per `(pair, entry_bar)`, mid-entry 1%/1% R converted to account P/L using the deployed 0.5% base risk and the book's ATR-regime multiplier. Entries are accepted sequentially under the three-position cap and 4% daily risk cap; exits realize per-trade R at the H4 exit timestamp. FTMO daily-loss, max-loss, target, and minimum-trading-day enforcement is delegated to `FtmoRuleEngine`; only the null max-trading-days Swing guard is wrapped locally.
Rolling starts are every 30 calendar days (`30D`) and each window is censored at 120, 180, and 365 calendar days. A pass requires target hit before breach and at least the configured minimum trading days; a fail is a daily/max-loss breach; a push is horizon expiry with neither.

## Artifacts
- `atr_regime_p4_ftmo.csv`: window rows plus aggregate rows.
- `atr_regime_p4_ftmo.out`: run summary.

Production wiring is intentionally out of scope for P4.

## Bubo Audit & Per-Trade Re-cut (2026-06-14)

The harness above is sound (timestamp-index bug self-caught; null-timer guard wired; verified $10k
Swing config + deployed 0.5% risk / 3-slot cap). But the **pass-rate headline is the wrong lens**,
for two reasons:

1. **It is throughput/sizing-limited, not edge-limited.** At the deployed 0.5% risk the strong-4 MR
   book is *push-dominated* (88–95% of 180-day windows never reach +10%). Pass-rate mostly measures
   "can the book race to +10% in the window," which is a function of bet size, not of whether the
   conditioner picks better trades. The Swing config has `max_trading_days = null` (no timer), so a
   push is ~free — you keep trading — making **fail-avoidance**, not pass-timing, the real objective.
2. **The 180-day pass deltas are noise.** Windows step 30d but span 180d (6× overlap → ~19
   independent blocks); 10 vs 6 passes is not distinguishable. The one robust, monotone signal is
   **fewer blow-ups**: max-loss breaches 17→3 (hard_gate) / 17→9 (size_down) at 365d.

Per **Brand's steer**, judge the conditioner on the *trades themselves* — total PnL / per-trade R
and win rate, calm (low+mid ATR) vs choppy (high ATR), no +10% target. See
`atr_regime_p4_pertrade.py` / `.csv` / `ATR_REGIME_P4_PERTRADE.md`.

**Strong-4 book, per-trade:**

| Market | Trades | Win rate | Avg R | Total R |
| --- | --- | --- | --- | --- |
| Calm (low+mid ATR) | 25,673 | 52.6% | +0.051 | +1317 |
| Choppy (high ATR) | 14,480 | 49.2% | −0.011 | −160 |
| low | 13,850 | 53.0% | +0.057 | +789 |
| mid | 11,823 | 52.1% | +0.045 | +528 |
| high | 14,480 | 49.2% | −0.011 | −160 |

Win rate is **monotone in calm** (53.0% → 52.1% → 49.2%); the choppy third wins <50% and is a net
loser. So the volatility filter raises win rate and trims a money-losing slice — same direction.

**Audited verdict:** the vol-regime conditioner survives FTMO as a **modest risk/dead-weight trim**,
not a pass-rate engine; `hard_gate_skip_high` is the constraint-optimal form (reverses P3's R-space
preference for `size_down`). The conditioner is a second-order overlay — the **first-order PnL lever
is exit geometry** (take-profit / stop / hold), which the campaign held fixed at 1:1 / 14d and never
swept. **Next phase = exit-geometry sweep ranked by total PnL at a survivable drawdown**, vol-filter
layered on, validated split-sample (interleaved time blocks so every era incl. COVID lands in both
halves) + a held-out recent-years dress rehearsal for decay.

**Open gap:** P4 has no exposure-matched uniform-downsize control, so "regime targeting earned the
fail reduction" rests on P3's R-space arbiter, not P4 itself.
