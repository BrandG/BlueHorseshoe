# FTMO Rules Specification

**Status:** canonical FTMO rule spec for BH FTMO (Phase 1 deliverable per decisions 5A + 7).
**Authority:** this document is the contract. Phase 3 backtest simulation (`backtest/engine.py` FTMO rule enforcement) implements it. If they disagree, verify against Brand's live FTMO dashboard first, then fix whichever is wrong.
**Drafted:** 2026-04-24

---

## 1. Purpose

The backtest simulates FTMO rule outcomes (challenge passed / failed / in-progress) on historical trade sequences. To be faithful, the simulation must honor the exact thresholds, timing, and precedence that FTMO enforces on the live account. Getting any of these wrong produces a backtest number that looks good but a live account that blows up.

This spec codifies every FTMO rule that affects whether a simulated trade sequence passes or fails.

## 2. Account-Specific Parameters (FILL IN BEFORE PHASE 3)

**These must be verified against Brand's FTMO dashboard before Phase 3 backtest code runs.** Placeholder values below are TYPICAL for a $100k FTMO Standard Challenge; they are NOT Brand's actuals.

| Parameter | Source of truth | Current value (TBD) |
| --- | --- | --- |
| Initial balance | FTMO account dashboard | `$TBD` (e.g., $100,000) |
| Account currency | FTMO account dashboard | `TBD` (likely USD) |
| Challenge phase | FTMO account dashboard | `TBD` (Challenge / Verification / Funded) |
| Profit target | FTMO rules page | `TBD %` (Challenge typically 10%; Verification 5%; Funded 0%) |
| Daily loss limit | FTMO rules page | `TBD %` (typically 5%) |
| Max loss (overall drawdown) | FTMO rules page | `TBD %` (typically 10%) |
| Min trading days | FTMO rules page | `TBD` (typically 4; Funded typically 0) |
| Max trading days | FTMO rules page | `TBD` (Challenge 30, Verification 60, Funded unlimited) |
| Commission model | FTMO trading conditions | `TBD` (e.g., ~$3/lot round-turn on FTMO Standard) |
| Swap model | FTMO trading conditions | `TBD` (Standard vs Swap-Free) |
| Server time zone | FTMO rules page | `TBD` (typically CE(S)T) |

Persist these once verified to `src/bh_ftmo_config.json` under a new `ftmo` block:

```json
"ftmo": {
  "initial_balance_usd": 100000,
  "phase": "challenge",
  "profit_target_pct": 0.10,
  "daily_loss_pct": 0.05,
  "max_loss_pct": 0.10,
  "min_trading_days": 4,
  "max_trading_days": 30,
  "server_timezone": "Europe/Prague",
  "commission_per_lot_round_turn_usd": 3.0,
  "swap_model": "standard"
}
```

Phase 3 loads this block and runs the simulation from it — no hard-coded values in engine code.

## 3. Hard Rules (Fail-on-Breach)

Any one of these breaching ends the simulation as **FAIL** for the current challenge. All open positions are closed at the breaching moment. No further trades count.

### 3.1 Daily Loss Limit

**Rule.** Equity at any instant during the FTMO trading day must not fall below `reference_equity − daily_loss_pct × initial_balance`.

- `reference_equity` = account equity at the last FTMO-day rollover (see §5 for timing).
- **Equity** = cash balance + sum of floating P&L on open positions (mark-to-market).
- Spread is part of floating P&L — a position is instantly "down" by the spread when opened.
- Swap charges are part of the day's equity trajectory.

**Breach is instantaneous.** If equity touches the threshold intrabar, it's a breach, even if the bar closes back above it. Simulation must resolve this at 1h granularity (see decision 4A) — if stop+target bracket both sit inside a 4h bar's H-L range and the 1h path shows the breach touched, it's a breach.

### 3.2 Maximum Loss (Overall Drawdown)

**Rule.** Equity at any instant from challenge start must not fall below `initial_balance × (1 − max_loss_pct)`.

- This is an absolute floor, not relative to a daily baseline.
- Same instantaneous-breach semantics as §3.1.
- FTMO refers to this as "Maximum Loss" or "Trailing Drawdown"; confirm which variant applies to Brand's account. Static max-loss uses `initial_balance` as the anchor; trailing variant (less common on Challenge/Verification, standard on Funded) uses running peak equity — **check FTMO dashboard for Brand's account**.

### 3.3 Profit Target (Pass Condition, Not a Fail)

**Rule.** Equity reaches `initial_balance × (1 + profit_target_pct)` at any instant.

