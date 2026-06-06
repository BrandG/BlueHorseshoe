# LOCKED RULE — Deep-Oversold × Heiken-Ashi Green (Gordon equity entry, v1)

**Status:** spec FROZEN 2026-06-06. In-sample (2016–2026) validated. **WIRED 2026-06-06** as the
`deep_oversold_ha` strategy (display `DeepOS+HA`) — tracked by the hypothesis engine AND eligible for
live paper orders (legacy slot pool). Now accumulating out-of-sample forward-R; that live record is
the real holdout gate before sizing up.

**Implementation note:** the live sleeve is a subclass of `DeepOversoldStrategy` and inherits its exact
constants, including `DEEP_OVERSOLD_MIN_AGE` (fires at 3 consecutive oversold bars by DeepOS's count
convention — a 1-bar difference from this doc's research age≥3/≥4-close wording, immaterial to the
monotone-in-depth edge) and the **$25M** $-vol floor (DeepOS's, stricter than the $1M below; the
gauntlet showed the edge is strongest in the >$25M tier anyway). The two added gates — SPY-nonbull and
true-recursive HA-green — are exactly as specified below. It does NOT use the production
`calculate_heiken_ashi()` (non-recursive open). Code: `strategy_interface.DeepOversoldHAStrategy`,
registered in `strategy_registry.py`. A within-run symbol guard in `paper_trader` prevents DeepOS and
DeepOS+HA from double-ordering the same name.
**Lineage:** [[project_heiken_ashi_deepdive]] (Findings 4–5), built on the validated deep-oversold
edge [[project_rsi_oversold_bracket_edge]]. Evidence: `ha_deep_stack_gauntlet.out`,
`ha_confluence_gauntlet.out`, `ha_nw_sweep.out`, `ha_incremental.out`.

This is the **high-conviction tier** of the contrarian sleeve: rare, high per-trade R. It is an
ENTRY-TIMING overlay, not new alpha — the HA green candle confirms the deep-oversold dislocation is
turning. The simpler `green` form is locked (the strict `flip`/red-yesterday requirement was inert:
deep_green +0.404R ≈ deep_flip +0.435R nonbull S4).

---

## Signal (all conditions must hold on the signal bar's close)

1. **Regime gate (mandatory):** SPY is **nonbull** = NOT(`SPY.close > EMA200(SPY)` AND
   `EMA50(SPY) > EMA200(SPY)`), evaluated on SPY daily closes.
   *Ungated (all-regime) this rule is a NET-NEGATIVE filter (−0.057R vs the bare deep rule) — the
   gate is not optional.*
2. **Deep oversold:** `RSI(14) < 30` for at least **4 consecutive closes** (harness convention:
   consecutive-oversold `age ≥ 3`, `THR=3`, 0-indexed — fires on the 4th+ oversold bar).
3. **Heiken-Ashi green:** current **true recursive** HA candle is bullish, `HA_close > HA_open`, where
   - `HA_close = (O + H + L + C) / 4`
   - `HA_open[0] = (O[0] + C[0]) / 2`;  `HA_open[t] = (HA_open[t-1] + HA_close[t-1]) / 2`
   - ⚠️ Use the RECURSIVE open. The production `calculate_heiken_ashi()` uses a non-recursive
     approximation `(prevO + prevC)/2` — that is NOT this signal and must not be substituted.

## Universe / eligibility (per symbol, per bar)
- Price `$5 ≤ close ≤ $500`
- 20-day avg share volume `> 100,000`
- `ATR(14)/close ≥ 0.005` (0.5% vol floor)
- **Recommended liquidity floor:** 20-day avg dollar-volume `≥ $1,000,000` (edge concentrates in
  liquid names; the `<$1M` tier is thin/insignificant — consistent with the rest of the book).

## Execution (bracket)
- **Entry:** next-day **market open** after the signal close (signal is only known at close).
- **Stop:** `entry − 1 × ATR(14)`. If the bar gaps through the stop, fill at that bar's **open**
  (worse than −1R is realistic and was priced into the validated result).
- **Target:** `entry + 2 × ATR(14)` (2:1 reward:risk).
- **Timeout:** exit at the **close of the 10th bar** after entry if neither level is hit.
- **De-overlap:** at most one open position per symbol at a time (no re-entry for 10 bars).

## Frozen measured performance (in-sample 2016–2026, nonbull, S4-realistic frictions)
Frictions = next-open entry + gap-through stops + liquidity-tiered round-trip cost; de-overlapped,
symbol-clustered.

| metric | value |
|---|---|
| per-trade R (deep_green, locked form) | **+0.404R**, t +7.4 |
| benchmark: bare deep rule (nonbull S4) | +0.244R, t +7.9 |
| incremental over bare deep | **+0.16R / trade** |
| win rate (deep_flip proxy; green ≈ same) | ~54% |
| de-overlapped trades (11y, nonbull) | ~746 (~68 / yr) |
| year stability (nonbull) | every sampled year positive incl crashes 2020 +0.49 / 2022 +0.15 / 2025 +0.97 |
| cost robustness | S0 ideal +0.436R → S4 realistic +0.404R (barely degrades) |

## Character & deployment notes
- **Low-frequency, high-conviction:** ~68 nonbull trades/yr across a 2000-name universe — a handful
  of names firing at once. Selective sleeve / overweight tier, not a workhorse.
- **Complementary breadth tier exists** (Finding 4): `ha_flip_up × (rsi<30 OR below-cloud)`,
  nonbull-gated = +0.264R, n≈15,200. Same family, ~20× more trades, lower per-trade R. The two can be
  tiered (this rule as the high-conviction overweight inside that broader sleeve).
- **Open risk:** still in-sample; year-split is the robustness proxy. Watch the live fire rate before
  sizing — n is healthy for a clustered t but thin enough to respect.

## Out of scope for v1 (do not silently add)
Trailing stops, partial take-profits, per-name position sizing, alternate hold windows. Any of these
is a v2 change requiring its own gauntlet pass.