- Once hit, the challenge is eligible to pass, **subject to §4.1 (min trading days)**.
- On reaching the target, continue simulating to end of period (challenge doesn't auto-end on target-hit), but record the moment for pass-path reporting.

## 4. Soft Rules (Pass Conditions, Not Fails)

These gate whether a challenge passes at period end. They do not trigger intrabar fails.

### 4.1 Minimum Trading Days

A "trading day" is a day (FTMO-calendar, per §5) on which at least one position was **opened or closed**. Days with only passive holds don't count.

- Pass requires `num_trading_days ≥ min_trading_days`.
- If §3 rules are not breached and profit target hit but trading days insufficient, the challenge ends WITHOUT pass at period end — a push, not a fail. Can retake.

### 4.2 Maximum Trading Days

Challenge period ends after `max_trading_days` calendar days from first trade (or account issuance — verify with FTMO). If profit target not hit by then, it's a push (no fail record, but no pass either).

## 5. Timing (Reset Boundaries + Swap)

### 5.1 FTMO Trading Day Boundary

FTMO server time is **CE(S)T**: UTC+1 (CET, winter) / UTC+2 (CEST, summer). The daily loss baseline (`reference_equity`, §3.1) resets at `00:00 server time`.

In NY local terms:
- Winter (CET, roughly Nov–Mar): 00:00 CET = 18:00 EST = 23:00 UTC
- Summer (CEST, roughly Mar–Nov): 00:00 CEST = 18:00 EDT = 22:00 UTC

**Note the mismatch with the BH FTMO H4 bar anchor.** Our bar grid is anchored at **NY 5pm** (`FX_TIME_SPEC.md` §2). FTMO's day boundary is **1 hour later** (6pm NY). The backtest must compute equity at FTMO-day boundaries, which may land mid-H4-bar. Use the 1h store (plan decision 4A) for this; take equity from the 1h bar close at FTMO-reset time.

### 5.2 Swap / Rollover

**Standard accounts:** daily swap charge applied at FTMO's rollover (~00:00 server time). Wednesday carries **triple swap** to cover weekend non-trading days. Rate is instrument-specific and sign depends on direction (long vs. short) plus interest-rate differential.

**Swap-Free accounts:** no swap applied (if Brand's account is swap-free, this is confirmed on FTMO dashboard).

For simulation:
- Pull per-instrument swap rates from OANDA (`/accounts/{id}/instruments` exposes `financing.longRate` / `shortRate`) as a proxy; these are close-enough to FTMO's because both are OANDA-sourced.
- Apply `position_lots × rate × bar_duration` each day.
- Triple Wednesday: 3× the usual amount.

### 5.3 Commission

Commission is charged per-lot per round-turn. Modeled per trade:
```
commission_per_trade = position_lots × commission_per_lot_round_turn_usd
```

Applied at position open (half) and close (half), or entirely at close — backtest can simplify to full charge at close as long as total is correct.

## 6. Rule-Interaction Precedence

When multiple rules fire in the same bar, resolution order is:

1. **§3.2 Max loss** — checked FIRST. If breached, fail immediately; no further rules evaluated.
2. **§3.1 Daily loss** — checked second. Same-bar simultaneity: if max loss and daily loss both breach, report as max loss (more severe).
3. **§3.3 Profit target** — checked third. If a bar has profit target touched AND daily loss breached on the same bar, DAILY LOSS WINS. (The breach is a fail; the target doesn't retroactively save you.)

Intrabar ordering (via 1h path per decision 4A):
- The 1h bar sequence within a 4h bar determines which hit happens first
- If both stop and target sit inside the same 1h bar's H-L range (rare edge case): flag the trade as **unresolved** per decision C-1; exclude from P&L, count in "unresolved" metric.

## 7. Simulation Semantics

### 7.1 Position Closing on Breach

When a hard rule breaches:
- All open positions close at the current instant's price (same side of spread as a normal market exit: longs close at bid, shorts at ask).
- Resulting P&L is included in the breach-triggering equity calculation (not double-counted).
- Simulation records `challenge_result = "failed"`, `failed_by = "<rule>"`, `failed_at = <timestamp>`.

### 7.2 Position Opening After Breach

After a failed challenge, NO new positions open. Simulation either:
- Continues emitting "would-have" signals for observability, marked as post-fail (not counted toward any metric), OR
- Halts simulation entirely (simpler — pick this for v1).

### 7.3 Randomized-Start Backtest

Per plan §Phase 3: run challenge simulations from many randomized start dates across the backtest window. Report pass rate (§3.3 target hit AND §4.1 trading days met AND no §3 breach) across N starts. This is the headline "FTMO pass rate" metric.

**Gate:** ≥70% pass rate across randomized start dates (plan §Phase 3 entry-edge gate criterion).

## 8. Operational Reminders

### 8.1 Quarterly OANDA API Token Rotation (Decision C-2)

OANDA personal-access tokens do not auto-expire, but long-lived tokens are a security liability. Rotate quarterly:

- Regenerate token at [OANDA account portal](https://www.oanda.com) → API Access
- Update `.env` file
- Restart any long-running BH FTMO processes (cron pulls from `.env` each run, so no restart needed there)
- Add a calendar reminder for the next rotation

Last rotation: `(fill in when done first)`

### 8.2 FTMO Rule Drift

FTMO periodically updates their rules (profit target %, daily loss %, max days). Check the current rules page quarterly against §2 and §3 of this doc. If thresholds changed:

1. Update `bh_ftmo_config.json` `ftmo` block
2. Update §2 table in this doc
3. Re-run Phase 3 backtest gate (plan §Phase 3 entry-edge gate) with new thresholds; if no longer passing, debug before resuming live trading
4. Note the change date in §9

## 9. Change Log

| Date | Change | Source |
| --- | --- | --- |
| 2026-04-24 | Initial draft | Plan Phase 1 deliverable |

## 10. Sources to Cross-Check Before Phase 3

Before Phase 3 backtest code runs, verify §2 + §3 values against:

- FTMO Rules page (main): https://ftmo.com/en/trading-rules/
- FTMO Account Profile → Rules tab (Brand's specific account)
- FTMO Trading Conditions: https://ftmo.com/en/trading-conditions/
- OANDA financing rates (for swap cross-check): `GET /v3/accounts/{id}/instruments`

When in doubt, **Brand's FTMO dashboard is the ultimate authority** — this document is a cache of that truth.
